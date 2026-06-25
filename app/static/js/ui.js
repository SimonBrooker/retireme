// Confirm-before-submit: <form data-confirm="Remove this?">
// Replaces onsubmit="return confirm(...)" — using a data attribute means the
// value goes through normal HTML-attribute escaping only, never JS-string
// escaping, so it can't be used to break out into arbitrary script the way
// inline event-handler attributes can with unescaped quotes in user data.
function checkForUpdate() {
  const badge = document.querySelector(".version-badge");
  if (!badge) return;
  const current = badge.dataset.version;
  fetch("https://api.github.com/repos/SimonBrooker/retireme/releases/latest", {
    headers: { Accept: "application/vnd.github+json" },
  })
    .then((r) => r.json())
    .then((data) => {
      const latest = (data.tag_name || "").replace(/^v/, "");
      if (latest && latest !== current) {
        badge.classList.add("update-available");
        badge.dataset.tooltip = `v${latest} available`;
        badge.setAttribute("role", "link");
        badge.setAttribute("tabindex", "0");
        badge.addEventListener("click", () => {
          window.open(data.html_url, "_blank", "noopener");
        });
        badge.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") window.open(data.html_url, "_blank", "noopener");
        });
      }
    })
    .catch(() => {}); // silently ignore — no network or rate limit
}

document.addEventListener("DOMContentLoaded", () => {
  checkForUpdate();
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
