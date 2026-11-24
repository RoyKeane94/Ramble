(function () {
  var table = document.querySelector("[data-crm-inline]");
  if (!table) return;

  var csrfToken = table.getAttribute("data-crm-csrf") || "";
  var activeCell = null;
  var saving = false;

  function cookieCsrf() {
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function emptyDisplay() {
    return '<span class="crm-empty">—</span>';
  }

  function renderDisplay(cell, value) {
    if (!value) return emptyDisplay();
    var link = cell.getAttribute("data-crm-link");
    var safe = escapeHtml(value);
    if (link === "mailto") {
      return '<a class="crm-link" href="mailto:' + safe + '">' + safe + "</a>";
    }
    if (link === "tel") {
      return '<a class="crm-link" href="tel:' + safe + '">' + safe + "</a>";
    }
    if (link === "url") {
      return (
        '<a class="crm-link" href="' +
        safe +
        '" target="_blank" rel="noopener noreferrer">' +
        safe +
        "</a>"
      );
    }
    if (cell.getAttribute("data-crm-field") === "personalisation_detail") {
      return (
        '<span class="crm-hover-tip" tabindex="0">' +
        '<span class="crm-hover-tip-trigger">View</span>' +
        '<span class="crm-hover-tip-panel" role="tooltip">' +
        safe +
        "</span></span>"
      );
    }
    return safe;
  }

  function setDisplay(cell, value) {
    cell.setAttribute("data-crm-value", value || "");
    var display = cell.querySelector(".crm-editable-display");
    if (!display) {
      display = document.createElement("span");
      display.className = "crm-editable-display";
      cell.appendChild(display);
    }
    display.innerHTML = renderDisplay(cell, value);
    if (cell.classList.contains("crm-clip")) {
      cell.title = value || "Click to edit";
    }
  }

  function cancelEdit(cell, restoreValue) {
    if (!cell) return;
    cell.classList.remove("is-editing");
    cell.innerHTML = "";
    var display = document.createElement("span");
    display.className = "crm-editable-display";
    cell.appendChild(display);
    setDisplay(cell, restoreValue);
    if (activeCell === cell) activeCell = null;
  }

  function saveEdit(cell, input, original) {
    if (saving) return;
    var value = (input.value || "").trim();
    if (value === (original || "").trim()) {
      cancelEdit(cell, original);
      return;
    }

    var row = cell.closest("tr");
    var url = row && row.getAttribute("data-crm-field-url");
    var field = cell.getAttribute("data-crm-field");
    if (!url || !field) {
      cancelEdit(cell, original);
      return;
    }

    saving = true;
    cell.classList.add("is-saving");
    input.disabled = true;

    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken || cookieCsrf(),
      },
      body: JSON.stringify({ field: field, value: value }),
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data || !result.data.ok) {
          var message =
            (result.data && result.data.error) || "Could not save. Try again.";
          window.alert(message);
          cancelEdit(cell, original);
          return;
        }
        cancelEdit(cell, result.data.value || "");
      })
      .catch(function () {
        window.alert("Could not save. Try again.");
        cancelEdit(cell, original);
      })
      .finally(function () {
        saving = false;
        cell.classList.remove("is-saving");
      });
  }

  function startEdit(cell) {
    if (!cell || cell.classList.contains("is-editing") || saving) return;
    if (activeCell && activeCell !== cell) {
      var previousInput = activeCell.querySelector(".crm-inline-input");
      if (previousInput) {
        previousInput.blur();
      }
    }

    var original = cell.getAttribute("data-crm-value") || "";
    var inputKind = cell.getAttribute("data-crm-input") || "text";
    var input;
    if (inputKind === "textarea") {
      input = document.createElement("textarea");
      input.rows = 3;
    } else {
      input = document.createElement("input");
      input.type = inputKind === "email" || inputKind === "tel" ? inputKind : "text";
    }
    input.className = "field crm-input crm-inline-input";
    input.value = original;
    input.setAttribute("aria-label", "Edit " + (cell.getAttribute("data-crm-field") || "field"));

    cell.classList.add("is-editing");
    cell.innerHTML = "";
    cell.appendChild(input);
    activeCell = cell;
    input.focus();
    if (typeof input.select === "function") input.select();

    var finished = false;
    function finish(save) {
      if (finished) return;
      finished = true;
      if (save) {
        saveEdit(cell, input, original);
      } else {
        cancelEdit(cell, original);
      }
    }

    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
        return;
      }
      if (event.key === "Enter" && inputKind !== "textarea") {
        event.preventDefault();
        finish(true);
      }
      if (event.key === "Enter" && inputKind === "textarea" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        finish(true);
      }
    });

    input.addEventListener("blur", function () {
      // Defer so a click that opens another cell can run first.
      setTimeout(function () {
        if (activeCell === cell && !finished) finish(true);
      }, 0);
    });
  }

  table.addEventListener("click", function (event) {
    var cell = event.target.closest("td.crm-editable");
    if (!cell || !table.contains(cell)) return;
    if (cell.classList.contains("is-editing")) return;

    // Let the personalisation hover tip work; double-click still edits.
    if (event.target.closest(".crm-hover-tip") && (cell.getAttribute("data-crm-value") || "")) {
      return;
    }

    var link = event.target.closest("a.crm-link");
    // Cmd/Ctrl-click keeps opening website / mailto / tel links.
    if (link && cell.contains(link) && (event.metaKey || event.ctrlKey)) {
      return;
    }

    event.preventDefault();
    startEdit(cell);
  });

  table.addEventListener("dblclick", function (event) {
    var cell = event.target.closest("td.crm-editable");
    if (!cell || !table.contains(cell)) return;
    event.preventDefault();
    startEdit(cell);
  });

  table.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    var cell = event.target.closest("td.crm-editable");
    if (!cell || event.target !== cell) return;
    event.preventDefault();
    startEdit(cell);
  });
})();
