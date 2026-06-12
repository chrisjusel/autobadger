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
  function getStack() {
    let stack = document.getElementById("toastStack");
    if (!stack) {
      stack = document.createElement("div");
      stack.className = "toast-stack";
      stack.id = "toastStack";
      document.body.appendChild(stack);
    }
    return stack;
  }

  function dismiss(toast) {
    if (toast.__dismissed) {
      return;
    }
    toast.__dismissed = true;
    toast.classList.remove("toast-in");
    toast.classList.add("toast-out");
    window.setTimeout(function () {
      toast.remove();
    }, 340);
  }

  function activate(toast, opts) {
    opts = opts || {};
    const closeBtn = toast.querySelector(".toast-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        dismiss(toast);
      });
    }
    window.requestAnimationFrame(function () {
      toast.classList.add("toast-in");
    });
    if (!opts.sticky) {
      window.setTimeout(function () {
        dismiss(toast);
      }, opts.duration || 4400);
    }
    return {
      el: toast,
      dismiss: function () {
        dismiss(toast);
      },
      setText: function (text) {
        const node = toast.querySelector(".toast-text");
        if (node) {
          node.textContent = text;
        }
      },
    };
  }

  function spawn(message, opts) {
    opts = opts || {};
    const toast = document.createElement("div");
    toast.className = "toast" + (opts.error ? " toast-error" : "") + (opts.planning ? " toast-planning" : "");
    toast.setAttribute("role", "status");
    const icon = opts.icon || (opts.error ? "alert-triangle" : opts.planning ? "loader-2" : "check-circle-2");
    const iconSpan = document.createElement("span");
    iconSpan.className = "toast-icon";
    iconSpan.innerHTML = '<i data-lucide="' + icon + '"></i>';
    const textSpan = document.createElement("span");
    textSpan.className = "toast-text";
    textSpan.textContent = message;
    toast.appendChild(iconSpan);
    toast.appendChild(textSpan);
    if (!opts.sticky) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "toast-close";
      button.setAttribute("aria-label", "Chiudi notifica");
      button.innerHTML = '<i data-lucide="x"></i>';
      toast.appendChild(button);
    }
    getStack().appendChild(toast);
    if (window.lucide) {
      window.lucide.createIcons();
    }
    return activate(toast, opts);
  }

  window.autobedgeToast = { spawn: spawn };

  const serverToast = document.querySelector(".toast[data-toast-auto]");
  if (serverToast) {
    activate(serverToast, {});
  }

  try {
    const done = window.sessionStorage.getItem("autobedge-plan-done");
    if (done) {
      window.sessionStorage.removeItem("autobedge-plan-done");
      spawn(done, {});
    }
  } catch (_error) {}
})();

(function () {
  const meta = document.querySelector('meta[name="autobedge-planning-status-url"]');
  const lockKey = "autobedge-planning-status-poller";
  const lockTtlMs = 12000;
  const pollIntervalMs = 4000;
  const instanceId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const isDashboard = window.location.pathname === "/dashboard" || window.location.pathname === "/";
  let polling = false;
  let lastPending = null;
  let stickyToast = null;

  if (!meta || window.__autobedgePlanningStatusPollingStarted) {
    return;
  }
  window.__autobedgePlanningStatusPollingStarted = true;

  function ensureSticky(message) {
    if (stickyToast) {
      stickyToast.setText(message);
      return;
    }
    if (window.autobedgeToast) {
      stickyToast = window.autobedgeToast.spawn(message, { sticky: true, planning: true });
    }
  }

  function clearSticky() {
    if (stickyToast) {
      stickyToast.dismiss();
      stickyToast = null;
    }
  }

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
        if (!payload) {
          return;
        }
        const pending = !!payload.pending;
        if (pending) {
          ensureSticky(payload.message || "Pianificazione in corso…");
        } else {
          clearSticky();
          if (lastPending === true && isDashboard) {
            try {
              window.sessionStorage.setItem("autobedge-plan-done", payload.message || "Pianificazione aggiornata.");
            } catch (_error) {}
            window.location.reload();
            return;
          }
        }
        lastPending = pending;
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
  window.setInterval(checkPlanningStatus, pollIntervalMs);
})();
