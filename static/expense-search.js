document.addEventListener("DOMContentLoaded", () => {
    const searchInput = document.querySelector("#expense-search");
    const expenseTable = document.querySelector("#expenses-table");
    const resultsMessage = document.querySelector("#expense-search-results");

    if (
        !(searchInput instanceof HTMLInputElement) ||
        !(expenseTable instanceof HTMLTableElement) ||
        !(resultsMessage instanceof HTMLElement)
    ) {
        return;
    }

    const rows = Array.from(expenseTable.querySelectorAll("tbody tr"));

    const filterExpenses = () => {
        const query = searchInput.value.trim().toLocaleLowerCase();
        let visibleRows = 0;

        for (const row of rows) {
            const values = Array.from(row.querySelectorAll("input, select"), (field) => field.value);
            const matches = values.some((value) => value.toLocaleLowerCase().includes(query));
            row.hidden = !matches;
            if (matches) {
                visibleRows += 1;
            }
        }

        resultsMessage.textContent = query
            ? `${visibleRows} of ${rows.length} expenses match your search.`
            : `${rows.length} expenses shown.`;
    };

    searchInput.addEventListener("input", filterExpenses);
    filterExpenses();
});
