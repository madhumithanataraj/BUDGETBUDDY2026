document.addEventListener("DOMContentLoaded", () => {
    const monthInput = document.querySelector("#month");
    const viewMonthButton = document.querySelector("#view-month");

    if (!(monthInput instanceof HTMLInputElement) || !(viewMonthButton instanceof HTMLButtonElement)) {
        return;
    }

    const monthForm = monthInput.form;
    if (!monthForm) {
        return;
    }

    viewMonthButton.addEventListener("click", () => {
        if (typeof monthInput.showPicker === "function") {
            monthInput.showPicker();
            return;
        }

        monthInput.focus();
        monthInput.click();
    });

    monthInput.addEventListener("change", () => monthForm.requestSubmit());
});
