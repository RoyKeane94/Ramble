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
  if (!heroVideo) return;

  if (reduced) {
    heroVideo.removeAttribute("autoplay");
    heroVideo.pause();
    heroVideo.currentTime = 0;
  }
})();
