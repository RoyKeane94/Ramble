(function () {
  var params = new URLSearchParams(window.location.search);
  var slug = (params.get("ref") || "").trim();
  if (!slug) return;

  var CONFIRM_MS = 3000;
  var confirmed = false;
  var visibleStartedAt = null;
  var visibleMs = 0;
  var timer = null;
  var startPromise = null;
  var base = "/t/" + encodeURIComponent(slug) + "/open/";

  function post(path) {
    return fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      keepalive: true,
    }).then(function (res) {
      return res.json().catch(function () {
        return {};
      }).then(function (data) {
        data = data || {};
        data._httpStatus = res.status;
        if (res.status === 204) {
          data.status = data.status || "ignored";
        }
        return data;
      });
    });
  }

  function ensureStarted() {
    if (!startPromise) {
      startPromise = post(base + "start/")
        .then(function (data) {
          if (data.status === "ignored") {
            startPromise = null;
            return false;
          }
          if (data.status === "opened") {
            confirmed = true;
            clearTimer();
            return true;
          }
          return true;
        })
        .catch(function () {
          startPromise = null;
          return false;
        });
    }
    return startPromise;
  }

  function clearTimer() {
    if (timer) {
      window.clearTimeout(timer);
      timer = null;
    }
  }

  function accumulatedVisibleMs() {
    var total = visibleMs;
    if (visibleStartedAt != null) {
      total += Date.now() - visibleStartedAt;
    }
    return total;
  }

  function scheduleConfirm(delay) {
    if (confirmed) return;
    clearTimer();
    timer = window.setTimeout(tryConfirm, Math.max(0, delay));
  }

  function tryConfirm() {
    if (confirmed) return;
    ensureStarted().then(function (ok) {
      if (!ok || confirmed) return;
      var remaining = CONFIRM_MS - accumulatedVisibleMs();
      if (remaining > 0) {
        scheduleConfirm(remaining);
        return;
      }
      post(base + "confirm/")
        .then(function (data) {
          if (data.status === "opened" || data.status === "ignored") {
            confirmed = true;
            clearTimer();
            return;
          }
          if (data.status === "too_soon" || data._httpStatus === 409) {
            scheduleConfirm(
              typeof data.retry_after_ms === "number" ? data.retry_after_ms : 1000
            );
            return;
          }
          scheduleConfirm(1500);
        })
        .catch(function () {
          scheduleConfirm(1500);
        });
    });
  }

  function onHidden() {
    if (visibleStartedAt == null) return;
    visibleMs += Date.now() - visibleStartedAt;
    visibleStartedAt = null;
    clearTimer();
  }

  function onVisible() {
    if (confirmed) return;
    visibleStartedAt = Date.now();
    ensureStarted().then(function (ok) {
      if (!ok || confirmed) return;
      scheduleConfirm(Math.max(0, CONFIRM_MS - visibleMs));
    });
  }

  function syncVisibility() {
    if (document.visibilityState === "hidden") {
      onHidden();
    } else {
      onVisible();
    }
  }

  document.addEventListener("visibilitychange", syncVisibility);
  window.addEventListener("pagehide", onHidden);
  syncVisibility();
})();
