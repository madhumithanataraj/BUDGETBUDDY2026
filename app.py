import logging
import os
import secrets
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from postgrest.exceptions import APIError
from supabase import AuthError, Client, create_client


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")
AUTH_SESSION_DB = PROJECT_ROOT / ".data" / "auth_sessions.sqlite3"

app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / ".dist" / "templates"),
    static_folder=str(PROJECT_ROOT / "static"),
    static_url_path="/static",
)

app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_REFRESH_EACH_REQUEST=False,
)


@app.before_request
def use_browser_only_session() -> None:
    session.permanent = False


if not os.environ.get("FLASK_SECRET_KEY"):
    logger.warning(
        "FLASK_SECRET_KEY is not set; sessions will be invalidated when the app restarts."
    )

supabase_url = os.environ.get("SUPABASE_URL") or os.environ.get(
    "NEXT_PUBLIC_SUPABASE_URL"
)
supabase_key = (
    os.environ.get("SUPABASE_KEY")
    or os.environ.get("SUPABASE_ANON_KEY")
    or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    or os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
)
supabase: Client | None = None

if supabase_url and supabase_key:
    supabase = create_client(supabase_url, supabase_key)
else:
    logger.warning(
        "Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY "
        "(or SUPABASE_ANON_KEY / SUPABASE_PUBLISHABLE_KEY) in .env."
    )


