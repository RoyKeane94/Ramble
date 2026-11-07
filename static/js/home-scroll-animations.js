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

  var heroVideo = document.querySelector(".hero-landing-video");
  if (heroVideo && reduced) {
    heroVideo.removeAttribute("autoplay");
    heroVideo.pause();
    heroVideo.currentTime = 0;
  }

  var examples = Array.prototype.slice.call(
    document.querySelectorAll(".talk-through-example")
  );
  if (examples.length < 2 || reduced) return;

  var index = 0;
  var holdMs = 2200;
  var fadeMs = 450;
  var timer = null;

  function showNext() {
    var current = examples[index];
    var nextIndex = (index + 1) % examples.length;
    var next = examples[nextIndex];

    current.classList.remove("is-active");
    current.classList.add("is-leaving");
    next.classList.add("is-active");

    window.setTimeout(function () {
      current.classList.remove("is-leaving");
    }, fadeMs);

    index = nextIndex;
    timer = window.setTimeout(showNext, holdMs);
  }

  timer = window.setTimeout(showNext, holdMs);

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      window.clearTimeout(timer);
      timer = null;
      return;
    }
    if (!timer) timer = window.setTimeout(showNext, holdMs);
  });
})();
