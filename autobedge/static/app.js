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
  const lockKey = "autobedge-planning-status-poller";
  const lockTtlMs = 4000;
  const instanceId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  let polling = false;

  if (!meta || pendingOverlay || window.__autobedgePlanningStatusPollingStarted) {
    return;
  }
  window.__autobedgePlanningStatusPollingStarted = true;

  function nowMs() {
    return Date.now();
  }

  function readLock() {
    try {
      const raw = window.localStorage.getItem(lockKey);
      return raw ? JSON.parse(raw) : null;
    } catch (_error) {
      return null;
    }
  }

  function writeLock() {
    try {
      window.localStorage.setItem(lockKey, JSON.stringify({ id: instanceId, ts: nowMs() }));
    } catch (_error) {}
  }

  function releaseLock() {
    try {
      const current = readLock();
      if (current && current.id === instanceId) {
        window.localStorage.removeItem(lockKey);
      }
    } catch (_error) {}
  }

  function hasLeadership() {
    if (document.visibilityState === "hidden") {
      return false;
    }
    const current = readLock();
    if (!current || nowMs() - Number(current.ts || 0) > lockTtlMs) {
      writeLock();
      return true;
    }
    if (current.id === instanceId) {
      writeLock();
      return true;
    }
    return false;
  }

  function checkPlanningStatus() {
    if (polling || !hasLeadership()) {
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

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      checkPlanningStatus();
      return;
    }
    releaseLock();
  });
  window.addEventListener("pagehide", releaseLock);
  window.addEventListener("beforeunload", releaseLock);

  checkPlanningStatus();
  window.setInterval(checkPlanningStatus, 1000);
})();
