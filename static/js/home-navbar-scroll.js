(function () {
  function updateNavbarBorder() {
    document.body.classList.toggle("is-navbar-scrolled", window.scrollY > 0);
  }
  updateNavbarBorder();
  window.addEventListener("scroll", updateNavbarBorder, { passive: true });
})();