def _initialize_auth_session_store() -> None:
    AUTH_SESSION_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(AUTH_SESSION_DB) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                session_id TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def _store_auth_tokens(access_token: str, refresh_token: str) -> str:
    _initialize_auth_session_store()
    session_id = secrets.token_urlsafe(32)
    with sqlite3.connect(AUTH_SESSION_DB) as connection:
        connection.execute(
            """
            INSERT INTO auth_sessions (session_id, access_token, refresh_token, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, access_token, refresh_token, datetime.now().isoformat()),
        )
    return session_id


def _get_auth_tokens(session_id: str) -> tuple[str, str] | None:
    _initialize_auth_session_store()
    with sqlite3.connect(AUTH_SESSION_DB) as connection:
        row = connection.execute(
            "SELECT access_token, refresh_token FROM auth_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return (row[0], row[1]) if row else None


def _save_refreshed_tokens(session_id: str, client: Client) -> None:
    auth_session = client.auth.get_session()
    if auth_session is None:
        return
    with sqlite3.connect(AUTH_SESSION_DB) as connection:
        connection.execute(
            """
            UPDATE auth_sessions
            SET access_token = ?, refresh_token = ?, updated_at = ?
            WHERE session_id = ?
            """,
            (
                auth_session.access_token,
                auth_session.refresh_token,
                datetime.now().isoformat(),
                session_id,
            ),
        )


def _delete_auth_tokens(session_id: str | None) -> None:
    if not session_id or not AUTH_SESSION_DB.exists():
        return
    with sqlite3.connect(AUTH_SESSION_DB) as connection:
        connection.execute(
            "DELETE FROM auth_sessions WHERE session_id = ?", (session_id,)
        )


def _authenticated_client() -> Client | None:
    if supabase is None:
        return None
    auth_session_id = session.get("auth_session_id")
    tokens = _get_auth_tokens(auth_session_id) if auth_session_id else None
    if tokens is None:
        return None
    client = create_client(supabase_url, supabase_key)
    client.auth.set_session(tokens[0], tokens[1])
    return client


def _persist_client_tokens(client: Client) -> None:
    auth_session_id = session.get("auth_session_id")
    if auth_session_id:
        _save_refreshed_tokens(auth_session_id, client)


def _require_client() -> Client | None:
    client = _authenticated_client()
    if client is None:
        flash("Please log in to continue.", "error")
        return None
    return client


def _parse_amount(value: str) -> Decimal | None:
    try:
        amount = Decimal(value).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite() or not Decimal("0") < amount <= Decimal("1000000000"):
        return None
    return amount


def _current_month() -> date:
    today = date.today()
    return date(today.year, today.month, 1)


def _parse_month(value: str) -> date | None:
    try:
        if len(value) == 7:
            value = f"{value}-01"
        parsed = date.fromisoformat(value)
        return date(parsed.year, parsed.month, 1)
    except ValueError:
        return None


def _get_monthly_data(client: Client, month: date) -> tuple[list[dict], dict | None]:
    month_start = month.replace(day=1)
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    expenses_result = (
        client.table("expenses")
        .select("id,title,description,amount,category,spent_on,notes")
        .gte("spent_on", month_start.isoformat())
        .lt("spent_on", next_month.isoformat())
        .order("spent_on", desc=True)
        .execute()
    )
    budget_result = (
        client.table("monthly_budgets")
        .select("id,amount,month")
        .eq("month", month_start.isoformat())
        .limit(1)
        .execute()
    )
    expenses = [
        {**expense, "title": expense.get("title") or expense.get("description")}
        for expense in expenses_result.data or []
        if expense.get("title") or expense.get("description")
        and expense.get("category")
        and expense.get("spent_on")
        and expense.get("amount") is not None
    ]
    budget = budget_result.data[0] if budget_result.data else None
    return expenses, budget


def _database_error(error: APIError, action: str) -> None:
    logger.error("Supabase %s failed: %s", action, error)
    flash(
        "Could not access your financial data. Check your Supabase table setup, "
        "then try again.",
        "error",
    )


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/features")
def features():
    return render_template("features.html")


@app.get("/dashboard")
def dashboard():
    client = _require_client()
    if client is None:
        return redirect(url_for("login"))

    try:
        month = _current_month()
        expenses, budget = _get_monthly_data(client, month)
        _persist_client_tokens(client)
    except APIError as error:
        _database_error(error, "dashboard query")
        expenses, budget = [], None

    total_spent = sum(
        (Decimal(str(expense["amount"])) for expense in expenses), Decimal("0")
    )
    budget_amount = Decimal(str(budget["amount"])) if budget else None
    return render_template(
        "dashboard.html",
        user_name=session.get("user_name") or "there",
        expenses=expenses[:5],
        total_spent=total_spent,
        budget_amount=budget_amount,
        remaining=budget_amount - total_spent if budget_amount is not None else None,
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")

    if supabase is None:
        flash("Account registration is not configured yet.", "error")
        return redirect(url_for("signup"))

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    if not name or not email or not password:
        flash("Please complete all fields.", "error")
        return redirect(url_for("signup"))

    try:
        result = supabase.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {"data": {"full_name": name}},
            }
        )
    except AuthError as error:
        logger.info("Supabase sign-up rejected: %s", error)
        flash("Sign-up failed. Check your details and Supabase email settings.", "error")
        return redirect(url_for("signup"))

    if result.session is not None and result.user is not None:
        session.clear()
        session.permanent = False
        session["user_id"] = result.user.id
        session["user_email"] = result.user.email
        session["user_name"] = name
        session["auth_session_id"] = _store_auth_tokens(
            result.session.access_token, result.session.refresh_token
        )
        flash("Your account is ready.", "success")
        return redirect(url_for("dashboard"))

    flash("Account created. Check your email to confirm it, then log in.", "success")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    if supabase is None:
        flash("Login is not configured yet.", "error")
        return redirect(url_for("login"))

    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    if not email or not password:
        flash("Enter your email address and password.", "error")
        return redirect(url_for("login"))

    try:
        result = supabase.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except AuthError as error:
        logger.info("Supabase sign-in rejected for %s: %s", email, error)
        flash("Login failed. Check your details and try again.", "error")
        return redirect(url_for("login"))

    if result.user is None or result.session is None:
        logger.error("Supabase sign-in returned no user or session for %s", email)
        flash("Login could not be completed. Please try again.", "error")
        return redirect(url_for("login"))

    session.clear()
    session.permanent = False
    session["user_id"] = result.user.id
    session["user_email"] = result.user.email
    user_metadata = result.user.user_metadata or {}
    session["user_name"] = (
        user_metadata.get("full_name") or result.user.email.split("@")[0]
    )
    session["auth_session_id"] = _store_auth_tokens(
        result.session.access_token, result.session.refresh_token
    )
    flash("You are logged in.", "success")
    return redirect(url_for("dashboard"))


@app.route("/expenses", methods=["GET", "POST"])
def expenses():
    client = _require_client()
    if client is None:
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        amount = _parse_amount(request.form.get("amount", ""))
        category = request.form.get("category", "").strip()
        spent_on = request.form.get("spent_on", "").strip()
        notes = request.form.get("notes", "").strip()
        try:
            date.fromisoformat(spent_on)
        except ValueError:
            spent_on = ""
        if not title or len(title) > 120 or amount is None or not category or not spent_on:
            flash("Enter a title, valid amount, category, and date.", "error")
            return redirect(url_for("expenses"))
        if len(category) > 60 or len(notes) > 500:
            flash("Category or notes are too long.", "error")
            return redirect(url_for("expenses"))

        try:
            client.table("expenses").insert(
                {
                    "user_id": session["user_id"],
                    "title": title,
                    "description": title,
                    "amount": str(amount),
                    "category": category,
                    "spent_on": spent_on,
                    "notes": notes or None,
                }
            ).execute()
            _persist_client_tokens(client)
        except APIError as error:
            _database_error(error, "expense insert")
            return redirect(url_for("expenses"))
        flash("Expense added.", "success")
        return redirect(url_for("expenses"))

    try:
        result = (
            client.table("expenses")
            .select("id,title,description,amount,category,spent_on,notes")
            .order("spent_on", desc=True)
            .limit(200)
            .execute()
        )
        _persist_client_tokens(client)
    except APIError as error:
        _database_error(error, "expense list")
        expenses_list = []
    else:
        expenses_list = [
            {**expense, "title": expense.get("title") or expense.get("description")}
            for expense in result.data or []
            if expense.get("title") or expense.get("description")
            and expense.get("category")
            and expense.get("spent_on")
            and expense.get("amount") is not None
        ]
    return render_template(
        "expenses.html",
        expenses=expenses_list,
        today=date.today().isoformat(),
        categories=("Food", "Transport", "Housing", "Education", "Shopping", "Health", "Other"),
    )


@app.post("/expenses/<expense_id>/delete")
def delete_expense(expense_id: str):
    client = _require_client()
    if client is None:
        return redirect(url_for("login"))
    try:
        client.table("expenses").delete().eq("id", expense_id).execute()
        _persist_client_tokens(client)
    except APIError as error:
        _database_error(error, "expense deletion")
        return redirect(url_for("expenses"))
    flash("Expense deleted.", "success")
    return redirect(url_for("expenses"))


@app.post("/expenses/<expense_id>/edit")
def edit_expense(expense_id: str):
    client = _require_client()
    if client is None:
        return redirect(url_for("login"))
    title = request.form.get("title", "").strip()
    amount = _parse_amount(request.form.get("amount", ""))
    category = request.form.get("category", "").strip()
    spent_on = request.form.get("spent_on", "").strip()
    notes = request.form.get("notes", "").strip()
    try:
        date.fromisoformat(spent_on)
    except ValueError:
        spent_on = ""
    if not title or len(title) > 120 or amount is None or not category or not spent_on:
        flash("Enter a title, valid amount, category, and date.", "error")
        return redirect(url_for("expenses"))
    if len(category) > 60 or len(notes) > 500:
        flash("Category or notes are too long.", "error")
        return redirect(url_for("expenses"))
    try:
        client.table("expenses").update(
            {
                "title": title,
                "description": title,
                "amount": str(amount),
                "category": category,
                "spent_on": spent_on,
                "notes": notes or None,
            }
        ).eq("id", expense_id).execute()
        _persist_client_tokens(client)
    except APIError as error:
        _database_error(error, "expense update")
        return redirect(url_for("expenses"))
    flash("Expense updated.", "success")
    return redirect(url_for("expenses"))


@app.route("/budget", methods=["GET", "POST"])
def budget():
    client = _require_client()
    if client is None:
        return redirect(url_for("login"))

    month_value = request.values.get("month", _current_month().strftime("%Y-%m"))
    month = _parse_month(month_value)
    if month is None:
        flash("Choose a valid budget month.", "error")
        return redirect(url_for("budget"))

    if request.method == "POST":
        amount = _parse_amount(request.form.get("amount", ""))
        if amount is None:
            flash("Enter a budget greater than zero.", "error")
            return redirect(url_for("budget", month=month.strftime("%Y-%m")))
        try:
            client.table("monthly_budgets").upsert(
                {
                    "user_id": session["user_id"],
                    "month": month.isoformat(),
                    "amount": str(amount),
                },
                on_conflict="user_id,month",
            ).execute()
            _persist_client_tokens(client)
        except APIError as error:
            _database_error(error, "budget save")
            return redirect(url_for("budget", month=month.strftime("%Y-%m")))
        flash("Monthly budget saved.", "success")
        return redirect(url_for("budget", month=month.strftime("%Y-%m")))

    try:
        expenses_for_month, saved_budget = _get_monthly_data(client, month)
        _persist_client_tokens(client)
    except APIError as error:
        _database_error(error, "budget query")
        expenses_for_month, saved_budget = [], None
    spent = sum(
        (Decimal(str(expense["amount"])) for expense in expenses_for_month),
        Decimal("0"),
    )
    amount = Decimal(str(saved_budget["amount"])) if saved_budget else None
    return render_template(
        "budget.html",
        month=month.isoformat(),
        budget_amount=amount,
        total_spent=spent,
        remaining=amount - spent if amount is not None else None,
    )


@app.route("/save-budget", methods=["GET", "POST"])
def save_budget():
    client = _require_client()
    if client is None:
        return redirect(url_for("login"))

    month_value = request.values.get("month", _current_month().strftime("%Y-%m"))
    month = _parse_month(month_value)
    if month is None:
        flash("Choose a valid budget month.", "error")
        return redirect(url_for("save_budget"))

    if request.method == "POST":
        amount = _parse_amount(request.form.get("amount", ""))
        if amount is None:
            flash("Enter a budget greater than zero.", "error")
            return redirect(url_for("save_budget", month=month.strftime("%Y-%m")))
        try:
            client.table("monthly_budgets").upsert(
                {
                    "user_id": session["user_id"],
                    "month": month.isoformat(),
                    "amount": str(amount),
                },
                on_conflict="user_id,month",
            ).execute()
            _persist_client_tokens(client)
        except APIError as error:
            _database_error(error, "budget save")
            return redirect(url_for("save_budget", month=month.strftime("%Y-%m")))
        flash("Monthly budget saved.", "success")
        return redirect(url_for("budget", month=month.strftime("%Y-%m")))

    saved_amount = None
    try:
        result = (
            client.table("monthly_budgets")
            .select("amount")
            .eq("month", month.isoformat())
            .limit(1)
            .execute()
        )
        _persist_client_tokens(client)
        if result.data:
            saved_amount = Decimal(str(result.data[0]["amount"]))
    except APIError as error:
        _database_error(error, "budget query")

    return render_template(
        "save.html",
        month=month.strftime("%Y-%m"),
        budget_amount=saved_amount,
    )


@app.get("/reports")
def reports():
    client = _require_client()
    if client is None:
        return redirect(url_for("login"))

    today = date.today()
    six_months_ago = date(today.year, today.month, 1)
    for _ in range(5):
        if six_months_ago.month == 1:
            six_months_ago = date(six_months_ago.year - 1, 12, 1)
        else:
            six_months_ago = date(six_months_ago.year, six_months_ago.month - 1, 1)
    try:
        result = (
            client.table("expenses")
            .select("title,description,amount,category,spent_on")
            .gte("spent_on", six_months_ago.isoformat())
            .order("spent_on", desc=True)
            .execute()
        )
        _persist_client_tokens(client)
    except APIError as error:
        _database_error(error, "report query")
        report_expenses = []
    else:
        report_expenses = [
            {**expense, "title": expense.get("title") or expense.get("description")}
            for expense in result.data or []
            if expense.get("category")
            and expense.get("spent_on")
            and expense.get("amount") is not None
        ]

    category_totals: dict[str, Decimal] = {}
    month_totals: dict[str, Decimal] = {}
    for expense in report_expenses:
        amount = Decimal(str(expense["amount"]))
        category = expense["category"]
        expense_month = expense["spent_on"][:7]
        category_totals[category] = category_totals.get(category, Decimal("0")) + amount
        month_totals[expense_month] = month_totals.get(expense_month, Decimal("0")) + amount
    months = sorted(month_totals.items())
    return render_template(
        "report.html",
        total=sum(
            (Decimal(str(expense["amount"])) for expense in report_expenses),
            Decimal("0"),
        ),
        expense_count=len(report_expenses),
        category_totals=sorted(category_totals.items(), key=lambda item: item[1], reverse=True),
        months=[
            {
                "label": datetime.strptime(month, "%Y-%m").strftime("%b %Y"),
                "amount": amount,
                "width": float(amount / max(value for _, value in months) * 100)
                if months
                else 0,
            }
            for month, amount in months
        ],
    )


@app.post("/logout")
def logout():
    _delete_auth_tokens(session.get("auth_session_id"))
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
