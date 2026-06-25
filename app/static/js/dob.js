function calculateAgeFromDob(dobStr) {
  const dob = new Date(dobStr + "T00:00:00");
  const today = new Date();
  let age = today.getFullYear() - dob.getFullYear();
  const hadBirthdayThisYear =
    today.getMonth() > dob.getMonth() ||
    (today.getMonth() === dob.getMonth() && today.getDate() >= dob.getDate());
  if (!hadBirthdayThisYear) age -= 1;
  return age;
}

function setupDobField() {
  const dobInput = document.getElementById("date_of_birth");
  const ageInput = document.getElementById("current_age");
  const agePreview = document.getElementById("age_preview");
  const fallbackHint = document.getElementById("age_fallback_hint");
  if (!dobInput || !ageInput) return;

  function sync() {
    if (dobInput.value) {
      const age = calculateAgeFromDob(dobInput.value);
      if (agePreview) agePreview.textContent = `(${age})`;
      ageInput.value = age;
      ageInput.disabled = true;
      if (fallbackHint) fallbackHint.textContent = "Calculated automatically from date of birth.";
    } else {
      if (agePreview) agePreview.textContent = "";
      ageInput.disabled = false;
      if (fallbackHint) fallbackHint.textContent = "Only used if date of birth is left blank.";
    }
  }

  dobInput.addEventListener("change", sync);
  sync();
}

document.addEventListener("DOMContentLoaded", setupDobField);
