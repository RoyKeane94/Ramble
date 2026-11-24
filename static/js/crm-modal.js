(function () {
  var modal = document.getElementById("crm-contact-modal");
  if (modal) {
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
  }

  var moreModal = document.getElementById("crm-more-modal");
  if (!moreModal) return;

  var fields = {
    title: moreModal.querySelector("[data-crm-more-title]"),
    website: moreModal.querySelector("[data-crm-more-website]"),
    email: moreModal.querySelector("[data-crm-more-email]"),
    phone: moreModal.querySelector("[data-crm-more-phone]"),
    emailSource: moreModal.querySelector("[data-crm-more-email-source]"),
    source: moreModal.querySelector("[data-crm-more-source]"),
    personalisation: moreModal.querySelector("[data-crm-more-personalisation]"),
    response: moreModal.querySelector("[data-crm-more-response]"),
    reason: moreModal.querySelector("[data-crm-more-reason]"),
    slug: moreModal.querySelector("[data-crm-more-slug]"),
    url: moreModal.querySelector("[data-crm-more-url]"),
  };

  function dash(value) {
    value = (value || "").trim();
    return value || "—";
  }

  function setText(node, value) {
    if (!node) return;
    node.textContent = dash(value);
  }

  function setLink(node, value, hrefPrefix, openBlank) {
    if (!node) return;
    value = (value || "").trim();
    node.textContent = "";
    if (!value) {
      node.textContent = "—";
      return;
    }
    var link = document.createElement("a");
    link.className = "crm-link";
    link.href = hrefPrefix ? hrefPrefix + value : value;
    if (openBlank) {
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    }
    link.textContent = value;
    node.appendChild(link);
  }

  function openMore(button) {
    setText(fields.title, button.getAttribute("data-crm-more-title"));
    setLink(fields.website, button.getAttribute("data-crm-more-website"), "", true);
    setLink(fields.email, button.getAttribute("data-crm-more-email"), "mailto:");
    setLink(fields.phone, button.getAttribute("data-crm-more-phone"), "tel:");
    setText(fields.emailSource, button.getAttribute("data-crm-more-email-source"));
    setText(fields.source, button.getAttribute("data-crm-more-source"));
    setText(fields.personalisation, button.getAttribute("data-crm-more-personalisation"));
    setText(fields.response, button.getAttribute("data-crm-more-response"));
    setText(fields.reason, button.getAttribute("data-crm-more-reason"));
    setText(fields.slug, button.getAttribute("data-crm-more-slug"));
    setLink(fields.url, button.getAttribute("data-crm-more-url"), "", true);
    if (typeof moreModal.showModal === "function" && !moreModal.open) {
      moreModal.showModal();
    }
  }

  function closeMore() {
    if (typeof moreModal.close === "function" && moreModal.open) {
      moreModal.close();
    }
  }

  document.querySelectorAll("[data-crm-more-open]").forEach(function (button) {
    button.addEventListener("click", function () {
      openMore(button);
    });
  });

  moreModal.querySelectorAll("[data-crm-more-close]").forEach(function (button) {
    button.addEventListener("click", closeMore);
  });

  moreModal.addEventListener("click", function (event) {
    if (event.target === moreModal) closeMore();
  });
})();
