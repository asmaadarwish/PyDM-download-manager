/* PyDM Video Catcher: in-page button.
   Shows a small "Download video" pill over any playing/visible video. The click is
   handled by the background worker, which knows what the page actually loaded. */
(() => {
  if (window.__pydmCatcher) return;
  window.__pydmCatcher = true;

  const ar = /^ar/i.test(navigator.language || "");
  const TXT = ar
    ? { dl: "تحميل الفيديو", q: "الجودة", found: "اتلقط من الصفحة", best: "أعلى جودة", audio: "صوت فقط", sending: "جاري الإرسال…", ok: "اتبعت لـ PyDM", wake: "بيفتح PyDM…", bad: "ماتبعتش. جرّب تاني" }
    : { dl: "Download video", q: "Quality", found: "Caught on this page", best: "Best quality", audio: "Audio only", sending: "Sending…", ok: "Sent to PyDM", wake: "Opening PyDM…", bad: "Couldn't send. Try again" };

  const host = document.createElement("div");
  host.style.cssText = "all:initial;position:fixed;z-index:2147483647;top:0;left:0;width:0;height:0;pointer-events:none;";
  const root = host.attachShadow({ mode: "closed" });
  root.innerHTML = `
    <style>
      .pill{position:fixed;display:none;align-items:center;gap:8px;height:38px;padding:0 15px 0 11px;border:0;border-radius:999px;
        background:#0A7F72;color:#fff;font:600 14px/1 "Segoe UI",system-ui,sans-serif;cursor:pointer;pointer-events:auto;
        box-shadow:0 6px 18px rgba(0,0,0,.35),0 0 0 2px rgba(255,255,255,.85);white-space:nowrap;direction:${ar ? "rtl" : "ltr"};
        transition:transform .12s,background .15s}
      .pill:hover{background:#0B9484;transform:translateY(-1px)}
      .pill.ok{background:#23804F}.pill.bad{background:#BF3B33}
      svg{width:18px;height:18px;fill:none;stroke:#fff;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}
      .wrap{position:fixed;display:none;pointer-events:auto;direction:${ar ? "rtl" : "ltr"}}
      .wrap .pill{position:static;display:inline-flex;border-radius:999px 0 0 999px;box-shadow:none}
      .caret{height:38px;width:34px;border:0;border-radius:0 999px 999px 0;background:#08695F;cursor:pointer;display:inline-grid;place-items:center;margin-inline-start:1px}
      .caret:hover{background:#0B9484} .caret svg{width:14px;height:14px}
      .wrap{box-shadow:0 6px 18px rgba(0,0,0,.35),0 0 0 2px rgba(255,255,255,.85);border-radius:999px}
      .menu{position:absolute;top:46px;inset-inline-end:0;min-width:230px;max-height:320px;overflow:auto;padding:6px;border-radius:14px;
        background:#fff;color:#0C2326;box-shadow:0 12px 32px rgba(0,0,0,.4);font:500 13.5px/1.3 "Segoe UI",system-ui,sans-serif;display:none}
      .menu h4{margin:6px 8px 4px;font:600 11.5px/1 "Segoe UI",system-ui,sans-serif;color:#587370}
      .menu button{display:flex;justify-content:space-between;gap:14px;width:100%;border:0;background:none;padding:9px 10px;border-radius:9px;cursor:pointer;
        color:inherit;font:inherit;text-align:start} .menu button:hover{background:#E3EEEC}
      .menu small{color:#587370;direction:ltr}
    </style>
    <div class="wrap"><button class="pill" type="button"><svg viewBox="0 0 24 24"><path d="M12 4v11"/><path d="m7 11 5 5 5-5"/><path d="M5 20h14"/></svg><span></span></button><button class="caret" type="button" aria-label="Quality"><svg viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg></button><div class="menu"></div></div>`;
  const wrap = root.querySelector(".wrap"), pill = root.querySelector(".pill"), caret = root.querySelector(".caret"), menu = root.querySelector(".menu");
  const label = root.querySelector("span");
  label.textContent = TXT.dl;
  (document.documentElement || document).appendChild(host);

  let target = null, hideTimer = null, busy = false;

  const videos = () => Array.from(document.querySelectorAll("video")).filter((v) => {
    const r = v.getBoundingClientRect();
    return r.width >= 220 && r.height >= 120 && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
  });
  const under = (x, y) => videos().find((v) => { const r = v.getBoundingClientRect(); return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom; });

  function place(v) {
    const r = v.getBoundingClientRect();
    const w = wrap.offsetWidth || 190;
    const left = ar ? r.left + 12 : r.right - w - 12;
    wrap.style.top = Math.max(8, r.top + 12) + "px";
    wrap.style.left = Math.max(8, Math.min(innerWidth - w - 8, left)) + "px";
  }
  function show(v) {
    target = v;
    wrap.style.display = "block";
    place(v);
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hide, 2600);
  }
  function hide() { if (busy || menu.style.display === "block") return; wrap.style.display = "none"; target = null; }

  let raf = 0;
  document.addEventListener("mousemove", (e) => {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const v = under(e.clientX, e.clientY);
      if (v) show(v); else if (!pill.matches(":hover")) { /* let the timer hide it */ }
    });
  }, { passive: true, capture: true });
  wrap.addEventListener("mouseenter", () => clearTimeout(hideTimer));
  wrap.addEventListener("mouseleave", () => { hideTimer = setTimeout(hide, 1200); });
  addEventListener("scroll", () => { if (target) place(target); }, { passive: true, capture: true });
  addEventListener("resize", () => { if (target) place(target); });
  document.addEventListener("fullscreenchange", () => { (document.fullscreenElement || document.documentElement).appendChild(host); });

  function flash(text, cls) {
    label.textContent = text; pill.className = "pill " + (cls || "");
  }
  function sendNow(extra) {
    if (busy) return;
    busy = true; menu.style.display = "none"; flash(TXT.sending);
    const src = target && (target.currentSrc || target.src) || "";
    chrome.runtime.sendMessage(Object.assign({ type: "grab", src: /^blob:/i.test(src) ? "" : src }, extra || {}), (res) => {
      if (chrome.runtime.lastError || !res) flash(TXT.bad, "bad");
      else if (res.ok) flash(TXT.ok, "ok");
      else if (res.launched) flash(TXT.wake, "ok");
      else flash(TXT.bad, "bad");
      setTimeout(() => { busy = false; flash(TXT.dl); hide(); }, 2200);
    });
  }
  pill.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); sendNow(); }, true);

  const fmt = (n) => { if (!n) return ""; const u = ["B", "KB", "MB", "GB"]; let i = 0; while (n >= 1024 && i < 3) { n /= 1024; i++; } return (i ? n.toFixed(1) : n) + " " + u[i]; };
  caret.addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    if (menu.style.display === "block") { menu.style.display = "none"; return; }
    chrome.runtime.sendMessage({ type: "list" }, (res) => {
      const items = (res && res.items) || [];
      menu.innerHTML = "";
      const add = (text, small, extra) => {
        const b = document.createElement("button");
        const t = document.createElement("span"); t.textContent = text; b.appendChild(t);
        if (small) { const s = document.createElement("small"); s.textContent = small; b.appendChild(s); }
        b.addEventListener("click", (ev) => { ev.stopPropagation(); sendNow(extra); }, true);
        menu.appendChild(b);
      };
      const head = (t) => { const h = document.createElement("h4"); h.textContent = t; menu.appendChild(h); };
      if (items.length) {
        head(TXT.found);
        items.slice(0, 6).forEach((it) => add(it.kind.toUpperCase(), fmt(it.size) || (new URL(it.url).hostname), { itemUrl: it.url }));
      }
      head(TXT.q);
      [["best", TXT.best], ["1080", "1080p"], ["720", "720p"], ["480", "480p"], ["360", "360p"], ["audio", TXT.audio]]
        .forEach(([v, l]) => add(l, "", v === "best" ? {} : { quality: v }));
      menu.style.display = "block";
    });
  }, true);
  for (const t of ["mousedown", "mouseup", "pointerdown", "pointerup", "dblclick"]) wrap.addEventListener(t, (e) => e.stopPropagation(), true);
})();
