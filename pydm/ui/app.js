/* PyDM interface. Talks to the local server (same origin) with a per-run token. */
(function () {
  "use strict";

  /* ------------------------------------------------------------ helpers */
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };

  const ICONS = {
    link: '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    download: '<path d="M12 4v11"/><path d="m7 11 5 5 5-5"/><path d="M5 20h14"/>',
    plug: '<path d="M9 2v6M15 2v6"/><path d="M6 8h12v4a6 6 0 0 1-12 0z"/><path d="M12 18v4"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    play: '<path d="M7 4.5v15l12-7.5z"/>',
    retry: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    open: '<path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    trash: '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    sliders: '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    Videos: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m10 9.5 5 2.5-5 2.5z"/>',
    Music: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    Documents: '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/>',
    Images: '<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="m4 18 5-5 4 4 3-3 4 4"/>',
    Compressed: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M12 3v6M10 11h4M10 15h4"/>',
    Programs: '<rect x="4" y="4" width="16" height="16" rx="4"/><path d="M9 12h6M12 9v6"/>',
    Design: '<path d="M12 3 3 8l9 5 9-5z"/><path d="m3 13 9 5 9-5"/>',
    General: '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/>',
  };
  const icon = (n) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ICONS.General}</svg>`;

  /* --------------------------------------------------------------- i18n */
  const L = {
    en: {
      dir: "ltr", lang: "EN",
      placeholder: "Paste a link: a video, a page with a video, or any file",
      go: "Download",
      hint: "PyDM looks inside the page for the video. You can also drop links anywhere in this window.",
      startNow: "Start right away",
      all: "All", active: "In progress", done: "Finished",
      startQueue: "Start queue", stopQueue: "Stop queue", schedule: "Schedule", cancelSchedule: "Cancel schedule",
      clear: "Clear finished", startsAt: "Starts at",
      emptyTitle: "Paste a link to start",
      emptyBody: "Copy a video link, or the address of a page that has a video, and paste it above. Downloads show up here.",
      emptyExt: "Catch videos from my browser", emptyFolder: "Open downloads folder",
      drop: "Drop the link to download it",
      pause: "Pause", resume: "Resume", retry: "Try again", open: "Open", folder: "Show in folder", remove: "Remove",
      removeOnly: "Remove from list", removeFile: "Also delete file", cancel: "Cancel", keep: "Keep",
      st_queued: "Waiting for a free slot", st_probing: "Looking for the video…", st_converting: "Making it play everywhere…",
      st_paused: "Paused", st_completed: "Saved", st_error: "Failed", left: "left",
      noneHere: "Nothing here yet.",
      added1: "Added. Looking for the video…", addedN: (n) => `${n} links added`,
      noLink: "That doesn't look like a link. Paste a web address that starts with http.",
      offline: "Lost connection to PyDM. Reopen it from the Start menu.",
      settings: "Settings", language: "Language", theme: "Theme", auto: "Automatic", light: "Light", dark: "Dark",
      langAuto: "Automatic", folderLabel: "Save downloads to", change: "Change",
      concurrent: "Downloads at once", concurrentHelp: "More run in parallel, the rest wait",
      connections: "Connections per file", connectionsHelp: "Splits each file into parts to go faster",
      quality: "Default video quality", best: "Best quality", audio: "Audio only",
      autostart: "Start with Windows", autostartHelp: "Runs quietly so the browser extension always works",
      engine: "Video engine", engineHelp: (v) => (v ? `Version ${v}` : "Not installed"), update: "Update",
      updating: "Updating…", updated: (v) => `Video engine updated to ${v}`, updateFail: "Couldn't update. Check your internet connection.",
      extension: "Browser extension", extensionHelp: "Catch videos that have no direct link", setup: "Set up",
      quit: "Quit PyDM", quitHelp: "Unfinished downloads pause and continue next time", quitBtn: "Quit",
      schedTitle: "Start downloads later", schedBody: "Pick a time. PyDM starts the waiting downloads then, if it's still running.",
      schedSet: "Schedule", scheduled: (t) => `Queue starts at ${t}`,
      extTitle: "Add the browser extension",
      extIntro: "It adds a Download button on any page with a video, even when the video has no link you can copy, like course players you're signed in to.",
      ext1: "Open the extensions page", ext1b: "In Chrome or Edge, paste this into the address bar:",
      ext2: "Turn on Developer mode", ext2b: "It's the switch at the top of that page.",
      ext3: "Click Load unpacked and pick this folder", ext3b: "",
      ext4: "Pin PyDM to the toolbar", ext4b: "Click the puzzle icon, then the pin next to PyDM.",
      extNote: "Chrome shows a Developer mode notice for extensions installed this way. That is normal.",
      copy: "Copy", copied: "Copied", openFolder: "Open folder",
      credit: "Created by Asmaa Darwish - Content Me",
      errors: {},
    },
    ar: {
      dir: "rtl", lang: "ع",
      placeholder: "الصق لينك فيديو أو صفحة فيها فيديو أو أي ملف",
      go: "تحميل",
      hint: "PyDM بيدور جوه الصفحة على الفيديو. وتقدر كمان تسحب أي لينك وتسيبه على الشاشة.",
      startNow: "ابدأ فورا",
      all: "الكل", active: "شغّال", done: "خلصان",
      startQueue: "ابدأ الطابور", stopQueue: "وقّف الطابور", schedule: "جدولة", cancelSchedule: "إلغاء الجدولة",
      clear: "امسح الخلصان", startsAt: "هيبدأ الساعة",
      emptyTitle: "الصق لينك عشان تبدأ",
      emptyBody: "انسخ لينك فيديو أو عنوان صفحة فيها فيديو والصقه فوق. التحميلات هتظهر هنا.",
      emptyExt: "التقط الفيديوهات من المتصفح", emptyFolder: "افتح فولدر التحميلات",
      drop: "سيب اللينك هنا عشان يتحمّل",
      pause: "إيقاف مؤقت", resume: "كمّل", retry: "جرّب تاني", open: "افتح", folder: "أظهر في الفولدر", remove: "احذف",
      removeOnly: "احذف من القائمة", removeFile: "واحذف الملف كمان", cancel: "إلغاء", keep: "سيبه",
      st_queued: "مستني دوره", st_probing: "بيدوّر على الفيديو…", st_converting: "بيجهّز الفيديو يشتغل على أي جهاز…",
      st_paused: "واقف مؤقتا", st_completed: "اتحفظ", st_error: "فشل", left: "متبقي",
      noneHere: "مفيش حاجة هنا لسه.",
      added1: "اتضاف. بيدوّر على الفيديو…", addedN: (n) => `اتضاف ${n} لينكات`,
      noLink: "ده مش شكل لينك. الصق عنوان بيبدأ بـ http.",
      offline: "الاتصال بـ PyDM اتقطع. افتحه تاني من قائمة ابدأ.",
      settings: "الإعدادات", language: "اللغة", theme: "المظهر", auto: "تلقائي", light: "فاتح", dark: "داكن",
      langAuto: "تلقائي", folderLabel: "مكان حفظ التحميلات", change: "تغيير",
      concurrent: "عدد التحميلات مع بعض", concurrentHelp: "اللي فوق العدد ده بيستنى",
      connections: "عدد الاتصالات للملف", connectionsHelp: "بيقسّم الملف أجزاء عشان يسرّع",
      quality: "جودة الفيديو الافتراضية", best: "أعلى جودة", audio: "صوت فقط",
      autostart: "شغّله مع الويندوز", autostartHelp: "بيشتغل بهدوء عشان إضافة المتصفح تشتغل دايما",
      engine: "محرك الفيديو", engineHelp: (v) => (v ? `الإصدار ${v}` : "مش متسطّب"), update: "تحديث",
      updating: "بيحدّث…", updated: (v) => `محرك الفيديو اتحدّث لـ ${v}`, updateFail: "التحديث ماتمّش. اتأكد من الإنترنت.",
      extension: "إضافة المتصفح", extensionHelp: "بتلقط الفيديوهات اللي ملهاش لينك مباشر", setup: "إعداد",
      quit: "إغلاق PyDM", quitHelp: "التحميلات الناقصة بتقف وتكمّل المرة الجاية", quitBtn: "إغلاق",
      schedTitle: "ابدأ التحميل بعدين", schedBody: "اختار وقت. PyDM هيبدأ التحميلات المستنية وقتها لو لسه شغّال.",
      schedSet: "جدولة", scheduled: (t) => `الطابور هيبدأ الساعة ${t}`,
      extTitle: "ضيف إضافة المتصفح",
      extIntro: "بتحط زرار تحميل على أي صفحة فيها فيديو، حتى لو الفيديو ملهوش لينك تنسخه، زي مشغّلات الكورسات اللي أنتي مسجّلة دخول فيها.",
      ext1: "افتح صفحة الإضافات", ext1b: "في Chrome أو Edge الصق ده في شريط العنوان:",
      ext2: "فعّل وضع المطوّر (Developer mode)", ext2b: "هو المفتاح اللي في أعلى الصفحة دي.",
      ext3: "اضغط Load unpacked واختار الفولدر ده", ext3b: "",
      ext4: "ثبّت PyDM في الشريط", ext4b: "اضغط على أيقونة القطعة، وبعدين دبّوس جنب PyDM.",
      extNote: "Chrome بيظهر تنبيه وضع المطوّر للإضافات اللي بتتثبّت بالشكل ده. ده طبيعي.",
      copy: "نسخ", copied: "اتنسخ", openFolder: "افتح الفولدر",
      credit: "Created by Asmaa Darwish - Content Me",
      errors: {
        "No downloadable video found at this link": "مالقيناش فيديو يتحمّل في اللينك ده",
        "This video needs a signed-in account": "الفيديو ده محتاج تسجيل دخول (خاص أو بحدّ عمري أو حماية). جرّب إضافة المتصفح",
        "This video is DRM-protected": "الفيديو ده محمي بحقوق نشر (DRM) ومينفعش يتحمّل",
        "This video is private": "الفيديو ده خاص",
        "This video is not available": "الفيديو ده مش متاح",
        "Could not reach the site": "مقدرناش نوصل للموقع. اتأكد من الإنترنت",
        "Connection failed": "الاتصال فشل",
        "Download incomplete": "التحميل ماكملش",
        "Video engine (yt-dlp) is missing": "محرك الفيديو ناقص. أعد تسطيب PyDM",
        "Unsupported URL": "اللينك ده مش مدعوم",
      },
    },
  };

  /* ------------------------------------------------------------ globals */
  const API = { token: (window.PYDM && window.PYDM.token) || "" };
  let S = null;                       // last state from server
  let lang = "en", T = L.en;
  let filter = "all";
  let confirming = null;              // row id with the inline remove-confirm open
  let failures = 0, offlineShown = false;
  const rows = new Map();             // id -> {el, sig, actSig}
  const history = [];                 // sparkline samples
  let firstRender = true;

  async function api(path, body) {
    const opts = { headers: { "X-PyDM-Token": API.token } };
    if (body !== undefined) {
      opts.method = "POST";
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  /* ----------------------------------------------------- lang and theme */
  function resolveLang(pref) {
    if (pref === "ar" || pref === "en") return pref;
    return (navigator.language || "en").toLowerCase().startsWith("ar") ? "ar" : "en";
  }
  function resolveTheme(pref) {
    if (pref === "light" || pref === "dark") return pref;
    return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function applyTheme(pref) {
    const th = resolveTheme(pref);
    document.documentElement.dataset.theme = th;
    store.set("pydm.theme", pref || "auto");
    $("themeBtn").innerHTML = icon(th === "dark" ? "sun" : "moon");
  }
  function applyLang(pref) {
    lang = resolveLang(pref);
    T = L[lang];
    store.set("pydm.lang", pref || "auto");
    const h = document.documentElement;
    h.lang = lang; h.dir = T.dir;
    $("linkInput").placeholder = T.placeholder;
    $("goLabel").textContent = T.go;
    $("pasteHint").textContent = T.hint;
    $("startNowLabel").textContent = T.startNow;
    $("emptyTitle").textContent = T.emptyTitle;
    $("emptyBody").textContent = T.emptyBody;
    $("emptyExtLabel").textContent = T.emptyExt;
    $("emptyFolder").textContent = T.emptyFolder;
    $("dropText").textContent = T.drop;
    $("setTitle").textContent = T.settings;
    $("schedTitle").textContent = T.schedTitle;
    $("schedBody").textContent = T.schedBody;
    $("schedCancel").textContent = T.cancel;
    $("schedSet").textContent = T.schedSet;
    $("extTitle").textContent = T.extTitle;
    $("langBtn").innerHTML = `<span class="lbl">${L[lang === "ar" ? "en" : "ar"].lang}</span>`;
    $("langBtn").title = lang === "ar" ? "English" : "العربية";
    $("settingsBtn").title = T.settings;
    $("settingsBtn").innerHTML = icon("sliders");
    $("credit").textContent = T.credit;
    buildQuality();
    // rows carry translated text; force a rebuild
    rows.forEach((r) => { r.sig = r.actSig = null; });
    if (S) render();
  }
  function buildQuality() {
    const sel = $("qualitySel"), cur = sel.value || (S && S.settings.quality) || "best";
    const opts = [["best", T.best], ["1080", "1080p"], ["720", "720p"], ["480", "480p"], ["360", "360p"], ["audio", T.audio]];
    sel.innerHTML = opts.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
    sel.value = cur;
  }

  /* ----------------------------------------------------------- formatting */
  function fmtSize(n) {
    if (!n || n < 0) return "";
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i === 0 ? n.toFixed(0) : n >= 100 ? n.toFixed(0) : n.toFixed(1)) + " " + u[i];
  }
  function fmtTime(s) {
    s = Math.max(0, Math.round(s));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    const p = (v) => String(v).padStart(2, "0");
    return h ? `${h}:${p(m)}:${p(x)}` : `${m}:${p(x)}`;
  }
  function errText(msg) {
    msg = msg || "";
    const map = T.errors;
    for (const k in map) if (msg.startsWith(k)) return map[k];
    return msg;
  }
  const bdi = (s) => `<bdi>${esc(s)}</bdi>`;

  /* -------------------------------------------------------------- toasts */
  function toast(msg, bad) {
    const el = document.createElement("div");
    el.className = "toast" + (bad ? " bad" : "");
    el.textContent = msg;
    $("toasts").appendChild(el);
    setTimeout(() => { el.style.transition = "opacity .3s"; el.style.opacity = "0"; setTimeout(() => el.remove(), 320); }, bad ? 5200 : 2800);
  }

  /* ---------------------------------------------------------------- rows */
  function isRunning(st) { return st === "downloading" || st === "probing" || st === "converting"; }

  function actionsHTML(it, confirm) {
    const b = (act, ic, label, cls) =>
      `<button type="button" class="act ${cls || ""}" data-act="${act}" title="${esc(label)}" aria-label="${esc(label)}">${icon(ic)}${cls && cls.includes("main") ? `<span>${esc(label)}</span>` : ""}</button>`;
    if (confirm) {
      const del = it.status === "completed" ? `<button type="button" class="go" data-act="remove-file">${esc(T.removeFile)}</button>` : "";
      return `<div class="confirm"><button type="button" data-act="remove-list" class="${del ? "" : "go"}">${esc(del ? T.removeOnly : T.remove)}</button>${del}<button type="button" data-act="cancel">${esc(T.keep)}</button></div>`;
    }
    let out = "";
    if (isRunning(it.status) || it.status === "queued") out += b("pause", "pause", T.pause);
    else if (it.status === "paused") out += b("resume", "play", T.resume, "main");
    else if (it.status === "error") out += b("retry", "retry", T.retry, "main");
    else if (it.status === "completed") out += b("open", "open", T.open, "main") + b("folder", "folder", T.folder);
    out += b("remove", "trash", T.remove, "warn");
    return out;
  }

  function figuresHTML(it) {
    const pct = it.size > 0 ? Math.min(100, Math.floor((it.done / it.size) * 100)) : 0;
    let big = "", small = "", cls = "";
    switch (it.status) {
      case "completed": big = `<span class="pct done">${icon("check")}</span>`; small = `<div class="rate">${bdi(fmtSize(it.size || it.done))}</div>`; break;
      case "error": big = `<div class="pct bad">${esc(T.st_error)}</div>`; small = `<div class="rate err">${esc(errText(it.error))}</div>`; break;
      case "downloading": {
        big = `<div class="pct">${it.size > 0 ? bdi(pct + "%") : "…"}</div>`;
        const parts = [];
        if (it.speed > 1) parts.push(bdi(fmtSize(it.speed) + "/s"));
        if (it.eta) parts.push(`${bdi(fmtTime(it.eta))} ${esc(T.left)}`);
        small = `<div class="rate">${parts.join(" · ")}</div>`;
        break;
      }
      case "paused": big = `<div class="pct">${it.size > 0 ? bdi(pct + "%") : ""}</div>`; small = `<div class="rate">${esc(T.st_paused)}</div>`; break;
      default: small = `<div class="rate">${esc(T["st_" + it.status] || it.status)}</div>`; cls = "wide";
    }
    return big + small;
  }

  function metaHTML(it) {
    const bits = [];
    if (it.host) bits.push(`<span dir="ltr">${esc(it.host)}</span>`);
    if (it.status !== "completed" && it.size > 0) bits.push(`<span dir="ltr">${esc(fmtSize(it.done))} / ${esc(fmtSize(it.size))}</span>`);
    if (it.media && it.quality && it.quality !== "best" && it.quality !== "audio") bits.push(`<span dir="ltr">${esc(it.quality)}p</span>`);
    return bits.join("");
  }

  function makeRow(it) {
    const el = document.createElement("article");
    el.className = "row" + (firstRender ? "" : " new");
    el.dataset.id = it.id;
    el.innerHTML = '<div class="fill"></div><div class="glyph"></div><div><p class="title"></p><div class="meta"></div></div><div class="figures"></div><div class="actions"></div>';
    return { el, sig: null, actSig: null };
  }

  function updateRow(r, it) {
    const el = r.el;
    const pct = it.size > 0 ? (it.done / it.size) * 100 : 0;
    el.style.setProperty("--p", it.status === "converting" ? 100 : pct.toFixed(1));
    el.dataset.p = it.status === "converting" ? 100 : Math.floor(pct);
    el.dataset.status = it.status;
    el.dataset.cat = it.category;
    el.classList.toggle("settled", it.status === "completed");
    const sig = [it.name, it.url, it.category, it.status, it.size, Math.floor(it.done / 1024 / 64), Math.round(it.speed / 1024), it.error, it.host, it.quality, lang].join("|");
    if (sig !== r.sig) {
      r.sig = sig;
      el.querySelector(".glyph").innerHTML = icon(it.category);
      const title = el.querySelector(".title");
      title.textContent = it.name || it.url;
      title.title = it.name || it.url;
      el.querySelector(".meta").innerHTML = metaHTML(it);
      el.querySelector(".figures").innerHTML = figuresHTML(it);
    }
    const asig = it.status + "|" + (confirming === it.id) + "|" + lang;
    if (asig !== r.actSig) {
      r.actSig = asig;
      el.querySelector(".actions").innerHTML = actionsHTML(it, confirming === it.id);
    }
  }

  /* -------------------------------------------------------------- render */
  function render() {
    const items = (S.items || []).slice().sort((a, b) => (b.added || 0) - (a.added || 0));
    const doneN = items.filter((i) => i.status === "completed").length;
    const activeN = items.length - doneN;
    const shown = items.filter((i) => filter === "all" || (filter === "done" ? i.status === "completed" : i.status !== "completed"));

    // filters
    const f = $("filters");
    const tabs = [["all", T.all, items.length], ["active", T.active, activeN], ["done", T.done, doneN]];
    const fsig = tabs.map((t) => t.join(":")).join("|") + filter + lang;
    if (f.dataset.sig !== fsig) {
      f.dataset.sig = fsig;
      f.innerHTML = tabs.map(([k, l, n]) => `<button type="button" role="tab" data-f="${k}" aria-selected="${k === filter}">${esc(l)}<span class="n">${n}</span></button>`).join("");
    }

    // empty state vs list
    const none = items.length === 0;
    $("empty").hidden = !none;
    document.querySelector(".toolbar").hidden = none;
    $("list").hidden = none;

    // toolbar
    const q = S.queue || {};
    $("queueBtn").textContent = q.active ? T.stopQueue : T.startQueue;
    $("schedBtn").textContent = q.start_at ? T.cancelSchedule : T.schedule;
    const chip = $("schedChip");
    chip.hidden = !q.start_at;
    if (q.start_at) chip.textContent = `${T.startsAt} ${q.start_at.slice(11, 16)}`;
    $("clearBtn").hidden = doneN === 0;
    $("clearBtn").textContent = T.clear;

    // rows (keyed)
    const list = $("list");
    const keep = new Set();
    let prev = null;
    shown.forEach((it) => {
      keep.add(it.id);
      let r = rows.get(it.id);
      if (!r) { r = makeRow(it); rows.set(it.id, r); }
      updateRow(r, it);
      const want = prev ? prev.nextElementSibling : list.firstElementChild;
      if (r.el !== want) list.insertBefore(r.el, want);
      prev = r.el;
    });
    rows.forEach((r, id) => { if (!keep.has(id)) { r.el.remove(); rows.delete(id); } });
    let msg = list.querySelector(".nothing");
    if (!none && shown.length === 0) {
      if (!msg) { msg = document.createElement("p"); msg.className = "muted nothing"; msg.style.cssText = "text-align:center;padding:36px 0"; list.appendChild(msg); }
      msg.textContent = T.noneHere;
    } else if (msg) msg.remove();

    // speed chip + sparkline
    const sp = S.speed || 0;
    history.push(sp);
    if (history.length > 30) history.shift();
    const chipEl = $("speed");
    chipEl.hidden = sp < 1;
    if (sp >= 1) {
      $("speedText").textContent = fmtSize(sp) + "/s";
      const max = Math.max(...history, 1);
      $("spark").firstElementChild.setAttribute("points",
        history.map((v, i) => `${((i / 29) * 70 + 1).toFixed(1)},${(20 - (v / max) * 18).toFixed(1)}`).join(" "));
    }
    firstRender = false;
  }

  /* ---------------------------------------------------------------- poll */
  async function poll() {
    try {
      const st = await api("/api/state");
      failures = 0; offlineShown = false;
      const first = !S;
      S = st;
      if (first || st.settings.language !== store.get("pydm.lang")) applyLang(st.settings.language);
      if (first || st.settings.theme !== store.get("pydm.theme")) applyTheme(st.settings.theme);
      if (first) $("qualitySel").value = st.settings.quality || "best";
      render();
      if ($("settingsDlg").open) fillSettings(false);
    } catch (e) {
      failures++;
      if (failures >= 4 && !offlineShown) { offlineShown = true; toast(T.offline, true); }
    }
    setTimeout(poll, document.hidden ? 2500 : 700);
  }

  /* ----------------------------------------------------------- add links */
  function extractUrls(text) {
    const found = String(text || "").match(/https?:\/\/[^\s"'<>]+/gi) || [];
    return Array.from(new Set(found.map((u) => u.replace(/[),.;]+$/, ""))));
  }
  async function addLinks(urls) {
    if (!urls.length) {
      $("pasteForm").classList.remove("shake"); void $("pasteForm").offsetWidth; $("pasteForm").classList.add("shake");
      toast(T.noLink, true);
      return false;
    }
    try {
      await api("/api/add", { urls, quality: $("qualitySel").value, start_now: $("startNow").checked });
      $("linkInput").value = "";
      toast(urls.length === 1 ? T.added1 : T.addedN(urls.length));
      filter = "all";
      poll_soon();
      return true;
    } catch (e) {
      toast(T.offline, true);
      return false;
    }
  }
  let soon = null;
  function poll_soon() { // refresh right away instead of waiting for the next tick
    clearTimeout(soon);
    soon = setTimeout(async () => { try { S = await api("/api/state"); render(); } catch (e) { /* next tick */ } }, 120);
  }

  /* ------------------------------------------------------------- dialogs */
  function copyText(text, btn) {
    const done = () => { const o = btn.textContent; btn.textContent = T.copied; setTimeout(() => (btn.textContent = o), 1400); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, () => fallback());
    else fallback();
    function fallback() {
      const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); done(); } catch (e) { /* ignore */ } ta.remove();
    }
  }

  function seg(name, current, options) {
    return `<div class="seg" data-seg="${name}">${options.map(([v, l]) => `<button type="button" data-v="${v}" aria-selected="${v === current}">${esc(l)}</button>`).join("")}</div>`;
  }
  function stepper(name, val) {
    return `<div class="stepper" data-step="${name}"><button type="button" data-d="-1" aria-label="-">−</button><output>${val}</output><button type="button" data-d="1" aria-label="+">+</button></div>`;
  }
  function fillSettings(force) {
    const s = S.settings, body = $("setBody");
    const sig = JSON.stringify([s, lang, S.engine]);
    if (!force && body.dataset.sig === sig) return;
    if (!force && body.contains(document.activeElement) && document.activeElement.tagName === "SELECT") return;
    body.dataset.sig = sig;
    const row = (lab, help, ctl) => `<div class="set-row"><div class="lab"><b>${esc(lab)}</b>${help ? `<small>${esc(help)}</small>` : ""}</div><div class="ctl">${ctl}</div></div>`;
    const q = [["best", T.best], ["1080", "1080p"], ["720", "720p"], ["480", "480p"], ["360", "360p"], ["audio", T.audio]];
    body.innerHTML =
      row(T.language, "", seg("language", s.language, [["auto", T.langAuto], ["ar", "العربية"], ["en", "English"]])) +
      row(T.theme, "", seg("theme", s.theme, [["auto", T.auto], ["light", T.light], ["dark", T.dark]])) +
      row(T.folderLabel, "", `<span class="path" title="${esc(s.root)}">${esc(s.root)}</span><button class="btn-ghost" data-do="browse" type="button">${esc(T.change)}</button>`) +
      row(T.concurrent, T.concurrentHelp, stepper("max_concurrent", s.max_concurrent)) +
      row(T.connections, T.connectionsHelp, stepper("connections", s.connections)) +
      row(T.quality, "", `<select class="select" data-sel="quality">${q.map(([v, l]) => `<option value="${v}"${v === s.quality ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`) +
      (S.windows ? row(T.autostart, T.autostartHelp, `<label class="switch"><input type="checkbox" data-chk="autostart"${s.autostart ? " checked" : ""}><span class="track" aria-hidden="true"></span></label>`) : "") +
      row(T.extension, T.extensionHelp, `<button class="btn-ghost" data-do="ext" type="button">${esc(T.setup)}</button>`) +
      row(T.engine, T.engineHelp(S.engine), `<button class="btn-ghost" data-do="engine" type="button">${esc(T.update)}</button>`) +
      row(T.quit, T.quitHelp, `<button class="btn-ghost danger" data-do="quit" type="button">${esc(T.quitBtn)}</button>`);
  }

  async function saveSetting(patch) {
    try {
      const r = await api("/api/settings", patch);
      S.settings = r.settings;
      if ("language" in patch) applyLang(S.settings.language);
      if ("theme" in patch) applyTheme(S.settings.theme);
      if ("quality" in patch) $("qualitySel").value = S.settings.quality;
      fillSettings(true);
    } catch (e) { toast(T.offline, true); }
  }

  function openExt() {
    const dir = S ? S.extension_dir : "";
    const box = (txt, extra) => `<div class="pathbox"><code>${esc(txt)}</code><button type="button" data-copy="${esc(txt)}">${esc(T.copy)}</button>${extra || ""}</div>`;
    $("extBody").innerHTML =
      `<p class="muted" style="margin:0 0 14px">${esc(T.extIntro)}</p><ol class="steps">` +
      `<li><b>${esc(T.ext1)}</b><p>${esc(T.ext1b)}</p>${box("chrome://extensions")}</li>` +
      `<li><b>${esc(T.ext2)}</b><p>${esc(T.ext2b)}</p></li>` +
      `<li><b>${esc(T.ext3)}</b>${box(dir, `<button type="button" data-do="extfolder">${esc(T.openFolder)}</button>`)}</li>` +
      `<li><b>${esc(T.ext4)}</b><p>${esc(T.ext4b)}</p></li></ol><p class="note">${esc(T.extNote)}</p>`;
    $("extDlg").showModal();
  }

  /* -------------------------------------------------------------- events */
  function bind() {
    document.querySelectorAll("[data-icon]").forEach((el) => { el.innerHTML = icon(el.dataset.icon); });

    $("pasteForm").addEventListener("submit", (e) => { e.preventDefault(); addLinks(extractUrls($("linkInput").value)); });
    // pasting a link straight into the box starts it: one step less
    $("linkInput").addEventListener("paste", (e) => {
      const text = (e.clipboardData || window.clipboardData).getData("text");
      const urls = extractUrls(text);
      if (urls.length) { e.preventDefault(); $("linkInput").value = urls.join(" "); addLinks(urls); }
    });
    // pasting anywhere else focuses the box and does the same
    document.addEventListener("paste", (e) => {
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
      if (document.querySelector("dialog[open]")) return;
      const urls = extractUrls((e.clipboardData || window.clipboardData).getData("text"));
      if (urls.length) { e.preventDefault(); addLinks(urls); }
    });

    // drag and drop links from the browser
    let depth = 0;
    const hasLink = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).some((t) => t === "text/uri-list" || t === "text/plain" || t === "text/html");
    document.addEventListener("dragenter", (e) => { if (hasLink(e)) { depth++; document.body.classList.add("dropping"); } });
    document.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) document.body.classList.remove("dropping"); });
    document.addEventListener("dragover", (e) => { if (hasLink(e)) e.preventDefault(); });
    document.addEventListener("drop", (e) => {
      e.preventDefault(); depth = 0; document.body.classList.remove("dropping");
      const dt = e.dataTransfer;
      addLinks(extractUrls((dt.getData("text/uri-list") || "") + " " + (dt.getData("text/plain") || "")));
    });

    $("filters").addEventListener("click", (e) => {
      const b = e.target.closest("[data-f]"); if (!b) return;
      filter = b.dataset.f; render();
    });
    $("queueBtn").addEventListener("click", async () => { try { await api("/api/queue", { action: S.queue.active ? "stop" : "start" }); poll_soon(); } catch (e) { /* tick */ } });
    $("schedBtn").addEventListener("click", async () => {
      if (S.queue.start_at) { await api("/api/schedule", { time: null }); toast(T.cancelSchedule); poll_soon(); }
      else $("schedDlg").showModal();
    });
    $("schedCancel").addEventListener("click", () => $("schedDlg").close());
    $("schedSet").addEventListener("click", async () => {
      const t = $("schedTime").value; if (!t) return;
      await api("/api/schedule", { time: t });
      $("schedDlg").close(); toast(T.scheduled(t)); poll_soon();
    });
    $("clearBtn").addEventListener("click", async () => { await api("/api/clear-finished", {}); poll_soon(); });

    // row actions (delegated)
    $("list").addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-act]"); if (!btn) return;
      const id = btn.closest(".row").dataset.id, act = btn.dataset.act;
      if (act === "remove") { confirming = id; render(); return; }
      if (act === "cancel") { confirming = null; render(); return; }
      if (act === "remove-list" || act === "remove-file") {
        confirming = null;
        await api("/api/item", { id, action: "remove", delete_files: act === "remove-file" });
      } else await api("/api/item", { id, action: act });
      poll_soon();
    });

    $("emptyExt").addEventListener("click", openExt);
    $("emptyFolder").addEventListener("click", () => api("/api/open-folder", {}));
    $("langBtn").addEventListener("click", () => saveSetting({ language: lang === "ar" ? "en" : "ar" }));
    $("themeBtn").addEventListener("click", () => saveSetting({ theme: document.documentElement.dataset.theme === "dark" ? "light" : "dark" }));
    $("settingsBtn").addEventListener("click", () => { if (S) { fillSettings(true); $("settingsDlg").showModal(); } });

    // settings dialog (delegated)
    $("setBody").addEventListener("click", async (e) => {
      const sg = e.target.closest("[data-seg] [data-v]");
      if (sg) return saveSetting({ [sg.parentElement.dataset.seg]: sg.dataset.v });
      const st = e.target.closest("[data-step] [data-d]");
      if (st) {
        const k = st.parentElement.dataset.step, lim = k === "connections" ? [1, 32] : [1, 10];
        return saveSetting({ [k]: Math.max(lim[0], Math.min(lim[1], S.settings[k] + Number(st.dataset.d))) });
      }
      const d = e.target.closest("[data-do]"); if (!d) return;
      if (d.dataset.do === "browse") { try { const r = await api("/api/browse", {}); if (r.path) saveSetting({ root: r.path }); } catch (err) { /* cancelled */ } }
      else if (d.dataset.do === "ext") { $("settingsDlg").close(); openExt(); }
      else if (d.dataset.do === "engine") {
        d.disabled = true; d.textContent = T.updating;
        try { const r = await api("/api/update-engine", {}); if (r.ok) toast(T.updated(r.version)); else toast(T.updateFail, true); } catch (err) { toast(T.updateFail, true); }
        fillSettings(true);
      } else if (d.dataset.do === "quit") { try { await api("/api/quit", {}); } catch (err) { /* closing */ } document.body.innerHTML = ""; window.close(); }
    });
    $("setBody").addEventListener("change", (e) => {
      const sel = e.target.closest("[data-sel]"); if (sel) return saveSetting({ [sel.dataset.sel]: sel.value });
      const c = e.target.closest("[data-chk]"); if (c) saveSetting({ [c.dataset.chk]: c.checked });
    });

    $("extBody").addEventListener("click", (e) => {
      const c = e.target.closest("[data-copy]");
      if (c) return copyText(c.dataset.copy, c);
      if (e.target.closest("[data-do='extfolder']")) api("/api/open-extension", {});
    });

    // click outside a dialog closes it
    document.querySelectorAll("dialog").forEach((dlg) => dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); }));

    // footer credit: open the site in the user's real browser, new tab, instantly
    $("credit").addEventListener("click", async (e) => {
      e.preventDefault();
      const url = $("credit").href;
      try { await api("/api/open-url", { url }); } catch (err) { window.open(url, "_blank", "noopener"); }
    });

    if (window.matchMedia) matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (S && S.settings.theme === "auto") applyTheme("auto"); });
  }

  /* ---------------------------------------------------------------- boot */
  applyTheme(store.get("pydm.theme") || "auto");
  bind();
  applyLang(store.get("pydm.lang") || "auto");
  poll();
  $("linkInput").focus();
})();
