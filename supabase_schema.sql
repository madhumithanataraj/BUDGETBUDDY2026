-- Run this script in Supabase Dashboard > SQL Editor before using expenses/budgets.

create table if not exists public.expenses (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    title text not null check (char_length(title) between 1 and 120),
    description text not null,
    amount numeric(12, 2) not null check (amount > 0),
    category text not null check (char_length(category) between 1 and 60),
    spent_on date not null default current_date,
    notes text check (notes is null or char_length(notes) <= 500),
    created_at timestamptz not null default now()
);

-- Add the application columns to an existing expenses table without deleting old data.
alter table public.expenses
    add column if not exists user_id uuid references auth.users(id) on delete cascade,
    add column if not exists title text,
    add column if not exists description text,
    add column if not exists amount numeric(12, 2),
    add column if not exists category text,
    add column if not exists spent_on date,
    add column if not exists notes text,
    add column if not exists created_at timestamptz default now();

create index if not exists expenses_user_spent_on_idx
    on public.expenses (user_id, spent_on desc);

create table if not exists public.monthly_budgets (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    month date not null check (extract(day from month) = 1),
    amount numeric(12, 2) not null check (amount > 0),
    created_at timestamptz not null default now(),
    unique (user_id, month)
);

alter table public.expenses enable row level security;
alter table public.monthly_budgets enable row level security;
grant select, insert, update, delete on public.expenses, public.monthly_budgets
    to authenticated;

drop policy if exists "Users can view their own expenses" on public.expenses;
create policy "Users can view their own expenses"
    on public.expenses for select to authenticated
    using (auth.uid() = user_id);

drop policy if exists "Users can add their own expenses" on public.expenses;
create policy "Users can add their own expenses"
    on public.expenses for insert to authenticated
    with check (auth.uid() = user_id);

drop policy if exists "Users can edit their own expenses" on public.expenses;
create policy "Users can edit their own expenses"
    on public.expenses for update to authenticated
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "Users can delete their own expenses" on public.expenses;
create policy "Users can delete their own expenses"
    on public.expenses for delete to authenticated
    using (auth.uid() = user_id);

drop policy if exists "Users can view their own budgets" on public.monthly_budgets;
create policy "Users can view their own budgets"
    on public.monthly_budgets for select to authenticated
    using (auth.uid() = user_id);

drop policy if exists "Users can add their own budgets" on public.monthly_budgets;
create policy "Users can add their own budgets"
    on public.monthly_budgets for insert to authenticated
    with check (auth.uid() = user_id);

drop policy if exists "Users can edit their own budgets" on public.monthly_budgets;
create policy "Users can edit their own budgets"
    on public.monthly_budgets for update to authenticated
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "Users can delete their own budgets" on public.monthly_budgets;
create policy "Users can delete their own budgets"
    on public.monthly_budgets for delete to authenticated
    using (auth.uid() = user_id);
