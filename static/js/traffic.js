(function () {
  if (window.__rambleTrafficStarted) return;
  if (document.visibilityState === "prerender") return;
  window.__rambleTrafficStarted = true;

  var path = window.location.pathname || "/";
  var search = window.location.search || "";
  var referrer = document.referrer || "";
  var pageviewSent = false;
  var HEARTBEAT_MS = 30000;

  function payload(kind) {
    return JSON.stringify({
      path: path,
      search: search,
      referrer: referrer,
      kind: kind || "pageview",
    });
  }

  function send(kind) {
    var body = payload(kind);
    try {
      if (navigator.sendBeacon) {
        var ok = navigator.sendBeacon(
          "/api/traffic/",
          new Blob([body], { type: "application/json" })
        );
        if (ok) return;
      }
    } catch (err) {}
    try {
      fetch("/api/traffic/", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: body,
        keepalive: true,
      });
    } catch (err) {}
  }

  function sendPageview() {
    if (pageviewSent) return;
    pageviewSent = true;
    send("pageview");
  }

  function sendHeartbeat() {
    if (!pageviewSent) return;
    if (document.visibilityState === "hidden") return;
    send("heartbeat");
  }

  if (document.readyState === "complete") {
    sendPageview();
  } else {
    window.addEventListener("load", sendPageview, { once: true });
  }

  window.setInterval(sendHeartbeat, HEARTBEAT_MS);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") sendHeartbeat();
  });
})();
