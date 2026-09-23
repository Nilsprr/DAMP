// Loaded synchronously in <head> so the saved theme applies before first paint.
(function () {
  var KEY = "damp-theme";
  var THEMES = ["data", "slop", "dark"];
  var saved = null;
  try {
    saved = localStorage.getItem(KEY);
  } catch (e) {}
  var root = document.documentElement;
  if (THEMES.indexOf(saved) !== -1) root.dataset.theme = saved;

  function sync() {
    document.querySelectorAll("[data-theme-choice]").forEach(function (btn) {
      btn.setAttribute("aria-pressed", String(btn.dataset.themeChoice === root.dataset.theme));
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    sync();
    document.querySelectorAll("[data-theme-choice]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        root.dataset.theme = btn.dataset.themeChoice;
        try {
          localStorage.setItem(KEY, root.dataset.theme);
        } catch (e) {}
        sync();
        document.dispatchEvent(new CustomEvent("damp:themechange"));
      });
    });
  });
})();
