// Live "date → age" preview for the actuals forms. Purely cosmetic: the server
// re-derives the age authoritatively on submit (see history.resolve_actual_age).
// Uses the same completed-years convention as models.calculate_age so what the
// user sees here matches what gets stored.
(function () {
  function ageOn(dobStr, dateStr) {
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
    const dob = input.dataset.dob;
    const field = input.closest(".field") || input.parentElement;
    const out = field ? field.querySelector("[data-age-out]") : null;
    if (!out) return;

    function update() {
      if (!input.value) {
        out.textContent = "";
        return;
      }
      const age = ageOn(dob, input.value);
      out.textContent = age === null ? "" : "→ age " + age;
    }

    input.addEventListener("change", update);
    input.addEventListener("input", update);
    update();
  });
})();
