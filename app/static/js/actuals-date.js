// Live "date → age" preview for the actuals form. Purely cosmetic: the server
// re-derives the age authoritatively on submit (see history.resolve_actual_age),
// using the same completed-years convention as models.calculate_age.
//
// DOB source is either static (data-dob on the date input) or dynamic — read
// from the currently-selected account option in a `select[data-dob-source]`,
// since an actual's age basis depends on whose account it is (yours vs a child's).
(function () {
  function ageOn(dobStr, dateStr) {
    if (!dobStr || !dateStr) return null;
    const dob = new Date(dobStr + "T00:00:00");
    const on = new Date(dateStr + "T00:00:00");
    if (isNaN(dob) || isNaN(on)) return null;
    let age = on.getFullYear() - dob.getFullYear();
    const beforeBirthday =
      on.getMonth() < dob.getMonth() ||
      (on.getMonth() === dob.getMonth() && on.getDate() < dob.getDate());
    if (beforeBirthday) age -= 1;
    return age;
  }

  document.querySelectorAll("[data-age-preview]").forEach(function (input) {
    const form = input.closest("form");
    const field = input.closest(".field") || input.parentElement;
    const out = field ? field.querySelector("[data-age-out]") : null;
    if (!out) return;

    const select = form ? form.querySelector("select[data-dob-source]") : null;

    function currentDob() {
      if (input.dataset.dob) return input.dataset.dob;
      if (select && select.selectedOptions.length) {
        return select.selectedOptions[0].dataset.dob || "";
      }
      return "";
    }

    function update() {
      if (!input.value) {
        out.textContent = "";
        return;
      }
      const age = ageOn(currentDob(), input.value);
      out.textContent = age === null ? "" : "→ age " + age;
    }

    input.addEventListener("change", update);
    input.addEventListener("input", update);
    if (select) select.addEventListener("change", update);
    update();
  });
})();
