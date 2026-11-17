/*
 * Minimal signature pad: works with mouse, touch screens, styluses and
 * USB signature pads that act as a pointer device.
 * Usage: <div class="sig-pad-wrap" data-target="id_of_hidden_input"><canvas></canvas></div>
 *        <button data-clear="id_of_hidden_input">Clear</button>
 */
(function () {
  function setup(wrap) {
    const canvas = wrap.querySelector("canvas");
    const input = document.getElementById(wrap.dataset.target);
    const ctx = canvas.getContext("2d");
    let drawing = false, hasInk = false, last = null;

    function resize() {
      const ratio = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * ratio;
      canvas.height = rect.height * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.lineWidth = 2.2;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#0b1f4a";
      clear();
    }
    function pos(e) {
      const r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    }
    function clear() {
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.restore();
      hasInk = false;
      input.value = "";
      wrap.classList.remove("signed");
    }
    function commit() {
      if (hasInk) {
        input.value = canvas.toDataURL("image/png");
        wrap.classList.add("signed");
      }
    }
    canvas.addEventListener("pointerdown", (e) => {
      drawing = true; last = pos(e); canvas.setPointerCapture(e.pointerId);
      ctx.beginPath(); ctx.arc(last.x, last.y, 1, 0, Math.PI * 2); ctx.fillStyle = ctx.strokeStyle; ctx.fill();
      hasInk = true;
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!drawing) return;
      const p = pos(e);
      ctx.beginPath(); ctx.moveTo(last.x, last.y); ctx.lineTo(p.x, p.y); ctx.stroke();
      last = p; hasInk = true;
    });
    ["pointerup", "pointercancel", "pointerleave"].forEach((ev) =>
      canvas.addEventListener(ev, () => { if (drawing) { drawing = false; commit(); } })
    );
    document.querySelectorAll('[data-clear="' + wrap.dataset.target + '"]').forEach((btn) =>
      btn.addEventListener("click", (e) => { e.preventDefault(); clear(); })
    );
    resize();
  }
  document.querySelectorAll(".sig-pad-wrap").forEach(setup);
})();
