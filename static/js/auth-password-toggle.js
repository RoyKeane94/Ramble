document.querySelectorAll("[data-password-toggle]").forEach(function (btn) {
  var field = btn.closest(".auth-field");
  var input = field && field.querySelector('input[type="password"], input[type="text"]');

  function syncToggle() {
    var visible = input && input.type === "text";
    btn.classList.toggle("is-visible", visible);
    btn.setAttribute("aria-label", visible ? "Hide password" : "Show password");
  }

  syncToggle();
  btn.addEventListener("click", function () {
    if (!input) return;
    input.type = input.type === "password" ? "text" : "password";
    syncToggle();
  });
});
