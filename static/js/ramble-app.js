(function () {
  var MOBILE_QUERY = "(max-width: 800px)";
  var DB_NAME = "ramble-offline";
  var DB_VERSION = 1;
  var TAKE_STORE = "pendingTakes";
  var LIVE_STORE = "liveRecording";

  var config = readConfig();
  if (!config) return;

  var TAKE_MAX_SECONDS = 300;
  if (Number(config.takeMaxSeconds) > 0) {
    TAKE_MAX_SECONDS = Math.min(TAKE_MAX_SECONDS, Number(config.takeMaxSeconds));
  }
  var media = window.matchMedia(MOBILE_QUERY);
  var state = {
    db: null,
    recorder: null,
    stream: null,
    chunks: [],
    mimeType: "",
    startedAt: 0,
    elapsed: 0,
    timer: null,
    recording: false,
    uploading: false,
    rollNavLoading: false,
    takeLimit: TAKE_MAX_SECONDS,
  };

  var rollNavCache = new Map();

  function readConfig() {
    var node = document.getElementById("ramble-app-config");
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (err) {
      return null;
    }
  }

  function isAppPage() {
    return document.body.classList.contains("is-signed-in")
      && !document.body.classList.contains("is-landing-page")
      && !document.body.classList.contains("is-auth-page");
  }

  function isMobile() {
    return media.matches;
  }

  function eventElement(event) {
    var node = event && event.target;
    if (!node) return null;
    if (node.nodeType === 3) node = node.parentElement;
    if (!node || typeof node.closest !== "function") return null;
    return node;
  }

  function recordingAllowed() {
    return isMobile() && document.body.dataset.appShutter !== "off";
  }

  function resetRecordingUi() {
    state.recording = false;
    if (state.timer) {
      clearInterval(state.timer);
      state.timer = null;
    }
    if (state.recorder && state.recorder.state !== "inactive") {
      try {
        state.recorder.stop();
      } catch (err) {}
    }
    state.recorder = null;
    stopTracks();
    document.body.classList.remove("is-recording");
    document.body.removeAttribute("hidden");
    var screen = document.querySelector("[data-app-record-screen]");
    if (screen) {
      screen.hidden = true;
      screen.setAttribute("aria-hidden", "true");
    }
    var button = document.querySelector("[data-app-record]");
    if (button) {
      button.classList.remove("is-recording");
      button.setAttribute("aria-label", "Start recording");
    }
    var stop = document.querySelector(".app-record-stop");
    if (stop) stop.hidden = true;
  }

  function applyShell() {
    var on = isAppPage() && isMobile();
    document.body.classList.toggle("is-app", on);
    if (!recordingAllowed()) {
      resetRecordingUi();
    }
    var shutter = document.querySelector(".app-shutter");
    if (shutter) {
      var show = on && recordingAllowed();
      shutter.hidden = !show;
    }
    var screen = document.querySelector("[data-app-record-screen]");
    if (screen && !state.recording) {
      screen.hidden = true;
      screen.setAttribute("aria-hidden", "true");
    }
    if (on) {
      document.documentElement.style.setProperty("--app-bottom-clearance", "148px");
    } else {
      document.documentElement.style.removeProperty("--app-bottom-clearance");
    }
  }

  function csrfToken() {
    if (config.csrfToken) return config.csrfToken;
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function formatDuration(seconds) {
    var total = Math.max(0, Math.floor(seconds));
    var minutes = Math.floor(total / 60);
    var rest = total % 60;
    return minutes + ":" + String(rest).padStart(2, "0");
  }

  function uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function openDb() {
    return new Promise(function (resolve, reject) {
      if (state.db) {
        resolve(state.db);
        return;
      }
      if (!window.indexedDB) {
        reject(new Error("IndexedDB is not available."));
        return;
      }
      var request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = function () {
        var db = request.result;
        if (!db.objectStoreNames.contains(TAKE_STORE)) {
          db.createObjectStore(TAKE_STORE, { keyPath: "id" });
        }
        if (!db.objectStoreNames.contains(LIVE_STORE)) {
          db.createObjectStore(LIVE_STORE, { keyPath: "id" });
        }
      };
      request.onsuccess = function () {
        state.db = request.result;
        resolve(state.db);
      };
      request.onerror = function () {
        reject(request.error);
      };
    });
  }

  function withStore(name, mode, fn) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(name, mode);
        var store = tx.objectStore(name);
        var result = fn(store);
        tx.oncomplete = function () {
          resolve(result);
        };
        tx.onerror = function () {
          reject(tx.error);
        };
      });
    });
  }

  function putTake(take) {
    return withStore(TAKE_STORE, "readwrite", function (store) {
      store.put(take);
    });
  }

  function deleteTake(id) {
    return withStore(TAKE_STORE, "readwrite", function (store) {
      store.delete(id);
    });
  }

  function allTakes() {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(TAKE_STORE, "readonly");
        var request = tx.objectStore(TAKE_STORE).getAll();
        request.onsuccess = function () {
          resolve(request.result || []);
        };
        request.onerror = function () {
          reject(request.error);
        };
      });
    });
  }

  function saveLive(chunks, mimeType, startedAt) {
    return withStore(LIVE_STORE, "readwrite", function (store) {
      store.put({
        id: "current",
        chunks: chunks,
        mimeType: mimeType,
        startedAt: startedAt,
      });
    });
  }

  function clearLive() {
    return withStore(LIVE_STORE, "readwrite", function (store) {
      store.delete("current");
    });
  }

  function loadLive() {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(LIVE_STORE, "readonly");
        var request = tx.objectStore(LIVE_STORE).get("current");
        request.onsuccess = function () {
          resolve(request.result || null);
        };
        request.onerror = function () {
          reject(request.error);
        };
      });
    });
  }

  function pickMimeType() {
    var types = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/mp4",
      "audio/mpeg",
    ];
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return "";
    for (var i = 0; i < types.length; i += 1) {
      if (MediaRecorder.isTypeSupported(types[i])) return types[i];
    }
    return "";
  }

  function takeLimitSeconds() {
    var allowance = Math.max(0, Number(config.remainingSeconds || 0));
    if (allowance < 1) return 0;
    return Math.min(TAKE_MAX_SECONDS, allowance);
  }

  function updateRecordLimitLabel() {
    var limit = document.querySelector("[data-app-limit]");
    if (!limit) return;
    var seconds = state.recording ? state.takeLimit : takeLimitSeconds();
    if (seconds < 1 && !config.isExhausted) seconds = TAKE_MAX_SECONDS;
    limit.textContent = "/ " + formatDuration(seconds);
  }

  function remainingSeconds() {
    return Math.max(0, state.takeLimit - Math.floor(state.elapsed));
  }

  function updateAllowanceHint() {
    var hint = document.querySelector("[data-app-allowance]");
    if (!hint) return;
    if (config.isExhausted) {
      hint.textContent = config.remainingCopy || "0 minutes left this month";
    } else {
      hint.textContent = "";
    }
  }

  function setRecordingChrome(on) {
    if (!recordingAllowed()) {
      on = false;
    }
    document.body.classList.toggle("is-recording", on);
    var button = document.querySelector("[data-app-record]");
    var stop = document.querySelector(".app-record-stop");
    var screen = document.querySelector("[data-app-record-screen]");
    if (button) {
      button.setAttribute("aria-label", on ? "Stop recording" : "Start recording");
      button.classList.toggle("is-recording", on);
      button.disabled = !on && !!config.isExhausted;
    }
    if (stop) stop.hidden = !on;
    if (screen) {
      screen.hidden = !on;
      screen.setAttribute("aria-hidden", on ? "false" : "true");
    }
    if (on) {
      state.takeLimit = Math.min(TAKE_MAX_SECONDS, state.takeLimit || takeLimitSeconds());
    }
    updateRecordLimitLabel();
  }

  function tickTimer() {
    state.elapsed = (Date.now() - state.startedAt) / 1000;
    var elapsedNode = document.querySelector("[data-app-elapsed]");
    if (elapsedNode) elapsedNode.textContent = formatDuration(state.elapsed);
    state.takeLimit = Math.min(TAKE_MAX_SECONDS, state.takeLimit || takeLimitSeconds());
    updateRecordLimitLabel();
    var limit = state.takeLimit;
    var left = limit - state.elapsed;
    if (elapsedNode) {
      elapsedNode.classList.toggle("is-late", limit > 0 && left <= 30);
    }
    if (limit > 0 && state.elapsed >= limit) {
      finishRecording();
    }
  }

  function preferredAudioConstraints() {
    return {
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    };
  }

  async function beginRecording() {
    if (!recordingAllowed()) return;
    if (state.recording) {
      finishRecording();
      return;
    }
    if (config.isExhausted) {
      showError(config.remainingCopy || "0 minutes left this month");
      return;
    }
    state.takeLimit = Math.min(TAKE_MAX_SECONDS, takeLimitSeconds());
    if (state.takeLimit < 1) {
      showError(config.remainingCopy || "0 minutes left this month");
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showError("Recording is not supported in this browser.");
      return;
    }

    try {
      state.stream = await navigator.mediaDevices.getUserMedia(preferredAudioConstraints());
    } catch (err) {
      showError("Microphone access is needed to record.");
      return;
    }
    var audioTrack = state.stream.getAudioTracks()[0];
    if (!audioTrack || audioTrack.readyState !== "live") {
      stopTracks();
      showError("Microphone access is needed to record.");
      return;
    }
    audioTrack.enabled = true;

    state.chunks = [];
    state.mimeType = pickMimeType();
    state.startedAt = Date.now();
    state.elapsed = 0;
    var options = state.mimeType ? { mimeType: state.mimeType } : undefined;
    try {
      state.recorder = new MediaRecorder(state.stream, options);
    } catch (err) {
      state.recorder = new MediaRecorder(state.stream);
    }
    state.mimeType = state.recorder.mimeType || state.mimeType || "audio/webm";

    state.recorder.addEventListener("dataavailable", function (event) {
      if (!event.data || !event.data.size) return;
      state.chunks.push(event.data);
      saveLive(state.chunks.slice(), state.mimeType, state.startedAt).catch(function () {});
    });
    state.recorder.addEventListener("error", function () {
      showError("Recording failed.");
      cancelRecording();
    });

    state.recording = true;
    setRecordingChrome(true);
    tickTimer();
    state.timer = setInterval(tickTimer, 250);
    state.recorder.start(1000);
  }

  function stopTracks() {
    if (!state.stream) return;
    state.stream.getTracks().forEach(function (track) {
      track.stop();
    });
    state.stream = null;
  }

  function cancelRecording() {
    state.recording = false;
    if (state.timer) {
      clearInterval(state.timer);
      state.timer = null;
    }
    if (state.recorder && state.recorder.state !== "inactive") {
      try {
        state.recorder.stop();
      } catch (err) {}
    }
    state.recorder = null;
    stopTracks();
    setRecordingChrome(false);
    clearLive().catch(function () {});
  }

  async function finishRecording() {
    if (!state.recording || !state.recorder) {
      cancelRecording();
      return;
    }

    var recorder = state.recorder;
    var duration = Math.max(1, Math.round((Date.now() - state.startedAt) / 1000));
    var mimeType = state.mimeType;

    var stopped = new Promise(function (resolve) {
      recorder.addEventListener("stop", resolve, { once: true });
    });
    try {
      recorder.stop();
    } catch (err) {
      cancelRecording();
      return;
    }
    await stopped;
    stopTracks();
    if (state.timer) {
      clearInterval(state.timer);
      state.timer = null;
    }
    state.recording = false;
    state.recorder = null;
    setRecordingChrome(false);

    var blob = new Blob(state.chunks, { type: mimeType || "audio/webm" });
    state.chunks = [];
    await clearLive().catch(function () {});
    if (!blob.size) {
      showError("Nothing was recorded.");
      return;
    }

    var take = {
      id: uuid(),
      createdAt: new Date().toISOString(),
      duration: duration,
      mimeType: blob.type || mimeType,
      blob: blob,
      status: "pending",
      error: "",
      attempts: 0,
    };
    await putTake(take);
    insertOptimisticRow(take);
    updateSyncBanner();
    flushQueue();
  }

  function showError(message) {
    window.alert(message);
  }

  function insertOptimisticRow(take) {
    var list = document.querySelector(".roll-list .frames") || ensureTodayList();
    if (!list) return;
    var empty = document.querySelector(".roll-list-empty, .empty-copy");
    if (empty && empty.closest(".roll-list-empty")) {
      empty.closest(".roll-list-empty").hidden = true;
    }
    var existing = document.querySelector('[data-pending-id="' + take.id + '"]');
    if (existing) return;
    var li = document.createElement("li");
    li.className = "frame-row is-pending";
    li.setAttribute("data-pending-id", take.id);
    li.innerHTML =
      '<div class="frame-swipe">' +
      '<div class="frame-swipe-actions"><button type="button" class="frame-swipe-delete" tabindex="-1">Delete</button></div>' +
      '<div class="frame-swipe-content">' +
      '<div class="frame is-developing">' +
      '<div class="frame-copy"><p class="frame-preview">Developing…</p></div>' +
      '<div class="frame-side"><p class="frame-meta"><span class="frame-meta-text">' +
      formatTime(take.createdAt) +
      (take.duration ? " · " + formatDuration(take.duration) : "") +
      "</span></p></div></div></div></div>";
    list.insertBefore(li, list.firstChild);
  }

  function formatTime(value) {
    var date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function ensureTodayList() {
    var roll = document.querySelector(".roll-list");
    if (!roll) {
      var shell = document.querySelector(".shell-roll");
      if (!shell) return null;
      roll = document.createElement("div");
      roll.className = "roll-list";
      roll.innerHTML = '<section class="day"><div class="day-head"><h2 class="day-label">Today</h2></div><ul class="frames"></ul></section>';
      shell.appendChild(roll);
      return roll.querySelector(".frames");
    }
    var frames = roll.querySelector(".frames");
    if (frames) return frames;
    var section = document.createElement("section");
    section.className = "day";
    section.innerHTML = '<div class="day-head"><h2 class="day-label">Today</h2></div><ul class="frames"></ul>';
    roll.insertBefore(section, roll.firstChild);
    return section.querySelector(".frames");
  }

  function updatePendingRow(take) {
    var row = document.querySelector('[data-pending-id="' + take.id + '"]');
    if (!row) return;
    var preview = row.querySelector(".frame-preview");
    if (preview) preview.textContent = "Developing…";
  }

  async function updateSyncBanner() {
    var banner = document.querySelector("[data-app-sync]");
    if (!banner) return;
    var pending = [];
    try {
      pending = await allTakes();
    } catch (err) {
      banner.hidden = true;
      return;
    }
    var offline = !navigator.onLine;
    var failed = pending.some(function (take) {
      return !!take.error;
    });
    if (!document.body.classList.contains("is-app") || !pending.length || (!offline && !failed)) {
      banner.hidden = true;
      return;
    }
    var title = document.querySelector("[data-app-sync-title]");
    var detail = document.querySelector("[data-app-sync-detail]");
    if (title) title.textContent = "Waiting for better signal";
    if (detail) {
      detail.textContent = pending.length === 1
        ? "1 take waiting to upload"
        : pending.length + " takes waiting to upload";
    }
    banner.hidden = false;
  }

  async function flushQueue() {
    if (state.uploading) return;
    if (!navigator.onLine) {
      var offlineTakes = await allTakes().catch(function () { return []; });
      offlineTakes.forEach(function (take) {
        updatePendingRow(take);
      });
      updateSyncBanner();
      return;
    }

    var takes = await allTakes().catch(function () { return []; });
    if (!takes.length) {
      updateSyncBanner();
      return;
    }

    state.uploading = true;
    for (var i = 0; i < takes.length; i += 1) {
      await uploadTake(takes[i]);
    }
    state.uploading = false;
    updateSyncBanner();
  }

  async function uploadTake(take) {
    take.status = "uploading";
    take.attempts = (take.attempts || 0) + 1;
    await putTake(take);
    updatePendingRow(take);
    updateSyncBanner();

    var body = new FormData();
    var filename = "ramble." + (extensionFor(take.mimeType) || "webm");
    body.append("audio", take.blob, filename);
    body.append("duration", String(take.duration || 0));
    body.append("id", take.id);
    body.append("created_at", take.createdAt);

    try {
      var response = await fetch(config.developUrl, {
        method: "POST",
        body: body,
        credentials: "same-origin",
        headers: {
          "X-CSRFToken": csrfToken(),
        },
      });
      var payload = {};
      try {
        payload = await response.json();
      } catch (err) {
        payload = {};
      }
      if (!response.ok) {
        if (response.status === 402) {
          config.isExhausted = true;
          updateAllowanceHint();
        }
        throw new Error(payload.detail || "Could not develop that take.");
      }
      await deleteTake(take.id);
      replacePendingRow(take.id, payload);
      if (payload.duration) {
        config.remainingSeconds = Math.max(0, Number(config.remainingSeconds || 0) - Number(payload.duration));
        if (config.remainingSeconds < 1) config.isExhausted = true;
        updateAllowanceHint();
      }
    } catch (err) {
      take.status = "pending";
      take.error = err.message || "Waiting for better signal";
      await putTake(take);
      updatePendingRow(take);
    }
  }

  function extensionFor(mime) {
    if (!mime) return "webm";
    if (mime.indexOf("mp4") !== -1) return "m4a";
    if (mime.indexOf("mpeg") !== -1 || mime.indexOf("mp3") !== -1) return "mp3";
    if (mime.indexOf("wav") !== -1) return "wav";
    return "webm";
  }

  function replacePendingRow(id, note) {
    var row = document.querySelector('[data-pending-id="' + id + '"]');
    if (!row) {
      if (document.body.dataset.appPage === "roll") {
        window.location.reload();
      }
      return;
    }
    if (!note || !note.id) {
      row.remove();
      return;
    }
    if (document.body.dataset.appPage === "roll") {
      window.location.reload();
      return;
    }
    row.remove();
  }

  function bindShutter() {
    if (bindShutter.done) return;
    bindShutter.done = true;
    document.addEventListener("click", function (event) {
      var el = eventElement(event);
      if (!el || !el.closest("[data-app-record]")) return;
      beginRecording();
    });
    var button = document.querySelector("[data-app-record]");
    if (button) button.disabled = !!config.isExhausted;
    updateAllowanceHint();
  }

  function onRollShellPage() {
    var page = document.body.dataset.appPage;
    return page === "roll" || page === "albums";
  }

  function appShellNavEnabled() {
    if (!isAppPage() || !isMobile() || state.recording) return false;
    var page = document.body.dataset.appPage;
    return page === "roll" || page === "albums" || page === "take";
  }

  function isTakeNavHref(href) {
    try {
      var u = new URL(href, window.location.origin);
      if (u.origin !== window.location.origin) return false;
      return /^\/notes\/[0-9a-f-]{36}\/?$/i.test(u.pathname);
    } catch (err) {
      return false;
    }
  }

  function isAppShellNavHref(href) {
    return isPrimaryRollNavHref(href) || isTakeNavHref(href);
  }

  function isPrimaryRollNavHref(href) {
    try {
      var u = new URL(href, window.location.origin);
      if (u.origin !== window.location.origin) return false;
      var path = u.pathname.replace(/\/+$/, "");
      if (path.endsWith("/roll")) {
        if (u.searchParams.has("q")) return false;
        var album = u.searchParams.get("album");
        if (!album || album === "recents" || album === "today" || album === "starred") {
          return true;
        }
        return false;
      }
      if (path.endsWith("/albums") && path.indexOf("/albums/new") === -1) {
        return !u.search;
      }
      return false;
    } catch (err) {
      return false;
    }
  }

  function rollNavUrlKey(href) {
    var u = new URL(href, window.location.origin);
    u.hash = "";
    return u.pathname + u.search;
  }

  function syncAppBarFrom(doc) {
    var pairs = [
      [".app-bar-leading", "innerHTML"],
      [".app-bar-title", "textContent"],
      [".app-bar-trailing", "innerHTML"],
    ];
    pairs.forEach(function (pair) {
      var from = doc.querySelector(pair[0]);
      var to = document.querySelector(pair[0]);
      if (from && to) {
        to[pair[1]] = from[pair[1]];
      }
    });
  }

  function syncNavbarChrome(doc) {
    syncAppBarFrom(doc);
    var navbar = document.querySelector(".navbar");
    if (!navbar) return;
    var existing = navbar.querySelector(".app-filters");
    if (existing) existing.remove();
    var incoming = doc.querySelector(".navbar .app-filters");
    if (incoming) navbar.appendChild(incoming.cloneNode(true));
  }

  function syncBodyShellFrom(doc) {
    if (!doc.body) return;
    if (doc.body.dataset.appPage) {
      document.body.dataset.appPage = doc.body.dataset.appPage;
    }
    if (doc.body.dataset.appShutter) {
      document.body.dataset.appShutter = doc.body.dataset.appShutter;
    } else {
      document.body.removeAttribute("data-app-shutter");
    }
  }

  function setRollFilterActive(filterId) {
    document.querySelectorAll("[data-app-roll-nav] .app-filter[data-roll-filter]").forEach(function (el) {
      el.classList.toggle("is-on", el.getAttribute("data-roll-filter") === filterId);
    });
  }

  function rollFilterIdFromUrl(url) {
    try {
      var u = new URL(url, window.location.origin);
      var path = u.pathname.replace(/\/+$/, "");
      if (path.endsWith("/albums")) return "albums";
      var album = u.searchParams.get("album");
      if (album === "today") return "today";
      if (album === "starred") return "starred";
      return "recents";
    } catch (err) {
      return "recents";
    }
  }

  function prefetchAppShellPage(url) {
    if (!isAppShellNavHref(url)) return;
    var key = rollNavUrlKey(url);
    if (rollNavCache.has(key) || rollNavCache.has(key + ":pending")) return;
    rollNavCache.set(key + ":pending", true);
    fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "text/html" },
    })
      .then(function (response) {
        return response.ok ? response.text() : null;
      })
      .then(function (html) {
        rollNavCache.delete(key + ":pending");
        if (html) rollNavCache.set(key, html);
      })
      .catch(function () {
        rollNavCache.delete(key + ":pending");
      });
  }

  function prefetchRollNavNeighbors() {
    if (!config) return;
    [config.listUrl, config.todayUrl, config.albumsPageUrl, config.starredUrl].forEach(function (url) {
      if (url) prefetchAppShellPage(url);
    });
  }

  function prefetchVisibleTakes() {
    if (!onRollShellPage()) return;
    var links = document.querySelectorAll(".frame-link[href]");
    for (var i = 0; i < links.length && i < 10; i++) {
      prefetchAppShellPage(links[i].href);
    }
  }

  function bindTakeTextareas() {
    document.querySelectorAll(".take-text-edit").forEach(function (textarea) {
      if (textarea.dataset.resizeBound === "1") return;
      textarea.dataset.resizeBound = "1";
      var resize = function () {
        textarea.style.height = "auto";
        textarea.style.height = textarea.scrollHeight + "px";
      };
      resize();
      textarea.addEventListener("input", resize);
    });
  }

  function takeIconHtml(kind) {
    var node = document.getElementById("take-icon-" + kind);
    return node ? node.innerHTML.trim() : "";
  }

  function prefetchTakeToolbarLinks() {
    if (document.body.dataset.appPage !== "take") return;
    var path = window.location.pathname;
    prefetchAppShellPage(path);
    prefetchAppShellPage(path + "?albums=1");
    prefetchAppShellPage(path + "?edit=1");
    document.querySelectorAll("[data-take-toolbar] a.app-icon-btn[href]").forEach(function (link) {
      prefetchAppShellPage(link.href);
    });
    var done = document.querySelector(".take-albums-done[href]");
    if (done) prefetchAppShellPage(done.href);
  }

  function setTakeStarButton(button, starred) {
    if (!button) return;
    var html = starred ? takeIconHtml("star-fill") : takeIconHtml("star");
    if (html) button.innerHTML = html;
    button.classList.toggle("is-active", starred);
    button.setAttribute("aria-label", starred ? "Unstar" : "Star");
  }

  function bindTakeToolbar() {
    if (bindTakeToolbar.done) return;
    bindTakeToolbar.done = true;

    document.addEventListener(
      "touchstart",
      function (event) {
        var el = eventElement(event);
        var btn = el && el.closest("[data-take-toolbar] .app-icon-btn");
        if (!btn || btn.disabled) return;
        btn.classList.add("is-tapped");
      },
      { passive: true, capture: true }
    );

    document.addEventListener(
      "touchend",
      function (event) {
        var el = eventElement(event);
        var btn = el && el.closest("[data-take-toolbar] .app-icon-btn");
        if (btn) btn.classList.remove("is-tapped");
      },
      { passive: true, capture: true }
    );

    document.addEventListener("click", function (event) {
      var el = eventElement(event);
      var starBtn = el && el.closest("[data-take-star]");
      if (!starBtn || !appShellNavEnabled()) return;
      var form = starBtn.closest("form");
      if (!form) return;
      event.preventDefault();

      var starred = !starBtn.classList.contains("is-active");
      setTakeStarButton(starBtn, starred);

      var body = new URLSearchParams();
      body.set("csrfmiddlewaretoken", csrfToken());
      fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-CSRFToken": csrfToken(),
          "X-Ramble-App": "1",
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: body.toString(),
      })
        .then(function (response) {
          if (!response.ok) throw new Error("star failed");
          return response.json();
        })
        .then(function (payload) {
          setTakeStarButton(starBtn, !!payload.is_starred);
        })
        .catch(function () {
          setTakeStarButton(starBtn, !starred);
        });
    });
  }

  function afterAppShellSwap() {
    bindTakeTextareas();
    applyShell();
    if (onRollShellPage()) {
      prefetchRollNavNeighbors();
      prefetchVisibleTakes();
    }
    prefetchTakeToolbarLinks();
  }

  function applyRollHtml(html, url, pushHistory, instant) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var nextMain = doc.querySelector("main");
    var main = document.querySelector("main");
    if (!nextMain || !main) {
      window.location.href = url;
      return;
    }
    main.innerHTML = nextMain.innerHTML;
    syncNavbarChrome(doc);
    syncBodyShellFrom(doc);
    if (isPrimaryRollNavHref(url)) {
      setRollFilterActive(rollFilterIdFromUrl(url));
    }
    var title = doc.querySelector("title");
    if (title) document.title = title.textContent;
    if (pushHistory) {
      history.pushState({ rambleAppNav: rollNavUrlKey(url) }, "", url);
    }
    main.classList.remove("is-roll-nav-loading");
    main.classList.add("is-roll-nav-enter");
    if (instant) main.classList.add("is-roll-nav-enter-instant");
    window.setTimeout(function () {
      main.classList.remove("is-roll-nav-enter", "is-roll-nav-enter-instant");
    }, instant ? 160 : 220);
    main.scrollTop = 0;
    window.scrollTo(0, 0);
    afterAppShellSwap();
    rollNavCache.set(rollNavUrlKey(url), html);
  }

  async function fetchRollHtml(url) {
    var key = rollNavUrlKey(url);
    var cached = rollNavCache.get(key);
    if (cached) return cached;
    var response = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "text/html" },
    });
    if (!response.ok) return null;
    var html = await response.text();
    rollNavCache.set(key, html);
    return html;
  }

  async function navigateRoll(url, pushHistory, filterId) {
    if (state.rollNavLoading) return;
    if (rollNavUrlKey(url) === rollNavUrlKey(window.location.href) && pushHistory) {
      return;
    }
    if (filterId) setRollFilterActive(filterId);

    var cached = rollNavCache.get(rollNavUrlKey(url));
    if (cached) {
      applyRollHtml(cached, url, pushHistory, true);
      return;
    }

    state.rollNavLoading = true;
    var main = document.querySelector("main");
    if (main) main.classList.add("is-roll-nav-loading");
    try {
      var html = await fetchRollHtml(url);
      if (!html) {
        window.location.href = url;
        return;
      }
      applyRollHtml(html, url, pushHistory, false);
    } catch (err) {
      window.location.href = url;
    } finally {
      state.rollNavLoading = false;
      if (main) main.classList.remove("is-roll-nav-loading");
    }
  }

  function appShellNavLinkFromEvent(event) {
    var el = eventElement(event);
    if (!el) return null;
    var filter = el.closest("[data-app-roll-nav] .app-filter[href]");
    if (filter) return filter;
    var album = el.closest(".albums-grid--library .album-entry[href]");
    if (album) return album;
    var frame = el.closest(".frame-link[href]");
    if (frame) return frame;
    var back = el.closest(".app-bar-leading a.app-icon-btn[href]");
    if (back) return back;
    var tool = el.closest("[data-take-toolbar] a.app-icon-btn[href]");
    if (tool) return tool;
    var done = el.closest(".take-albums-done[href]");
    if (done) return done;
    return null;
  }

  function prefetchLinkFromEvent(event) {
    var link = appShellNavLinkFromEvent(event);
    if (!link || !appShellNavEnabled()) return;
    if (!isAppShellNavHref(link.href)) return;
    prefetchAppShellPage(link.href);
  }

  function bindRollNav() {
    if (bindRollNav.done) return;
    bindRollNav.done = true;

    document.addEventListener("click", function (event) {
      if (event.defaultPrevented) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (event.button !== 0) return;
      var link = appShellNavLinkFromEvent(event);
      if (!link) return;
      if (!appShellNavEnabled()) return;
      if (!isAppShellNavHref(link.href)) return;
      if (rollNavUrlKey(link.href) === rollNavUrlKey(window.location.href)) {
        event.preventDefault();
        return;
      }
      event.preventDefault();
      var row = link.closest(".frame-row");
      if (row) {
        if (row.classList.contains("is-swipe-open")) {
          closeOpenFrameSwipes();
          return;
        }
        if (row.dataset.swipeSuppressClick === "1") {
          delete row.dataset.swipeSuppressClick;
          return;
        }
        row.classList.add("is-opening");
        window.setTimeout(function () {
          row.classList.remove("is-opening");
        }, 280);
      }
      var toolBtn = link.closest("[data-take-toolbar]");
      if (toolBtn) {
        link.classList.add("is-tapped");
        window.setTimeout(function () {
          link.classList.remove("is-tapped");
        }, 160);
      }
      var filterId = link.getAttribute("data-roll-filter") || rollFilterIdFromUrl(link.href);
      navigateRoll(link.href, true, filterId);
    });

    document.addEventListener("pointerenter", prefetchLinkFromEvent, true);

    document.addEventListener("touchstart", prefetchLinkFromEvent, { passive: true, capture: true });

    window.addEventListener("popstate", function () {
      if (!appShellNavEnabled()) return;
      if (!isAppShellNavHref(window.location.href)) return;
      navigateRoll(window.location.href, false, rollFilterIdFromUrl(window.location.href));
    });
  }

  var SWIPE_DELETE_WIDTH = 88;
  var SWIPE_OPEN_THRESHOLD = 44;
  var SWIPE_FULL_DELETE = 112;
  var frameSwipeDrag = null;

  function frameSwipeEnabled() {
    return isAppPage() && isMobile() && document.body.classList.contains("is-app");
  }

  function closeOpenFrameSwipes(except) {
    document.querySelectorAll(".frame-row.is-swipe-open, .frame-row.is-swipe-dragging").forEach(function (row) {
      if (except && row === except) return;
      setFrameSwipeOffset(row, 0);
      row.classList.remove("is-swipe-open", "is-swipe-dragging");
      setFrameSwipeDeleteFocus(row, false);
    });
  }

  function setFrameSwipeDeleteFocus(row, enabled) {
    var btn = row && row.querySelector(".frame-swipe-delete");
    if (!btn) return;
    if (enabled) {
      btn.removeAttribute("tabindex");
    } else {
      btn.setAttribute("tabindex", "-1");
    }
  }

  function setFrameSwipeOffset(row, offset) {
    var content = row.querySelector(".frame-swipe-content");
    if (!content) return;
    var x = Math.max(-SWIPE_DELETE_WIDTH, Math.min(0, offset));
    if (x) {
      content.style.transform = "translateX(" + x + "px)";
    } else {
      content.style.transform = "";
    }
  }

  async function removeFrameRow(row) {
    if (!row || row.dataset.deleting === "1") return;
    row.dataset.deleting = "1";
    var pendingId = row.getAttribute("data-pending-id");
    try {
      if (pendingId) {
        await deleteTake(pendingId);
      } else {
        var url = row.getAttribute("data-delete-url");
        if (!url) throw new Error("missing delete url");
        var res = await fetch(url, {
          method: "POST",
          headers: {
            "X-CSRFToken": config.csrfToken,
            "X-Ramble-App": "1",
          },
          credentials: "same-origin",
        });
        if (!res.ok) throw new Error("delete failed");
      }
      rollNavCache.clear();
      closeOpenFrameSwipes();
      var height = row.offsetHeight;
      row.style.maxHeight = height + "px";
      row.classList.add("is-removing");
      window.setTimeout(function () {
        if (row.parentNode) row.remove();
      }, 280);
    } catch (err) {
      delete row.dataset.deleting;
      showError("Could not delete this take.");
      setFrameSwipeOffset(row, 0);
      row.classList.remove("is-swipe-open");
    }
  }

  function bindFrameSwipe() {
    if (bindFrameSwipe.done) return;
    bindFrameSwipe.done = true;

    document.addEventListener("click", function (event) {
      if (!frameSwipeEnabled()) return;
      var deleteBtn = event.target.closest(".frame-swipe-delete");
      if (deleteBtn) {
        event.preventDefault();
        event.stopPropagation();
        removeFrameRow(deleteBtn.closest(".frame-row"));
        return;
      }
      var openRow = event.target.closest(".frame-row.is-swipe-open");
      if (openRow && event.target.closest(".frame-swipe-content")) {
        event.preventDefault();
        event.stopPropagation();
        closeOpenFrameSwipes();
        return;
      }
      if (!event.target.closest(".frame-row.is-swipe-open")) {
        closeOpenFrameSwipes();
      }
    }, true);

    document.addEventListener("pointerdown", function (event) {
      if (!frameSwipeEnabled() || event.button !== 0) return;
      if (event.target.closest(".frame-swipe-delete")) return;
      var row = event.target.closest(".frame-row");
      if (!row || (!row.hasAttribute("data-note-id") && !row.hasAttribute("data-pending-id"))) return;
      if (event.target.closest(".album-chip")) return;
      var content = row.querySelector(".frame-swipe-content");
      if (!content || !content.contains(event.target)) return;

      closeOpenFrameSwipes(row);
      frameSwipeDrag = {
        row: row,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        baseOffset: row.classList.contains("is-swipe-open") ? -SWIPE_DELETE_WIDTH : 0,
        moved: false,
        axis: "",
      };
      if (content.setPointerCapture) {
        try {
          content.setPointerCapture(event.pointerId);
        } catch (err) {}
      }
    });

    document.addEventListener("pointermove", function (event) {
      if (!frameSwipeDrag || event.pointerId !== frameSwipeDrag.pointerId) return;
      var dx = event.clientX - frameSwipeDrag.startX;
      var dy = event.clientY - frameSwipeDrag.startY;
      if (!frameSwipeDrag.axis) {
        if (Math.abs(dx) < 6 && Math.abs(dy) < 6) return;
        frameSwipeDrag.axis = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
        if (frameSwipeDrag.axis === "y") {
          frameSwipeDrag.row.classList.remove("is-swipe-dragging");
          frameSwipeDrag = null;
          return;
        }
        frameSwipeDrag.row.classList.add("is-swipe-dragging");
        setFrameSwipeDeleteFocus(frameSwipeDrag.row, true);
      }
      if (frameSwipeDrag.axis !== "x") return;
      event.preventDefault();
      frameSwipeDrag.moved = true;
      setFrameSwipeOffset(frameSwipeDrag.row, frameSwipeDrag.baseOffset + dx);
    }, { passive: false });

    function endFrameSwipeDrag(event) {
      if (!frameSwipeDrag || event.pointerId !== frameSwipeDrag.pointerId) return;
      var row = frameSwipeDrag.row;
      var moved = frameSwipeDrag.moved;
      row.classList.remove("is-swipe-dragging");
      setFrameSwipeDeleteFocus(row, false);
      var content = row.querySelector(".frame-swipe-content");
      if (content && content.releasePointerCapture) {
        try {
          content.releasePointerCapture(event.pointerId);
        } catch (err) {}
      }
      var offset = 0;
      if (content && content.style.transform) {
        var match = content.style.transform.match(/translateX\((-?\d+(?:\.\d+)?)px\)/);
        offset = match ? parseFloat(match[1]) : 0;
      }
      frameSwipeDrag = null;

      if (offset <= -SWIPE_FULL_DELETE) {
        removeFrameRow(row);
        return;
      }
      if (offset <= -SWIPE_OPEN_THRESHOLD) {
        setFrameSwipeOffset(row, -SWIPE_DELETE_WIDTH);
        row.classList.add("is-swipe-open");
        setFrameSwipeDeleteFocus(row, true);
        return;
      }
      setFrameSwipeOffset(row, 0);
      row.classList.remove("is-swipe-open");
      if (moved) row.dataset.swipeSuppressClick = "1";
    }

    document.addEventListener("pointerup", endFrameSwipeDrag);
    document.addEventListener("pointercancel", endFrameSwipeDrag);
    closeOpenFrameSwipes();
  }

  function bindSearch() {
    if (bindSearch.done) return;
    bindSearch.done = true;
    document.addEventListener("click", function (event) {
      var el = eventElement(event);
      var button = el && el.closest("[data-app-search-open]");
      if (!button) return;
      var search = document.getElementById("search");
      if (!search) return;
      search.classList.add("is-open");
      var input = search.querySelector("input[type='text'], input[name='q']");
      if (input) input.focus();
    });
  }

  function bindAlbumDialogs() {
    if (bindAlbumDialogs.done) return;
    bindAlbumDialogs.done = true;
    document.addEventListener("click", function (event) {
      var el = eventElement(event);
      if (!el) return;
      var createOpen = el.closest("[data-album-modal-open]");
      if (createOpen) {
        var createModal = document.getElementById("album-modal");
        if (createModal) {
          createModal.showModal();
          var nameInput = createModal.querySelector('input[name="name"]');
          if (nameInput) nameInput.focus();
        }
        return;
      }
      var deleteOpen = el.closest("[data-album-delete-open]");
      if (deleteOpen) {
        var deleteModal = document.getElementById("album-delete-modal");
        if (deleteModal) deleteModal.showModal();
        return;
      }
      var closeBtn = el.closest("[data-album-modal-close], [data-album-delete-close]");
      if (closeBtn) {
        var dialog = closeBtn.closest("dialog");
        if (dialog) dialog.close();
        return;
      }
      if (el.tagName === "DIALOG") {
        el.close();
      }
    });
    document.addEventListener("close", function (event) {
      var dialog = event.target;
      if (!dialog || dialog.tagName !== "DIALOG") return;
      if (dialog.id === "album-modal") {
        dialog.querySelector("form")?.reset();
      }
    });
  }

  function bindSync() {
    if (bindSync.done) return;
    bindSync.done = true;
    var retry = document.querySelector("[data-app-sync-retry]");
    if (retry) {
      retry.addEventListener("click", function () {
        flushQueue();
      });
    }
    window.addEventListener("online", function () {
      flushQueue();
    });
    window.addEventListener("offline", function () {
      updateSyncBanner();
    });
  }

  function prefersNativeShareSheet() {
    if (!navigator.share) return false;
    var ua = navigator.userAgent || "";
    return /iPhone|iPad|iPod|Android/i.test(ua);
  }

  function sharePreviewText(text) {
    var trimmed = text.trim();
    if (trimmed.length <= 280) return trimmed;
    return trimmed.slice(0, 277) + "…";
  }

  function closeAppShareSheet() {
    var sheet = document.querySelector("[data-app-share-sheet]");
    if (!sheet) return;
    sheet.hidden = true;
    document.body.classList.remove("is-share-open");
    var copyRow = sheet.querySelector("[data-app-share-copy]");
    if (copyRow) copyRow.classList.remove("is-done");
  }

  function openAppShareSheet(text) {
    var sheet = document.querySelector("[data-app-share-sheet]");
    if (!sheet) return;
    var preview = sheet.querySelector("[data-app-share-preview]");
    var nativeRow = sheet.querySelector("[data-app-share-native]");
    if (preview) preview.textContent = sharePreviewText(text);
    if (nativeRow) {
      nativeRow.hidden = !prefersNativeShareSheet();
      nativeRow.dataset.shareText = text;
    }
    sheet.dataset.shareText = text;
    sheet.hidden = false;
    document.body.classList.add("is-share-open");
  }

  async function copyShareText(text) {
    if (!text.trim()) return false;
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy");
        document.body.removeChild(area);
        return true;
      } catch (copyErr) {
        document.body.removeChild(area);
        return false;
      }
    }
  }

  function bindAppShareSheet() {
    var sheet = document.querySelector("[data-app-share-sheet]");
    if (!sheet || sheet.dataset.bound === "1") return;
    sheet.dataset.bound = "1";

    sheet.querySelectorAll("[data-app-share-close]").forEach(function (button) {
      button.addEventListener("click", function () {
        closeAppShareSheet();
      });
    });

    var copyRow = sheet.querySelector("[data-app-share-copy]");
    if (copyRow) {
      copyRow.addEventListener("click", async function () {
        var text = sheet.dataset.shareText || "";
        var ok = await copyShareText(text);
        if (!ok) return;
        copyRow.classList.add("is-done");
        window.setTimeout(function () {
          closeAppShareSheet();
        }, 700);
      });
    }

    var nativeRow = sheet.querySelector("[data-app-share-native]");
    if (nativeRow) {
      nativeRow.addEventListener("click", async function () {
        var text = nativeRow.dataset.shareText || sheet.dataset.shareText || "";
        if (!text.trim() || !navigator.share) return;
        try {
          await navigator.share({ text: text });
          closeAppShareSheet();
        } catch (err) {
          if (err && err.name === "AbortError") return;
        }
      });
    }

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !sheet.hidden) closeAppShareSheet();
    });
  }

  function bindTakePageHelpers() {
    if (bindTakePageHelpers.done) return;
    bindTakePageHelpers.done = true;

    document.addEventListener("click", async function (event) {
      var el = eventElement(event);
      var button = el && el.closest("[data-copy-target]");
      if (!button || button.disabled) return;
      var source = document.getElementById(button.getAttribute("data-copy-target"));
      if (!source || !source.value.trim()) return;

      var label = button.textContent;
      event.preventDefault();
      try {
        await navigator.clipboard.writeText(source.value);
        button.textContent = "Copied";
        window.setTimeout(function () {
          button.textContent = label;
        }, 1500);
      } catch (err) {
        source.select();
        document.execCommand("copy");
        button.textContent = "Copied";
        window.setTimeout(function () {
          button.textContent = label;
        }, 1500);
      }
    });
  }

  function bindShare() {
    bindAppShareSheet();
    if (bindShare.bound) return;
    bindShare.bound = true;

    document.addEventListener("click", async function (event) {
      var el = eventElement(event);
      var button = el && el.closest("[data-app-share]");
      if (!button || button.disabled) return;
      var source = document.getElementById(button.getAttribute("data-app-share"));
      var text = source ? source.value : "";
      if (!text.trim()) return;

      if (prefersNativeShareSheet()) {
        try {
          await navigator.share({ text: text });
          return;
        } catch (err) {
          if (err && err.name === "AbortError") return;
        }
      }

      if (isMobile()) {
        openAppShareSheet(text);
        return;
      }

      var copied = await copyShareText(text);
      if (copied) {
        button.classList.add("is-copied");
        window.setTimeout(function () {
          button.classList.remove("is-copied");
        }, 1200);
      }
    });
  }

  async function recoverLiveRecording() {
    var live = await loadLive().catch(function () { return null; });
    if (!live || !live.chunks || !live.chunks.length) return;
    var blob = new Blob(live.chunks, { type: live.mimeType || "audio/webm" });
    if (!blob.size) {
      await clearLive();
      return;
    }
    var take = {
      id: uuid(),
      createdAt: live.startedAt ? new Date(live.startedAt).toISOString() : new Date().toISOString(),
      duration: live.startedAt ? Math.max(1, Math.round((Date.now() - live.startedAt) / 1000)) : 1,
      mimeType: blob.type,
      blob: blob,
      status: "pending",
      error: "",
      attempts: 0,
    };
    await putTake(take);
    await clearLive();
    insertOptimisticRow(take);
  }

  function bindPageLifecycle() {
    window.addEventListener("pagehide", function () {
      if (state.recording && state.chunks.length) {
        saveLive(state.chunks.slice(), state.mimeType, state.startedAt);
      }
    });
    window.addEventListener("pageshow", function () {
      if (!recordingAllowed()) {
        resetRecordingUi();
      }
      applyShell();
    });
  }

  function init() {
    if (!recordingAllowed()) {
      resetRecordingUi();
    }
    applyShell();
    media.addEventListener("change", applyShell);
    bindTakePageHelpers();
    if (!isAppPage()) return;
    bindSearch();
    bindShare();
    bindTakeToolbar();
    bindFrameSwipe();
    bindRollNav();
    bindAlbumDialogs();
    if (onRollShellPage()) {
      prefetchRollNavNeighbors();
      if (window.requestIdleCallback) {
        window.requestIdleCallback(function () {
          prefetchVisibleTakes();
        }, { timeout: 1200 });
      } else {
        prefetchVisibleTakes();
      }
    }
    prefetchTakeToolbarLinks();
    bindPageLifecycle();
    bindShutter();
    bindSync();
    recoverLiveRecording().then(flushQueue).catch(function () {
      flushQueue();
    });
    allTakes().then(function (takes) {
      takes.forEach(insertOptimisticRow);
      updateSyncBanner();
    }).catch(function () {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
