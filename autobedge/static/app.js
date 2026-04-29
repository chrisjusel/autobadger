(function () {
  const indicator = document.querySelector(".pull-refresh");
  const threshold = 86;
  const maxPull = 126;
  let startY = 0;
  let pull = 0;
  let tracking = false;
  let refreshing = false;

  if (!indicator) {
    return;
  }

  function scrollTop() {
    return window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
  }

  function setPull(distance) {
    pull = Math.max(0, Math.min(distance, maxPull));
    const progress = Math.min(pull / threshold, 1);
    const y = -76 + pull;
    indicator.classList.toggle("visible", pull > 6);
    indicator.style.transform = `translate(-50%, ${y}px) scale(${0.92 + progress * 0.08})`;
    indicator.style.setProperty("--pull-rotation", `${progress * 220}deg`);
  }

  function reset() {
    tracking = false;
    pull = 0;
    indicator.classList.remove("visible", "refreshing");
    indicator.style.transform = "translate(-50%, -76px) scale(.92)";
    indicator.style.setProperty("--pull-rotation", "0deg");
  }

  window.addEventListener("touchstart", function (event) {
    if (refreshing || scrollTop() > 0 || event.touches.length !== 1) {
      tracking = false;
      return;
    }
    startY = event.touches[0].clientY;
    tracking = true;
  }, { passive: true });

  window.addEventListener("touchmove", function (event) {
    if (!tracking || refreshing || event.touches.length !== 1) {
      return;
    }
    const distance = event.touches[0].clientY - startY;
    if (distance <= 0 || scrollTop() > 0) {
      reset();
      return;
    }
    setPull(distance * 0.62);
  }, { passive: true });

  window.addEventListener("touchend", function () {
    if (!tracking || refreshing) {
      return;
    }
    if (pull >= threshold) {
      refreshing = true;
      indicator.classList.add("visible", "refreshing");
      indicator.style.transform = "translate(-50%, 26px) scale(1)";
      window.setTimeout(function () {
        window.location.reload();
      }, 260);
      return;
    }
    reset();
  }, { passive: true });

  window.addEventListener("touchcancel", reset, { passive: true });
})();

(function () {
  const meta = document.querySelector('meta[name="autobedge-planning-status-url"]');
  const pendingOverlay = document.querySelector(".pending-overlay");
  let polling = false;

  if (!meta || pendingOverlay) {
    return;
  }

  function checkPlanningStatus() {
    if (polling) {
      return;
    }
    polling = true;
    window.fetch(meta.content, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (response) {
        if (!response.ok) {
          return null;
        }
        return response.json();
      })
      .then(function (payload) {
        if (payload && payload.pending) {
          window.location.reload();
        }
      })
      .catch(function () {})
      .finally(function () {
        polling = false;
      });
  }

  window.setInterval(checkPlanningStatus, 1000);
})();
