// Confirm-before-submit: <form data-confirm="Remove this?">
// Replaces onsubmit="return confirm(...)" — using a data attribute means the
// value goes through normal HTML-attribute escaping only, never JS-string
// escaping, so it can't be used to break out into arbitrary script the way
// inline event-handler attributes can with unescaped quotes in user data.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (!window.confirm(form.dataset.confirm)) {
        e.preventDefault();
      }
    });
  });

  // Auto-submit on change: <input data-auto-submit>
  document.querySelectorAll("[data-auto-submit]").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.form) input.form.requestSubmit();
    });
  });
});
