document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".form-message").forEach((message) => {
        window.setTimeout(() => {
            message.classList.add("is-dismissing");
            window.setTimeout(() => message.remove(), 200);
        }, 800);
    });

    const deleteDialog = document.querySelector("#delete-confirm-dialog");
    if (!deleteDialog) {
        return;
    }

    const confirmedForms = new WeakSet();
    let pendingDeleteForm = null;

    document.addEventListener("submit", (event) => {
        const form = event.target.closest(".delete-form");
        if (!form) {
            return;
        }

        if (confirmedForms.has(form)) {
            confirmedForms.delete(form);
            return;
        }

        event.preventDefault();
        pendingDeleteForm = form;
        deleteDialog.showModal();
        deleteDialog.querySelector("[data-dialog-cancel]").focus();
    });

    deleteDialog
        .querySelector("[data-dialog-cancel]")
        .addEventListener("click", () => {
            pendingDeleteForm = null;
            deleteDialog.close();
        });

    deleteDialog
        .querySelector("[data-dialog-confirm]")
        .addEventListener("click", () => {
            if (!pendingDeleteForm) {
                return;
            }
            const form = pendingDeleteForm;
            pendingDeleteForm = null;
            confirmedForms.add(form);
            deleteDialog.close();
            form.requestSubmit();
        });
});
