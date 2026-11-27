(function () {
  var root = document.querySelector("[data-traffic-live]");
  if (!root) return;

  var countEl = root.querySelector("[data-live-count]");
  var labelEl = root.querySelector("[data-live-label]");
  var listEl = root.querySelector("[data-live-list]");
  var emptyEl = root.querySelector("[data-live-empty]");
  var POLL_MS = 15000;

  function render(data) {
    var count = data.count || 0;
    var viewers = data.viewers || [];
    if (countEl) countEl.textContent = String(count);
    if (labelEl) labelEl.textContent = data.label || "people viewing";
    root.classList.toggle("is-live", count > 0);

    if (!listEl) return;
    listEl.innerHTML = "";
    if (!viewers.length) {
      if (emptyEl) emptyEl.hidden = false;
      return;
    }
    if (emptyEl) emptyEl.hidden = true;
    viewers.forEach(function (row) {
      var li = document.createElement("li");
      li.className = "traffic-live-row";
      li.innerHTML =
        '<span class="traffic-live-path"></span>' +
        '<span class="traffic-live-meta"></span>';
      li.querySelector(".traffic-live-path").textContent = row.path || "/";
      li.querySelector(".traffic-live-meta").textContent =
        (row.ago_label || "") +
        (row.source ? " · " + row.source : "");
      listEl.appendChild(li);
    });
  }

  function poll() {
    fetch("/api/traffic/live/", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (res) {
        if (!res.ok) throw new Error("live fetch failed");
        return res.json();
      })
      .then(render)
      .catch(function () {});
  }

  poll();
  window.setInterval(poll, POLL_MS);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") poll();
  });
})();
