(function () {
  const form = document.querySelector('form[action*="set_theme"]');
  if (!form) return;
  const combined = form.querySelector('#theme-combined');

  function updateCombined() {
    const base = form.querySelector('[name="base"]:checked');
    const accent = form.querySelector('[name="accent"]:checked');
    if (base && accent) combined.value = base.value + '-' + accent.value;
  }

  function updateSwatches() {
    const base = form.querySelector('[name="base"]:checked');
    if (!base) return;
    form.querySelectorAll('.accent-swatch').forEach(function (el) {
      el.style.background = base.value === 'dark' ? el.dataset.dark : el.dataset.light;
    });
  }

  form.querySelectorAll('[name="base"]').forEach(function (el) {
    el.addEventListener('change', function () {
      updateCombined();
      updateSwatches();
      form.submit();
    });
  });

  form.querySelectorAll('[name="accent"]').forEach(function (el) {
    el.addEventListener('change', function () {
      updateCombined();
      form.submit();
    });
  });
})();
