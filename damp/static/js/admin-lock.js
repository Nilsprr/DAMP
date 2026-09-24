// The padlock in the footer: open while this browser has an admin login, closed otherwise.
// The site is static and can't see the Cloudflare Access cookie, so the admin pages
// remember when the login expires (damp/static/admin/core.js) and this reads it.
(function () {
  var KEY = "damp-admin-until";

  function loggedIn() {
    try {
      return Number(localStorage.getItem(KEY) || 0) > Date.now();
    } catch (e) {
      return false;
    }
  }

  function sync() {
    var open = loggedIn();
    document.querySelectorAll("[data-admin-lock]").forEach(function (a) {
      a.classList.toggle("is-open", open);
      a.title = open ? "Admin (inloggad)" : "Admin (logga in)";
    });
  }

  document.addEventListener("DOMContentLoaded", sync);
  document.addEventListener("damp:adminlogin", sync);
  if (document.readyState !== "loading") sync();
})();
