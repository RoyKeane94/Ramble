(function () {
  var modal = document.getElementById("crm-contact-modal");
  if (!modal) return;

  var cancelUrl = modal.getAttribute("data-crm-cancel-url") || "";

  function openModal() {
    if (typeof modal.showModal === "function" && !modal.open) {
      modal.showModal();
    }
  }

  function closeModal() {
    if (cancelUrl) {
      window.location.href = cancelUrl;
      return;
    }
    if (typeof modal.close === "function" && modal.open) {
      modal.close();
    }
  }

  document.querySelectorAll("[data-crm-modal-open]").forEach(function (button) {
    button.addEventListener("click", openModal);
  });

  document.querySelectorAll("[data-crm-modal-close]").forEach(function (button) {
    button.addEventListener("click", closeModal);
  });

  modal.addEventListener("click", function (event) {
    if (event.target === modal) closeModal();
  });

  modal.addEventListener("cancel", function (event) {
    if (!cancelUrl) return;
    event.preventDefault();
    window.location.href = cancelUrl;
  });

  if (modal.getAttribute("data-crm-open") === "1") {
    openModal();
  }
})();
