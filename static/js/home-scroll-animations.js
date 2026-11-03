(function () {
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (!reduced) {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: "0px 0px -40px 0px" }
    );
    document.querySelectorAll(".reveal").forEach(function (el) {
      observer.observe(el);
    });
    document.querySelectorAll(".step-block").forEach(function (block) {
      block.querySelectorAll(".reveal").forEach(function (el, i) {
        el.style.transitionDelay = i * 0.12 + "s";
      });
    });
    document.querySelectorAll(".hero-landing-copy > *").forEach(function (el, i) {
      el.style.animationDelay = i * 0.1 + "s";
      el.classList.add("hero-enter");
    });
  } else {
    document.querySelectorAll(".reveal").forEach(function (el) {
      el.classList.add("is-visible");
    });
  }

  var preview = document.getElementById("hero-recents-preview");
  if (!preview) return;

  var raw =
    "I keep finding myself out and about and, um, ideas pop into my head. I don\u2019t have a notepad with me and, uh, I suppose I could use notes on my phone, but it\u2019s clunky and, you know, they, they always just stay on my phone anyway. What if we, ah, what if we built something which was super easy to use? You just press record and, um, you go. The output is tidied to remove any filler and any false starts, but it never rewrites, so it\u2019s always your words. It\u2019s instantly on your phone and laptop, and if you ever wanted to edit it, you can. You should also be able to create albums to group your rambles. Let\u2019s call this Ramble.";
  var fillers = [", um,", ", uh,", ", you know,", " they, they", ", ah, what if we"];
  var tidyParagraphs = [
    "I keep finding myself out and about and ideas pop into my head. I don\u2019t have a notepad with me and I suppose I could use notes on my phone, but it\u2019s clunky and they always just stay on my phone anyway.",
    "What if we built something which was super easy to use? You just press record and you go. The output is tidied to remove any filler and any false starts, but it never rewrites, so it\u2019s always your words. It\u2019s instantly on your phone and laptop, and if you ever wanted to edit it, you can.",
    "You should also be able to create albums to group your rambles. Let\u2019s call this Ramble.",
  ];
  var recordSeconds = 88;
  var phaseEl = document.querySelector(".recents-phase");
  var durEl = document.querySelector(".recents-meta-dur");
  var albumChips = document.getElementById("hero-demo-album-chips");
  var albumPanel = document.getElementById("hero-demo-album-panel");
  var albumRow = document.getElementById("hero-demo-album-row");

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function setPhase(label, isTalk) {
    if (!phaseEl) return;
    phaseEl.textContent = label;
    phaseEl.classList.toggle("is-talk", !!isTalk);
  }

  function formatDur(totalSec) {
    var m = Math.floor(totalSec / 60);
    var s = totalSec % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function wrapFillers(text) {
    var parts = [{ t: text, f: false }];
    fillers.forEach(function (filler) {
      var next = [];
      parts.forEach(function (part) {
        if (part.f) {
          next.push(part);
          return;
        }
        var idx = part.t.indexOf(filler);
        if (idx === -1) {
          next.push(part);
          return;
        }
        if (idx > 0) next.push({ t: part.t.slice(0, idx), f: false });
        next.push({ t: filler, f: true });
        var rest = part.t.slice(idx + filler.length);
        if (rest) next.push({ t: rest, f: false });
      });
      parts = next;
    });
    return parts
      .map(function (part) {
        if (!part.f) return part.t;
        return '<span class="recents-filler">' + part.t + "</span>";
      })
      .join("");
  }

  function showTidy() {
    preview.classList.add("is-tidy");
    preview.innerHTML = tidyParagraphs
      .map(function (p) {
        return "<p>" + p + "</p>";
      })
      .join("");
  }

  function resetAlbum() {
    if (albumChips) {
      albumChips.hidden = true;
      albumChips.setAttribute("aria-hidden", "true");
      albumChips.classList.remove("is-visible");
    }
    if (albumPanel) {
      albumPanel.hidden = true;
      albumPanel.classList.remove("is-open");
    }
    if (albumRow) albumRow.classList.remove("is-in");
  }

  async function showAlbumAssign() {
    setPhase("Album", false);
    if (albumPanel) {
      albumPanel.hidden = false;
      await sleep(40);
      albumPanel.classList.add("is-open");
    }
    await sleep(320);
    if (albumRow) albumRow.classList.add("is-in");
    await sleep(520);
    if (albumPanel) {
      albumPanel.classList.remove("is-open");
      await sleep(280);
      albumPanel.hidden = true;
    }
    if (albumChips) {
      albumChips.hidden = false;
      albumChips.removeAttribute("aria-hidden");
      await sleep(40);
      albumChips.classList.add("is-visible");
    }
  }

  async function runCycle() {
    if (reduced) {
      showTidy();
      setPhase("Tidy", false);
      if (durEl) durEl.textContent = formatDur(recordSeconds);
      if (albumChips) {
        albumChips.hidden = false;
        albumChips.classList.add("is-visible");
      }
      return;
    }

    while (true) {
      resetAlbum();
      setPhase("Talk", true);
      preview.classList.remove("is-tidy");
      preview.innerHTML = "";
      var caret = document.createElement("span");
      caret.className = "recents-caret";
      caret.setAttribute("aria-hidden", "true");

      for (var i = 0; i <= raw.length; i++) {
        preview.textContent = raw.slice(0, i);
        preview.appendChild(caret);
        if (durEl) {
          durEl.textContent = formatDur(Math.min(recordSeconds, Math.floor(i / 7)));
        }
        await sleep(42);
      }
      await sleep(1100);

      setPhase("Tidy", false);
      preview.innerHTML = wrapFillers(raw);
      await sleep(120);
      preview.querySelectorAll(".recents-filler").forEach(function (el) {
        el.classList.add("is-gone");
      });
      await sleep(650);
      showTidy();
      if (durEl) durEl.textContent = formatDur(recordSeconds);
      await sleep(1400);
      await showAlbumAssign();
      await sleep(3800);
    }
  }

  runCycle();
})();
