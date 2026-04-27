(function () {
  const shell = document.querySelector(".app-shell");
  const indicator = document.querySelector(".pull-refresh");
  const threshold = 86;
  const maxPull = 126;
  let startY = 0;
  let pull = 0;
  let tracking = false;
  let refreshing = false;

  if (!shell || !indicator) {
    return;
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

  shell.addEventListener("touchstart", function (event) {
    if (refreshing || shell.scrollTop > 0 || event.touches.length !== 1) {
      tracking = false;
      return;
    }
    startY = event.touches[0].clientY;
    tracking = true;
  }, { passive: true });

  shell.addEventListener("touchmove", function (event) {
    if (!tracking || refreshing || event.touches.length !== 1) {
      return;
    }
    const distance = event.touches[0].clientY - startY;
    if (distance <= 0 || shell.scrollTop > 0) {
      reset();
      return;
    }
    event.preventDefault();
    setPull(distance * 0.62);
  }, { passive: false });

  shell.addEventListener("touchend", function () {
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

  shell.addEventListener("touchcancel", reset, { passive: true });
})();
