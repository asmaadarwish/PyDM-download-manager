/* PyDM Video Catcher: background worker.
   - watches network responses for video / audio / streaming playlists, per tab
   - hands the best one (with the browser's cookies + referer) to the PyDM app */

const PORT_BASE = 47321, PORT_TRIES = 10;
const MAX_PER_TAB = 30;

/* ------------------------------------------------------------ detection */
const FILE_EXT = /\.(mp4|m4v|webm|mkv|mov|flv|mp3|m4a|ogg|opus|wav)(?:$|[?#])/i;
const MANIFEST_EXT = /\.(m3u8|mpd)(?:$|[?#])/i;
const SEGMENT = /\.(ts|m4s|cmfv|cmfa|aac)(?:$|[?#])|[\/_-](seg(ment)?|chunk|frag(ment)?)[-_]?\d+/i;
const MANIFEST_CT = /mpegurl|dash\+xml/i;

function header(h, name) {
  const x = (h || []).find((i) => i.name.toLowerCase() === name);
  return x ? x.value || "" : "";
}

function classify(url, ct, total) {
  const path = url.split("?")[0];
  if (MANIFEST_CT.test(ct) || MANIFEST_EXT.test(url)) {
    return /\.mpd(?:$|[?#])/i.test(url) || /dash/i.test(ct) ? "dash" : "hls";
  }
  if (SEGMENT.test(url) || /mp2t|iso\.segment/i.test(ct)) return null;
  const isMedia = /^(video|audio)\//i.test(ct) || FILE_EXT.test(url) || FILE_EXT.test(path);
  if (!isMedia) return null;
  if (total && total < 150 * 1024) return null;               // tracking pixels, tiny ranges
  return /^audio\//i.test(ct) ? "audio" : "file";
}

/* ---------------------------------------------------------- per-tab store */
const mem = new Map();                    // tabId -> array of items
const queue = new Map();                  // tabId -> promise chain (serialises storage writes)

async function load(tabId) {
  if (mem.has(tabId)) return mem.get(tabId);
  let list = [];
  try { list = (await chrome.storage.session.get("t" + tabId))["t" + tabId] || []; } catch (e) { /* no session storage */ }
  mem.set(tabId, list);
  return list;
}
function persist(tabId) {
  try { chrome.storage.session.set({ ["t" + tabId]: mem.get(tabId) || [] }); } catch (e) { /* ignore */ }
}
function badge(tabId) {
  const n = (mem.get(tabId) || []).length;
  chrome.action.setBadgeText({ tabId, text: n ? String(n) : "" }).catch(() => {});
  if (n) chrome.action.setBadgeBackgroundColor({ tabId, color: "#0A7F72" }).catch(() => {});
}
function withTab(tabId, fn) {
  const next = (queue.get(tabId) || Promise.resolve()).then(async () => { await load(tabId); fn(mem.get(tabId)); persist(tabId); badge(tabId); });
  queue.set(tabId, next.catch(() => {}));
  return next;
}

chrome.webRequest.onResponseStarted.addListener((d) => {
  if (d.tabId < 0 || d.statusCode >= 400 || d.method !== "GET") return;
  const ct = header(d.responseHeaders, "content-type");
  const range = header(d.responseHeaders, "content-range");
  const total = range ? Number(range.split("/")[1]) || 0 : Number(header(d.responseHeaders, "content-length")) || 0;
  const kind = classify(d.url, ct, total);
  if (!kind) return;
  withTab(d.tabId, (list) => {
    const key = kind === "file" || kind === "audio" ? d.url.split("?")[0] : d.url;
    const prev = list.findIndex((i) => i.key === key);
    const item = { key, url: d.url, kind, size: total || (prev >= 0 ? list[prev].size : 0), time: Date.now(), frame: d.frameId, ct };
    if (prev >= 0) list.splice(prev, 1);
    list.push(item);
    if (list.length > MAX_PER_TAB) list.shift();
  });
}, { urls: ["<all_urls>"], types: ["media", "xmlhttprequest", "other", "object"] }, ["responseHeaders"]);

chrome.webNavigation.onCommitted.addListener((d) => {
  if (d.frameId !== 0) return;
  mem.set(d.tabId, []); persist(d.tabId); badge(d.tabId);
});
chrome.tabs.onRemoved.addListener((tabId) => { mem.delete(tabId); chrome.storage.session.remove("t" + tabId).catch(() => {}); });

/* choose what to download when the user does not pick */
function best(list) {
  const files = list.filter((i) => i.kind === "file").sort((a, b) => b.size - a.size);
  if (files[0] && files[0].size >= 1024 * 1024) return files[0];
  const streams = list.filter((i) => i.kind === "hls" || i.kind === "dash").sort((a, b) => b.time - a.time);
  return streams[0] || files[0] || list.filter((i) => i.kind === "audio").pop() || null;
}

/* --------------------------------------------------------------- PyDM link */
async function readConfig() {
  try { return await (await fetch(chrome.runtime.getURL("config.json"), { cache: "no-store" })).json(); }
  catch (e) { return {}; }
}
async function findServer() {
  const cfg = await readConfig();
  const ports = [cfg.port, ...Array.from({ length: PORT_TRIES }, (_, i) => PORT_BASE + i)].filter((p, i, a) => p && a.indexOf(p) === i);
  for (const port of ports) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/api/ping`, { cache: "no-store" });
      const j = await r.json();
      if (j && j.app === "pydm") return { port, token: cfg.token || "" };
    } catch (e) { /* try next */ }
  }
  return null;
}
async function callServer(path, body) {
  const s = await findServer();
  if (!s) throw new Error("offline");
  const r = await fetch(`http://127.0.0.1:${s.port}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-PyDM-Token": s.token }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

async function cookiesFor(urls) {
  const seen = new Map();
  for (const u of urls.filter(Boolean)) {
    try {
      for (const c of await chrome.cookies.getAll({ url: u })) seen.set(c.domain + "|" + c.path + "|" + c.name, c);
    } catch (e) { /* invalid url */ }
  }
  return Array.from(seen.values()).slice(0, 300).map((c) => ({
    name: c.name, value: c.value, domain: c.domain, path: c.path, secure: c.secure, httpOnly: c.httpOnly, expires: c.expirationDate || 0,
  }));
}

function cleanTitle(t) {
  return String(t || "").replace(/\s+/g, " ").replace(/^\(\d+\)\s*/, "").trim().slice(0, 180);
}

/* send one thing to PyDM. what = {url, kind: file|hls|dash|audio|page} */
async function send(tabId, what) {
  const tab = await chrome.tabs.get(tabId);
  const pageUrl = tab.url || "";
  const isStream = what.kind === "hls" || what.kind === "dash";
  const spec = {
    url: what.url,
    kind: what.kind === "page" ? "auto" : isStream ? "media" : "file",
    page_url: pageUrl,
    referer: pageUrl,
    origin: (() => { try { return new URL(pageUrl).origin; } catch (e) { return ""; } })(),
    user_agent: navigator.userAgent,
    title: cleanTitle(tab.title),
    cookies: await cookiesFor([what.url, pageUrl]),
  };
  if (what.quality) spec.quality = what.quality;
  try {
    const r = await callServer("/api/add", { items: [spec] });
    return { ok: true, added: r.added };
  } catch (e) {
    // PyDM isn't running: wake it with the pydm:// link (no cookies, best effort)
    const link = `pydm://add?url=${encodeURIComponent(what.url)}&title=${encodeURIComponent(spec.title)}&kind=${spec.kind}`;
    const t = await chrome.tabs.create({ url: link, active: false });
    setTimeout(() => chrome.tabs.remove(t.id).catch(() => {}), 2500);
    return { ok: false, launched: true };
  }
}

/* what a click on the in-page button should do */
async function grab(tabId, hint, opts = {}) {
  const list = await load(tabId);
  let pick = opts.itemUrl ? list.find((i) => i.url === opts.itemUrl) : null;
  if (!pick && opts.quality) {                       // a quality was chosen: let PyDM pick that stream from the page
    const tab = await chrome.tabs.get(tabId);
    pick = { url: tab.url, kind: "page", quality: opts.quality };
  }
  pick = pick || best(list);
  if (!pick && hint && /^https?:/i.test(hint)) pick = { url: hint, kind: FILE_EXT.test(hint) ? "file" : MANIFEST_EXT.test(hint) ? "hls" : "page" };
  if (!pick) {
    const tab = await chrome.tabs.get(tabId);
    pick = { url: tab.url, kind: "page" };
  }
  const res = await send(tabId, pick);
  return Object.assign(res, { picked: pick.kind });
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    const tabId = msg.tabId ?? (sender.tab && sender.tab.id);
    if (msg.type === "grab") return reply(await grab(tabId, msg.src, { quality: msg.quality, itemUrl: msg.itemUrl }));
    if (msg.type === "send") return reply(await send(tabId, msg.item));
    if (msg.type === "list") {
      const tab = await chrome.tabs.get(tabId);
      return reply({ items: (await load(tabId)).slice().reverse(), title: cleanTitle(tab.title), url: tab.url, server: !!(await findServer()) });
    }
    if (msg.type === "status") return reply({ server: !!(await findServer()) });
    if (msg.type === "show") { await callServer("/api/show", {}).catch(() => {}); return reply({ ok: true }); }
    reply(null);
  })().catch((e) => reply({ ok: false, error: String(e && e.message || e) }));
  return true;
});


/* ---------------------------------------------------- catch normal file downloads */
async function autoCatchOn() {
  try { const v = (await chrome.storage.local.get("autoCatch")).autoCatch; return v !== false; } catch (e) { return true; }
}
const handled = new Set();
chrome.downloads.onCreated.addListener(async (item) => {
  try {
    if (handled.has(item.id)) return;
    const url = item.finalUrl || item.url || "";
    if (!/^https?:/i.test(url) || item.byExtensionId) return;          // blob:, data:, file: and other extensions' downloads stay in the browser
    if (item.fileSize > 0 && item.fileSize < 100 * 1024) return;       // tiny files: not worth handing over
    if (!(await autoCatchOn())) return;
    if (!(await findServer())) return;                                 // PyDM isn't running: let the browser do it
    handled.add(item.id);
    const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    const pageUrl = item.referrer || (tabs[0] && tabs[0].url) || "";
    const spec = {
      url, kind: "file", filename: (item.filename || "").split(/[\\/]/).pop(), page_url: pageUrl, referer: pageUrl,
      origin: (() => { try { return new URL(pageUrl).origin; } catch (e) { return ""; } })(),
      user_agent: navigator.userAgent, cookies: await cookiesFor([url, pageUrl]),
    };
    const r = await callServer("/api/add", { items: [spec] });
    if (r && r.added && r.added.length) {
      await chrome.downloads.cancel(item.id).catch(() => {});
      await chrome.downloads.erase({ id: item.id }).catch(() => {});
    }
  } catch (e) { /* on any failure the browser keeps the download */ }
});
