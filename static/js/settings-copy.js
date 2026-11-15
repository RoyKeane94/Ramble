(function () {
  function copyText(text) {
    if (!text) return Promise.resolve(false);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(
        function () { return true; },
        function () { return copyTextFallback(text); }
      );
    }
    return Promise.resolve(copyTextFallback(text));
  }

  function copyTextFallback(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (err) {
      ok = false;
    }
    document.body.removeChild(area);
    return ok;
  }

  function markCopied(button) {
    var label = button.getAttribute("aria-label") || "Copy";
    button.classList.add("is-copied");
    button.setAttribute("aria-label", "Copied");
    window.setTimeout(function () {
      button.classList.remove("is-copied");
      button.setAttribute("aria-label", label);
    }, 1200);
  }

  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
      var node = document.querySelector(button.getAttribute("data-copy"));
      if (!node) return;
      var text = (node.textContent || "").trim();
      copyText(text).then(function (ok) {
        if (ok) markCopied(button);
      });
    });
  });
})();
