const ar = /^ar/i.test(navigator.language || "");
const T = ar ? {
  catchFiles: "التقط تحميلات الملفات تلقائيا", on: "PyDM شغّال", off: "PyDM مش شغّال. هيتفتح لما تبعت", grabPage: "حمّل فيديو الصفحة دي",
  found: "اتلقط من الصفحة", none: "لسه مفيش فيديو اتلقط. شغّل الفيديو وهيظهر هنا.",
  download: "تحميل", open: "افتح PyDM", sent: "اتبعت لـ PyDM", wake: "بيفتح PyDM…", bad: "ماتبعتش. جرّب تاني",
  hls: "بث HLS", dash: "بث DASH", file: "ملف", audio: "صوت",
} : {
  catchFiles: "Catch file downloads automatically", on: "PyDM is running", off: "PyDM isn't running. It opens when you send", grabPage: "Download this page's video",
  found: "Caught on this page", none: "No video caught yet. Play the video and it shows up here.",
  download: "Download", open: "Open PyDM", sent: "Sent to PyDM", wake: "Opening PyDM…", bad: "Couldn't send. Try again",
  hls: "HLS stream", dash: "DASH stream", file: "File", audio: "Audio",
};
if (ar) { document.documentElement.lang = "ar"; document.documentElement.dir = "rtl"; }
const $ = (id) => document.getElementById(id);
const ask = (m) => new Promise((res) => chrome.runtime.sendMessage(m, (r) => res(chrome.runtime.lastError ? null : r)));
let tabId = null;

function toast(msg, bad) {
  const t = $("toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
  setTimeout(() => (t.hidden = true), 2200);
}
const size = (n) => { if (!n) return ""; const u = ["B", "KB", "MB", "GB"]; let i = 0; while (n >= 1024 && i < 3) { n /= 1024; i++; } return (i ? n.toFixed(1) : n) + " " + u[i]; };
const short = (u) => { try { const x = new URL(u); return x.hostname + x.pathname; } catch (e) { return u; } };

async function sent(res) {
  if (res && res.ok) toast(T.sent);
  else if (res && res.launched) toast(T.wake);
  else toast(T.bad, true);
}

(async () => {
  $("catchLabel").textContent = T.catchFiles;
  const st0 = await chrome.storage.local.get("autoCatch");
  $("autoCatch").checked = st0.autoCatch !== false;
  $("autoCatch").onchange = (e) => chrome.storage.local.set({ autoCatch: e.target.checked });
  $("grabPage").textContent = T.grabPage; $("open").textContent = T.open;
  $("foundTitle").textContent = T.found; $("none").textContent = T.none;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  tabId = tab.id;
  const data = await ask({ type: "list", tabId });
  $("pageTitle").textContent = (data && data.title) || tab.title || "";
  const st = $("state");
  st.className = data && data.server ? "on" : "off"; st.textContent = data && data.server ? T.on : T.off;

  const items = (data && data.items) || [];
  $("found").hidden = !items.length; $("none").hidden = !!items.length;
  $("items").innerHTML = "";
  for (const it of items) {
    const li = document.createElement("li");
    li.innerHTML = `<div class="t"><span class="n"></span><div class="m"><span class="tag"></span><span class="sz"></span></div></div><button type="button"></button>`;
    li.querySelector(".n").textContent = short(it.url);
    li.querySelector(".n").title = it.url;
    li.querySelector(".tag").textContent = T[it.kind] || it.kind;
    li.querySelector(".sz").textContent = size(it.size);
    const b = li.querySelector("button"); b.textContent = T.download;
    b.onclick = async () => sent(await ask({ type: "send", tabId, item: it }));
    $("items").appendChild(li);
  }
  $("grabPage").onclick = async () => sent(await ask({ type: "send", tabId, item: { url: tab.url, kind: "page" } }));
  $("open").onclick = async () => { await ask({ type: "show" }); window.close(); };
})();
