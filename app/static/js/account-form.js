const KID_ACCOUNT_TYPES = ["JISA", "JSIPP"];

function setupAccountTypeToggle(form) {
  const typeSelect = form.querySelector('select[name="type"]');
  const contribFields = form.querySelectorAll("[data-contribution-field]");
  const childField = form.querySelector("[data-child-field]");
  const adultOnlyRows = form.querySelectorAll("[data-adult-only-checkbox]");
  const withdrawalCheckbox = form.querySelector('input[name="include_in_withdrawal_calc"]');
  const stopCheckbox = form.querySelector('input[name="stop_contributions_at_retirement"]');
  if (!typeSelect) return;

  function syncContributionFields() {
    const isProperty = typeSelect.value === "PROPERTY";
    contribFields.forEach((field) => {
      field.style.display = isProperty ? "none" : "";
      const input = field.querySelector("input");
      if (input) {
        input.disabled = isProperty;
        if (isProperty) input.value = 0;
      }
    });
  }

  // Hard rule, applies on load and on change: junior accounts belong to a
  // child (so show/require that field) and never count toward the user's own
  // retirement figures (so those two checkboxes are greyed out and forced off).
  function syncKidFields() {
    const isKid = KID_ACCOUNT_TYPES.includes(typeSelect.value);

    if (childField) {
      childField.style.display = isKid ? "" : "none";
      const select = childField.querySelector("select");
      if (select) {
        select.disabled = !isKid;
        select.required = isKid;
      }
    }

    adultOnlyRows.forEach((row) => {
      row.classList.toggle("checkbox-row-disabled", isKid);
      const input = row.querySelector("input");
      if (input) input.disabled = isKid;
    });

    if (isKid) {
      if (withdrawalCheckbox) withdrawalCheckbox.checked = false;
      if (stopCheckbox) stopCheckbox.checked = false;
    }
  }

  // Only acts when the user actively changes the type during this visit — never
  // overrides an already-saved value just because the page loaded with type=PROPERTY,
  // so it won't silently flip a deliberate choice every time an existing account is opened.
  function suggestOnTypeChange() {
    syncContributionFields();
    syncKidFields();
    if (typeSelect.value === "PROPERTY" && withdrawalCheckbox) {
      withdrawalCheckbox.checked = false;
    }
  }

  typeSelect.addEventListener("change", suggestOnTypeChange);
  syncContributionFields(); // initial state — contribution-zeroing is a hard rule either way
  syncKidFields(); // initial state — must reflect saved type when editing an existing account
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-account-form]").forEach(setupAccountTypeToggle);
});
