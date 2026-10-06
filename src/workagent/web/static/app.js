/* Personal Work Agent — web UI (vanilla JS, no external resources).
 * CSP forbids inline styles, so geometry is passed in data-* attributes and applied by paint(). */
"use strict";
(() => {
  // ---------------------------------------------------------------- helpers
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pad = (n) => String(n).padStart(2, "0");
  const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const today = () => isoDate(new Date());
  const shiftDate = (iso, days) => { const d = new Date(iso + "T12:00:00"); d.setDate(d.getDate() + days); return isoDate(d); };
  const hm = (ts) => { const d = new Date(ts * 1000); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const fmtDur = (s) => { const m = Math.round((s || 0) / 60); if (m < 1) return `${Math.floor(s || 0)}s`; const h = Math.floor(m / 60); return h ? `${h}h ${pad(m % 60)}m` : `${m}m`; };
  const weekday = (iso) => ["CN", "T2", "T3", "T4", "T5", "T6", "T7"][new Date(iso + "T12:00:00").getDay()];

  const P = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    timeline: '<path d="M4 6h10M4 12h16M4 18h7"/>',
    tasks: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="m8 12 3 3 5-6"/>',
    bot: '<rect x="5" y="7" width="14" height="12" rx="3"/><path d="M12 3v4M9.5 12v.5M14.5 12v.5M9.5 16h5"/>',
    report: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
    settings: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    play: '<path d="M7 5v14l12-7z"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    eyeoff: '<path d="M3 3l18 18"/><path d="M10.6 6.1A9 9 0 0 1 12 6c5 0 9 6 9 6a17 17 0 0 1-2.6 3.2M6.6 6.6C4.3 8.1 3 12 3 12s4 6 9 6a9 9 0 0 0 4.4-1.1"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    left: '<path d="m15 18-6-6 6-6"/>',
    right: '<path d="m9 18 6-6-6-6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/>',
    download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
    send: '<path d="M4 12 20 4l-6 16-3-7z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    check: '<path d="m5 12 5 5 9-10"/>',
    alert: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17v.5"/>',
    block: '<circle cx="12" cy="12" r="9"/><path d="m6 6 12 12"/>',
    help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17v.5"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
    coffee: '<path d="M4 8h13v6a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z"/><path d="M17 10h2a2 2 0 0 1 0 4h-2M8 3v2M12 3v2"/>',
    shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    flag: '<path d="M5 21V4h11l-2 4 2 4H5"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3"/>',
    circle: '<circle cx="12" cy="12" r="8"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
  };
  const icon = (n, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[n] || ""}</svg>`;

  const CATS = ["development", "meeting", "research", "documents", "communication", "design", "browsing", "other", "private"];
  const CAT_VI = { development: "Lập trình", meeting: "Họp", research: "Tra cứu", documents: "Tài liệu", communication: "Trao đổi", design: "Thiết kế", browsing: "Duyệt web", other: "Khác", private: "Riêng tư", away: "Vắng mặt" };
  const catOf = (a) => a.kind === "private" ? "private" : (a.kind === "away" || a.kind === "locked") ? "away"
    : (CATS.includes(a.category) && a.category !== "private" ? a.category : "other");
  const isWork = (a) => a.kind === "active" || a.kind === "private";

  const STATUSES = [["todo", "Cần làm", "circle"], ["doing", "Đang làm", "play"], ["blocked", "Bị chặn", "block"], ["done", "Xong", "check"]];
  const SECS = [["progress", "Tiến độ hôm nay", "check"], ["issues", "Vấn đề phát hiện", "alert"], ["blocks", "Bị chặn", "block"], ["support", "Cần hỗ trợ", "help"], ["plan", "Kế hoạch ngày mai", "arrow"]];
  const NAV = [["dashboard", "grid", "Tổng quan"], ["timeline", "timeline", "Thời gian"], ["tasks", "tasks", "Công việc"], ["chat", "bot", "Trợ lý"], ["report", "report", "Báo cáo"], ["settings", "settings", "Cài đặt"]];

  const S = {
    token: null, st: null, view: "dashboard", date: today(), noToken: false, offline: false, switched: false,
    day: null, catOff: new Set(), filter: "", open: new Set(), tasks: null, tickets: [], jira: "",
    chat: [], busy: false, report: null, draft: null, text: "", editing: false, dirty: false, cfg: null, keySet: false,
  };

  // ---------------------------------------------------------------- api
  class ApiErr extends Error { constructor(status, data) { super(data && data.error || String(status)); this.status = status; this.data = data || {}; } }

  async function api(method, path, body) {
    const opt = { method, headers: { "X-WA-Token": S.token || "" } };
    if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    let r;
    try { r = await fetch(path, opt); } catch (e) { if (!S.offline) { S.offline = true; render(); } throw e; }
    const data = await r.json().catch(() => ({}));
    if (r.status === 401) { S.noToken = true; render(); throw new ApiErr(401, data); }
    if (r.status === 423) { refreshState(true); throw new ApiErr(423, data); }
    if (!r.ok) throw new ApiErr(r.status, data);
    return data;
  }

  // ---------------------------------------------------------------- ui primitives
  function paint(root) {
    $$("[data-l]", root).forEach((e) => { e.style.left = e.dataset.l + "%"; });
    $$("[data-w]", root).forEach((e) => { e.style.width = e.dataset.w + "%"; });
    $$("[data-g]", root).forEach((e) => { e.style.flexGrow = e.dataset.g; });
  }
  const tipAttrs = (head, sub, cat) => `data-th="${esc(head)}"${sub ? ` data-ts="${esc(sub)}"` : ""}${cat ? ` data-tc="${esc(cat)}"` : ""}`;

  function toast(msg, kind = "good") {
    const ic = { good: "check", critical: "alert", warning: "alert", info: "circle" }[kind] || "circle";
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.innerHTML = `${icon(ic)}<span>${esc(msg)}</span>`;
    $("#toasts").appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  function modal(html, onMount) {
    const ov = document.createElement("div");
    ov.className = "overlay";
    ov.innerHTML = `<div class="modal" role="dialog" aria-modal="true">${html}</div>`;
    document.body.appendChild(ov);
    const close = () => ov.remove();
    ov.addEventListener("mousedown", (e) => { if (e.target === ov) close(); });
    ov.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    onMount && onMount(ov, close);
    const first = $("input, textarea, button", ov);
    first && first.focus();
    return close;
  }

  function chip(text, cls = "", ic = "", extra = "") {
    return `<span class="chip ${cls}" ${extra}>${ic ? icon(ic) : ""}${esc(text)}</span>`;
  }
  const ticketChip = (t) => S.jira
    ? `<a class="chip ticket" href="${esc(S.jira.replace(/\/$/, "") + "/browse/" + encodeURIComponent(t))}" target="_blank" rel="noopener noreferrer">${esc(t)}</a>`
    : chip(t, "ticket");

  // ---------------------------------------------------------------- charts
  function strip(acts, dayStart) {
    const work = acts.filter(isWork);
    let t0 = dayStart + 8 * 3600, t1 = dayStart + 18 * 3600;
    if (work.length) {
      const first = Math.min(...work.map((a) => a.start)), last = Math.max(...work.map((a) => a.end));
      t0 = Math.max(dayStart, dayStart + Math.floor((first - dayStart) / 3600) * 3600);
      t1 = Math.min(dayStart + 86400, dayStart + Math.ceil((last - dayStart) / 3600) * 3600);
      if (t1 - t0 < 2 * 3600) t1 = Math.min(dayStart + 86400, t0 + 2 * 3600);
    }
    const span = t1 - t0;
    const segs = work.filter((a) => !S.catOff.has(catOf(a)) && a.end > t0 && a.start < t1).map((a) => {
      const c = catOf(a);
      const l = ((Math.max(a.start, t0) - t0) / span) * 100;
      const w = Math.max(0.2, ((Math.min(a.end, t1) - Math.max(a.start, t0)) / span) * 100);
      const sub = a.kind === "private" ? "Riêng tư — không ghi chi tiết" : `${a.app_name || a.app}${a.title ? " — " + a.title : ""}`;
      return `<div class="seg-a c-${c}" data-l="${l.toFixed(3)}" data-w="${w.toFixed(3)}" ${tipAttrs(`${hm(a.start)}–${hm(a.end)} · ${fmtDur(a.end - a.start)} · ${CAT_VI[c]}`, sub, c)}></div>`;
    }).join("");
    const hours = Math.round(span / 3600), step = hours > 12 ? 2 : 1;
    let ticks = "";
    for (let i = 0; i <= hours; i += step) {
      const cls = i === 0 ? "first" : i + step > hours ? "last" : "";
      ticks += `<span class="${cls}" data-l="${((i * 3600) / span) * 100}">${hm(t0 + i * 3600)}</span>`;
    }
    return `<div class="strip" role="img" aria-label="Dòng thời gian trong ngày">${segs}</div><div class="ticks">${ticks}</div>`;
  }

  function legend(cats, clickable) {
    return `<div class="legend">${cats.map((c) => `<span class="it c-${c} ${clickable ? "click" : ""} ${S.catOff.has(c) ? "off" : ""}" data-cat="${c}"><span class="sw bg-cat"></span>${CAT_VI[c]}</span>`).join("")}</div>`;
  }

  function categoryBlock(byCat) {
    const merged = {};
    Object.entries(byCat || {}).forEach(([k, v]) => { const c = CATS.includes(k) ? k : "other"; merged[c] = (merged[c] || 0) + v; });
    const rows = Object.entries(merged).filter(([, v]) => v >= 30).sort((a, b) => b[1] - a[1]);
    const total = rows.reduce((s, [, v]) => s + v, 0);
    if (!total) return `<div class="empty">${icon("layers")}Chưa có dữ liệu</div>`;
    return `<div class="stacked">${rows.map(([c, v]) => `<div class="c-${c}" data-g="${v}" ${tipAttrs(`${CAT_VI[c]} · ${fmtDur(v)}`, `${Math.round((v / total) * 100)}% thời gian`, c)}></div>`).join("")}</div>
      <div class="catlist">${rows.map(([c, v]) => `<div class="it c-${c}"><span class="sw bg-cat"></span>${CAT_VI[c]}<span class="t">${fmtDur(v)}</span><span class="p">${Math.round((v / total) * 100)}%</span></div>`).join("")}</div>`;
  }

  function bars(entries, catFor) {
    const rows = entries.slice(0, 8);
    if (!rows.length) return `<div class="empty">${icon("folder")}Chưa có dữ liệu</div>`;
    const top = rows[0][1] || 1;
    return `<div class="bars">${rows.map(([name, v]) => {
      const c = catFor ? catFor(name) : "development";
      return `<div class="b c-${c}" ${tipAttrs(name, fmtDur(v), c)}><span class="n">${esc(name)}</span><div class="track"><div class="fill" data-w="${((v / top) * 100).toFixed(2)}"></div></div><span class="t">${fmtDur(v)}</span></div>`;
    }).join("")}</div>`;
  }

  // ---------------------------------------------------------------- gate screens
  function gate(inner) { $("#app").innerHTML = `<div class="gate"><div class="box">${inner}</div></div>`; }

  function renderNoToken() {
    gate(`<div class="big">${icon("link")}</div><h2>Mở từ khay hệ thống</h2>
      <div class="dim">Nhấp biểu tượng <b>Work Agent</b> ở khay → <b>Mở cửa sổ</b>.</div>
      <div class="notice warning">${icon("shield")}<span>Mỗi lần mở, ứng dụng cấp một khoá truy cập mới cho tab này.</span></div>`);
  }

  function renderOffline() {
    gate(S.switched
      ? `<div class="big">${icon("monitor")}</div><h2>Đã chuyển sang ứng dụng</h2><div class="dim">Có thể đóng tab này.</div>`
      : `<div class="big">${icon("alert")}</div><h2>Mất kết nối</h2><div class="dim">Ứng dụng đã dừng hoặc khởi động lại. Mở lại từ khay hệ thống.</div>`);
  }

  function renderSetup() {
    gate(`<div class="big">${icon("shield")}</div><h2>Tạo kho dữ liệu</h2>
      <div class="dim">Dữ liệu được mã hoá trên máy bằng khoá sinh từ PIN.</div>
      <input id="p1" class="input pin" type="password" autocomplete="new-password" placeholder="PIN">
      <div class="meter" id="meter"><div></div></div>
      <input id="p2" class="input pin" type="password" autocomplete="new-password" placeholder="Nhập lại">
      <label class="row"><span class="switch"><input id="boot" type="checkbox" checked><span></span></span>Khởi động cùng Windows</label>
      <div class="notice critical">${icon("alert")}<span>Quên PIN = mất dữ liệu. Không có cách khôi phục.</span></div>
      <div class="err" id="err"></div>
      <button class="btn primary" id="go">${icon("lock")}Tạo kho & bắt đầu</button>`);
    const p1 = $("#p1"), p2 = $("#p2"), meter = $("#meter");
    p1.addEventListener("input", () => {
      const v = p1.value, min = S.st.min_pin;
      const score = v.length < min ? Math.min(30, (v.length / min) * 30) : (/^\d+$/.test(v) && v.length < 10 ? 60 : 100);
      meter.className = "meter" + (score >= 100 ? " strong" : score >= 60 ? " ok" : "");
      meter.firstElementChild.style.width = score + "%";
    });
    const go = async () => {
      const err = $("#err");
      if (p1.value.length < S.st.min_pin) { err.innerHTML = `${icon("alert")}Tối thiểu ${S.st.min_pin} ký tự`; return; }
      if (p1.value !== p2.value) { err.innerHTML = `${icon("alert")}Hai lần nhập không khớp`; return; }
      $("#go").disabled = true;
      try { await api("POST", "/api/setup", { pin: p1.value, run_at_startup: $("#boot").checked }); await refreshState(true); toast("Đã tạo kho dữ liệu"); }
      catch (e) { err.innerHTML = `${icon("alert")}Không tạo được kho (${esc(e.message)})`; $("#go").disabled = false; }
    };
    $("#go").addEventListener("click", go);
    p2.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    p1.focus();
  }

  let lockTimer = null;
  function renderLock() {
    const st = S.st;
    gate(`<div class="big">${icon("lock")}</div><h2>Đã khoá</h2>
      <div class="row">${chip("Vẫn đang theo dõi", "good", "", "")}${st.pending ? chip(`${st.pending} bản ghi chờ gộp`, "warning", "layers") : ""}</div>
      <input id="pin" class="input pin" type="password" autocomplete="current-password" placeholder="PIN">
      <div class="err" id="err"></div>
      <button class="btn primary" id="go">${icon("lock")}Mở khoá</button>`);
    const pin = $("#pin"), btn = $("#go"), err = $("#err");
    const countdown = (secs) => {
      clearInterval(lockTimer);
      let left = secs;
      btn.disabled = true;
      const tick = () => {
        if (left <= 0) { clearInterval(lockTimer); btn.disabled = false; err.innerHTML = `${icon("alert")}Sai PIN`; return; }
        err.innerHTML = `${icon("alert")}Sai PIN · thử lại sau ${left}s`; left -= 1;
      };
      tick(); lockTimer = setInterval(tick, 1000);
    };
    const go = async () => {
      if (!pin.value || btn.disabled) return;
      btn.disabled = true;
      try {
        const r = await api("POST", "/api/unlock", { pin: pin.value });
        S.st = null; await refreshState(true);
        if (r.migrated) toast(`Đã gộp ${r.migrated} bản ghi`);
      } catch (e) {
        pin.select();
        if (e.status === 403 || e.status === 429) {
          const wait = e.data.retry_after || 0;
          if (wait) countdown(wait); else { btn.disabled = false; err.innerHTML = `${icon("alert")}Sai PIN`; }
        } else { btn.disabled = false; err.innerHTML = `${icon("alert")}Lỗi: ${esc(e.message)}`; }
      }
    };
    btn.addEventListener("click", go);
    pin.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    pin.focus();
    // The setup chip has a live dot when tracking
    const good = $(".gate .chip.good");
    if (good && st.tracking === "tracking") good.insertAdjacentHTML("afterbegin", '<span class="live"></span>');
  }

  // ---------------------------------------------------------------- shell
  function renderShell() {
    $("#app").innerHTML = `<div class="shell">
      <nav class="rail" aria-label="Điều hướng">
        <div class="logo" title="Work Agent">${icon("timeline")}</div>
        ${NAV.map(([k, ic, label]) => `<button class="nav" data-nav="${k}" title="${esc(label)}">${icon(ic)}<span>${esc(label)}</span></button>`).join("")}
        <div class="spacer"></div>
        <div class="local" title="Dữ liệu chỉ lưu trên máy này và được mã hoá">${icon("shield")}<span>Cục bộ</span></div>
      </nav>
      <main class="main" id="main">
        <header class="topbar"><h1 id="vt"></h1><div id="vtools" class="row"></div><div class="grow"></div><div id="status" class="row"></div></header>
        <section class="content" id="view"></section>
      </main></div>`;
    $$("[data-nav]").forEach((b) => b.addEventListener("click", () => go(b.dataset.nav)));
    updateStatus();
  }

  function updateStatus() {
    const el = $("#status");
    if (!el || !S.st) return;
    const st = S.st;
    let left = "";
    if (st.tracking_error) left = chip("Không theo dõi được", "critical", "alert");
    else if (!st.tracking_started) left = chip("Chưa bắt đầu", "warning", "pause");
    else {
      const b = (mode, dot, label, ic, tip) => `<button class="${st.tracking === mode ? "on" : ""}" data-mode="${mode}" title="${esc(tip)}"><span class="dot ${dot}"></span>${icon(ic)}${label}</button>`;
      left = `<div class="seg" role="group" aria-label="Trạng thái theo dõi">
        ${b("tracking", "good", "Theo dõi", "play", "Ghi ứng dụng và tiêu đề cửa sổ")}
        ${b("paused", "warning", "Dừng", "pause", "Không ghi gì")}
        ${b("privacy", "violet", "Riêng tư", "eyeoff", "Chỉ ghi tên ứng dụng")}</div>`;
    }
    el.innerHTML = `${left}<button class="btn icon" id="lockbtn" title="Khoá kho dữ liệu">${icon("lock")}</button>`;
    $$("[data-mode]", el).forEach((btn) => btn.addEventListener("click", async () => {
      try { await api("POST", "/api/tracking", { mode: btn.dataset.mode }); await refreshState(); } catch (e) { toast("Không đổi được trạng thái", "critical"); }
    }));
    $("#lockbtn").addEventListener("click", async () => { if (!leaveOk()) return; await api("POST", "/api/lock").catch(() => {}); refreshState(true); });
  }

  function leaveOk() {
    return !(S.view === "report" && S.dirty) || confirm("Báo cáo chưa lưu. Bỏ thay đổi?");
  }

  function go(view) {
    if (view === S.view) return;
    if (!leaveOk()) return;
    if (S.view === "report") { S.dirty = false; S.editing = false; }
    location.hash = view;
  }

  const VIEWS = {};

  async function renderView(soft = false) {
    const v = VIEWS[S.view] || VIEWS.dashboard;
    $$("[data-nav]").forEach((b) => b.classList.toggle("active", b.dataset.nav === S.view));
    $("#vt").textContent = v.title;
    if (!soft) { $("#vtools").innerHTML = v.tools ? v.tools() : ""; v.bindTools && v.bindTools(); }
    const view = $("#view");
    if (!soft) view.innerHTML = `<div class="empty">${icon("clock")}Đang tải…</div>`;
    try {
      await v.load(soft);
      if (VIEWS[S.view] !== v) return;
      view.innerHTML = v.html();
      paint(view);
      v.bind && v.bind(view);
    } catch (e) {
      if (e instanceof ApiErr && (e.status === 423 || e.status === 401)) return;
      view.innerHTML = `<div class="empty">${icon("alert")}Không tải được dữ liệu</div>`;
    }
  }

  function dateTools() {
    return `<button class="btn icon ghost" data-d="-1" title="Ngày trước">${icon("left")}</button>
      <span class="chip num">${weekday(S.date)}</span>
      <input class="input" type="date" id="datepick" value="${S.date}" max="${today()}">
      <button class="btn icon ghost" data-d="1" title="Ngày sau" ${S.date >= today() ? "disabled" : ""}>${icon("right")}</button>
      <button class="btn ghost" data-d="0">Hôm nay</button>`;
  }
  function bindDateTools() {
    const set = (d) => { if (!d || d > today() || !leaveOk()) return; S.date = d; S.dirty = false; S.editing = false; renderView(); };
    $$("[data-d]").forEach((b) => b.addEventListener("click", () => set(b.dataset.d === "0" ? today() : shiftDate(S.date, +b.dataset.d))));
    $("#datepick").addEventListener("change", (e) => set(e.target.value));
  }

  // ---------------------------------------------------------------- dashboard
  function nowCard() {
    const st = S.st, a = st.current;
    let cat = "other", what = "Không có hoạt động", sub = "", right = "", chips = "", lead = "";
    if (!st.tracking_started) { what = st.tracking_error ? "Không theo dõi được" : "Chưa bắt đầu theo dõi"; cat = "away"; lead = icon("alert"); }
    else if (st.tracking === "paused") { what = "Đang tạm dừng"; sub = "Không ghi hoạt động"; cat = "away"; lead = icon("pause"); }
    else if (a && a.kind === "away") { cat = "away"; what = "Vắng mặt"; lead = icon("coffee"); right = a.start; }
    else if (a && a.kind === "locked") { cat = "away"; what = "Màn hình đang khoá"; lead = icon("lock"); right = a.start; }
    else if (a && a.kind === "private") { cat = "private"; what = "Riêng tư"; sub = "Không ghi chi tiết"; lead = icon("eyeoff"); right = a.start; }
    else if (a) {
      cat = catOf(a); what = a.app_name || a.app; sub = a.title; right = a.start;
      chips = `${chip(CAT_VI[cat], `c-${cat}`, "", "")}${a.project ? chip(a.project, "project", "folder") : ""}${(a.tickets || []).map(ticketChip).join("")}`;
    }
    const live = st.tracking === "tracking" && a && a.kind === "active" ? '<span class="live" title="Đang ghi"></span>' : "";
    return `<div class="card now c-${cat}"><div class="bar bg-cat"></div>
      <div class="stack tight">
        <div class="row"><span class="what">${lead} ${esc(what)}</span>${live}${chips}</div>
        ${sub ? `<div class="title" title="${esc(sub)}">${esc(sub)}</div>` : ""}
      </div>
      ${right ? `<div class="since"><div class="v num">${fmtDur(Date.now() / 1000 - right)}</div><div class="muted">từ ${hm(right)}</div></div>` : ""}</div>`;
  }

  function appCategories(acts) {
    const by = {};
    acts.filter((a) => a.kind === "active").forEach((a) => {
      const k = a.app_name || a.app; by[k] = by[k] || {}; const c = catOf(a); by[k][c] = (by[k][c] || 0) + (a.end - a.start);
    });
    return (name) => { const m = by[name]; if (!m) return "other"; return Object.entries(m).sort((x, y) => y[1] - x[1])[0][0]; };
  }

  VIEWS.dashboard = {
    title: "Tổng quan",
    async load() { S.day = await api("GET", `/api/day?date=${today()}`); },
    html() {
      const d = S.day, s = d.summary;
      const topProject = Object.keys(s.by_project)[0];
      const kpi = (ic, cls, v, l, tip) => `<div class="card kpi" title="${esc(tip || "")}"><div class="badge ${cls}">${icon(ic)}</div><div><div class="v num">${esc(v)}</div><div class="l">${esc(l)}</div></div></div>`;
      const cats = CATS.filter((c) => d.activities.some((a) => isWork(a) && catOf(a) === c));
      const catFor = appCategories(d.activities);
      return `<div class="stack">
        <div id="now">${nowCard()}</div>
        <div class="grid g4">
          ${kpi("clock", "good", fmtDur(s.active), "Hoạt động", `Riêng tư: ${fmtDur(s.private)} · Vắng: ${fmtDur(s.away)}`)}
          ${kpi("layers", "blue", String(d.sessions.length), "Phiên làm việc")}
          ${kpi("bolt", "violet", d.sessions.length ? fmtDur(s.longest) : "—", "Phiên dài nhất")}
          ${kpi("folder", "warning", topProject || "—", "Dự án chính", topProject ? fmtDur(s.by_project[topProject]) : "")}
        </div>
        <div class="card"><h3>${icon("timeline")}Hôm nay${s.first ? `<span class="count chip num">${hm(s.first)}–${hm(s.last)}</span>` : ""}</h3>
          ${strip(d.activities, d.day_start)}${cats.length ? legend(cats, false) : ""}</div>
        <div class="card"><h3>${icon("layers")}Theo nhóm</h3>${categoryBlock(s.by_category)}</div>
        <div class="grid g2">
          <div class="card"><h3>${icon("folder")}Dự án</h3>${bars(Object.entries(s.by_project))}</div>
          <div class="card"><h3>${icon("monitor")}Ứng dụng</h3>${bars(Object.entries(s.by_app), catFor)}</div>
        </div></div>`;
    },
  };

  function updateNow() {
    const el = $("#now");
    if (el) { el.innerHTML = nowCard(); }
  }

  // ---------------------------------------------------------------- timeline
  VIEWS.timeline = {
    title: "Dòng thời gian",
    tools: dateTools,
    bindTools: bindDateTools,
    async load() { S.day = await api("GET", `/api/day?date=${S.date}`); },
    html() {
      const d = S.day, s = d.summary;
      if (!s.first) return `<div class="card"><div class="empty">${icon("timeline")}Không có hoạt động ngày ${esc(S.date)}</div></div>`;
      const byId = Object.fromEntries(d.activities.map((a) => [a.id, a]));
      const cats = CATS.filter((c) => d.activities.some((a) => isWork(a) && catOf(a) === c));
      const needle = S.filter.trim().toLowerCase();
      const match = (a) => !S.catOff.has(catOf(a)) && (!needle ||
        `${a.app_name} ${a.title} ${a.project} ${a.file} ${(a.tickets || []).join(" ")} ${a.domain}`.toLowerCase().includes(needle));
      const sessions = d.sessions.map((x, i) => ({ ...x, i, acts: x.ids.map((id) => byId[id]).filter(Boolean) }))
        .map((x) => ({ ...x, shown: x.acts.filter(match) })).filter((x) => x.shown.length);
      const sessionHtml = sessions.map((x) => {
        const open = S.open.has(x.i) || needle;
        const comp = {};
        x.acts.forEach((a) => { const c = catOf(a); comp[c] = (comp[c] || 0) + (a.end - a.start); });
        const main = Object.entries(comp).sort((a, b) => b[1] - a[1])[0][0];
        const mini = `<div class="stacked mini">${Object.entries(comp).sort((a, b) => b[1] - a[1]).map(([c, v]) => `<div class="c-${c}" data-g="${v}" ${tipAttrs(`${CAT_VI[c]} · ${fmtDur(v)}`, "", c)}></div>`).join("")}</div>`;
        const rows = open ? `<div class="acts">${x.shown.map((a) => {
          const c = catOf(a), priv = a.kind === "private";
          const detail = priv ? "Riêng tư — không ghi chi tiết" : (a.title || "");
          return `<div class="act c-${c}"><span class="cb"></span><span class="tm">${hm(a.start)}–${hm(a.end)}</span><span class="du">${fmtDur(a.end - a.start)}</span>
            <span class="ap">${esc(a.app_name || a.app)}</span><span class="ti ${priv ? "priv" : ""}" title="${esc([a.title, a.url].filter(Boolean).join("\n"))}">${esc(detail)}</span>
            <span class="row">${a.project ? chip(a.project, "project", "folder") : ""}${(a.tickets || []).map(ticketChip).join("")}</span></div>`;
        }).join("")}</div>` : "";
        return `<div class="session ${open ? "open" : ""}"><div class="head" data-sess="${x.i}">
          <span class="time">${hm(x.start)}–${hm(x.end)}</span><span class="dur">${fmtDur(x.active)}</span>
          <span class="lbl c-${main}"><span class="sw bg-cat"></span><b>${esc(x.label)}</b>${x.tickets.slice(0, 3).map(ticketChip).join("")}</span>
          ${icon("right", "chev")}${mini}</div>${rows}</div>`;
      }).join("");
      return `<div class="summary-chips">
          ${chip(fmtDur(s.active), "good", "clock")}${chip(`${hm(s.first)}–${hm(s.last)}`, "", "play")}
          ${chip(`${d.sessions.length} phiên`, "", "layers")}${chip(`Vắng ${fmtDur(s.away)}`, "", "coffee")}
          ${s.private ? chip(`Riêng tư ${fmtDur(s.private)}`, "violet", "eyeoff") : ""}</div>
        <div class="card">${strip(d.activities, d.day_start)}${legend(cats, true)}</div>
        <div class="row my">
          <div class="flex1"><input class="input" id="filter" placeholder="Lọc: ứng dụng, tiêu đề, dự án, ticket…" value="${esc(S.filter)}"></div>
          <button class="btn ghost" id="expand">${icon("layers")}${S.open.size ? "Thu gọn" : "Mở tất cả"}</button>
          <button class="btn danger" id="delday" title="Xoá vĩnh viễn hoạt động của ngày này">${icon("trash")}Xoá ngày</button></div>
        <div class="stack">${sessionHtml || `<div class="empty">${icon("search")}Không có kết quả</div>`}</div>`;
    },
    bind(view) {
      $$("[data-sess]", view).forEach((h) => h.addEventListener("click", (e) => {
        if (e.target.closest("a")) return;
        const i = +h.dataset.sess; S.open.has(i) ? S.open.delete(i) : S.open.add(i); rerender();
      }));
      $$(".legend .it.click", view).forEach((it) => it.addEventListener("click", () => {
        const c = it.dataset.cat; S.catOff.has(c) ? S.catOff.delete(c) : S.catOff.add(c); rerender();
      }));
      const f = $("#filter", view);
      if (f) {
        f.addEventListener("input", () => { S.filter = f.value; rerender(true); });
      }
      const ex = $("#expand", view);
      ex && ex.addEventListener("click", () => { if (S.open.size) S.open.clear(); else S.day.sessions.forEach((_, i) => S.open.add(i)); rerender(); });
      const del = $("#delday", view);
      del && del.addEventListener("click", async () => {
        if (!confirm(`Xoá vĩnh viễn toàn bộ hoạt động ngày ${S.date}? Báo cáo vẫn được giữ.`)) return;
        await api("DELETE", `/api/day?date=${S.date}`); toast("Đã xoá dữ liệu ngày"); renderView();
      });
    },
  };

  function rerender(keepFocus) {
    const v = VIEWS[S.view], view = $("#view");
    const pos = keepFocus && document.activeElement && document.activeElement.id === "filter" ? document.activeElement.selectionStart : null;
    view.innerHTML = v.html(); paint(view); v.bind && v.bind(view);
    if (pos !== null) { const f = $("#filter"); f.focus(); f.setSelectionRange(pos, pos); }
  }

  // ---------------------------------------------------------------- tasks
  VIEWS.tasks = {
    title: "Công việc",
    tools: () => `<button class="btn primary" id="newtask">${icon("plus")}Thêm việc</button>`,
    bindTools() { $("#newtask").addEventListener("click", () => taskModal({ status: "todo" })); },
    async load() {
      const [t, k] = await Promise.all([api("GET", "/api/tasks"), api("GET", "/api/tickets")]);
      S.tasks = t.tasks; S.jira = t.jira || ""; S.tickets = k.tickets;
    },
    html() {
      const col = ([key, label, ic]) => {
        const items = S.tasks.filter((t) => t.status === key);
        return `<div class="col st-${key}" data-col="${key}"><div class="ch">${icon(ic)}${esc(label)}<span class="count">${items.length}</span></div>
          ${items.map((t) => `<div class="tcard st-${t.status} ${t.status === "done" ? "done" : ""}" draggable="true" data-task="${esc(t.id)}">
            <div class="tt">${esc(t.title)}</div><div class="row">
            ${t.ticket ? ticketChip(t.ticket) : ""}${t.project ? chip(t.project, "project", "folder") : ""}
            ${t.needs_support ? chip("Hỗ trợ", "warning", "flag") : ""}${t.tracked > 0 ? chip(fmtDur(t.tracked), "", "clock", 'title="Thời gian ghi nhận 7 ngày"') : ""}</div></div>`).join("")}
        </div>`;
      };
      const tickets = S.tickets.length ? S.tickets.map((k) => k.has_task
        ? chip(`${k.ticket} · ${fmtDur(k.seconds)}`, "good", "check", 'title="Đã có công việc"')
        : `<span class="chip ticket click" data-ticket="${esc(k.ticket)}" title="Tạo công việc">${icon("plus")}${esc(k.ticket)} · ${fmtDur(k.seconds)}</span>`).join("")
        : `<span class="muted">Chưa phát hiện ticket nào</span>`;
      return `<div class="board">${STATUSES.map(col).join("")}</div>
        <div class="card mt"><h3>${icon("search")}Ticket phát hiện · 7 ngày</h3><div class="row">${tickets}</div></div>`;
    },
    bind(view) {
      const byId = Object.fromEntries(S.tasks.map((t) => [t.id, t]));
      $$("[data-task]", view).forEach((c) => {
        c.addEventListener("click", (e) => { if (!e.target.closest("a")) taskModal(byId[c.dataset.task]); });
        c.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/plain", c.dataset.task); });
      });
      $$("[data-col]", view).forEach((col) => {
        col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("drop"); });
        col.addEventListener("dragleave", () => col.classList.remove("drop"));
        col.addEventListener("drop", async (e) => {
          e.preventDefault(); col.classList.remove("drop");
          const t = byId[e.dataTransfer.getData("text/plain")];
          if (!t || t.status === col.dataset.col) return;
          await api("POST", "/api/tasks", { ...t, status: col.dataset.col }); renderView(true);
        });
      });
      $$("[data-ticket]", view).forEach((c) => c.addEventListener("click", () => taskModal({ ticket: c.dataset.ticket, title: c.dataset.ticket, status: "doing" })));
    },
  };

  function taskModal(t) {
    const status = t.status || "todo";
    modal(`<h2>${t.id ? "Sửa công việc" : "Công việc mới"}</h2>
      <div><label>Tiêu đề</label><input class="input" id="t-title" value="${esc(t.title || "")}" maxlength="300"></div>
      <div><label>Trạng thái</label><div class="seg" id="t-status">${STATUSES.map(([k, l, ic]) => `<button type="button" class="st-${k} ${k === status ? "on" : ""}" data-v="${k}">${icon(ic)}${l}</button>`).join("")}</div></div>
      <div class="grid g2"><div><label>Ticket</label><input class="input" id="t-ticket" value="${esc(t.ticket || "")}" placeholder="PROJ-123"></div>
      <div><label>Dự án</label><input class="input" id="t-project" value="${esc(t.project || "")}"></div></div>
      <div><label>Ghi chú</label><textarea class="textarea" id="t-notes">${esc(t.notes || "")}</textarea></div>
      <label class="row"><span class="switch"><input type="checkbox" id="t-support" ${t.needs_support ? "checked" : ""}><span></span></span>${icon("flag")}Cần hỗ trợ / escalate</label>
      <div class="actions">${t.id ? `<button class="btn danger" id="t-del">${icon("trash")}Xoá</button><span class="sp"></span>` : ""}
        <button class="btn ghost" id="t-cancel">Huỷ</button><button class="btn primary" id="t-save">${icon("check")}Lưu</button></div>`,
    (ov, close) => {
      $$("#t-status button", ov).forEach((b) => b.addEventListener("click", () => { $$("#t-status button", ov).forEach((x) => x.classList.toggle("on", x === b)); }));
      $("#t-cancel", ov).addEventListener("click", close);
      $("#t-save", ov).addEventListener("click", async () => {
        const title = $("#t-title", ov).value.trim();
        if (!title) { $("#t-title", ov).focus(); return; }
        await api("POST", "/api/tasks", {
          id: t.id, title, status: $("#t-status .on", ov).dataset.v, ticket: $("#t-ticket", ov).value,
          project: $("#t-project", ov).value, notes: $("#t-notes", ov).value, needs_support: $("#t-support", ov).checked,
        });
        close(); toast("Đã lưu"); renderView(true);
      });
      const del = $("#t-del", ov);
      del && del.addEventListener("click", async () => {
        if (!confirm("Xoá công việc này?")) return;
        await api("DELETE", `/api/tasks?id=${encodeURIComponent(t.id)}`); close(); toast("Đã xoá", "warning"); renderView(true);
      });
    });
  }

  // ---------------------------------------------------------------- chat
  const SUGGEST = ["Hôm nay tôi làm gì", "Hôm qua tôi làm gì", "Tôi đang làm gì", "Các phiên hôm nay", "Hôm nay có vướng gì", "Kế hoạch ngày mai"];
  VIEWS.chat = {
    title: "Trợ lý",
    tools: () => {
      const ai = S.st.ai;
      return ai.provider === "none" || !ai.chat ? chip("Cục bộ", "good", "shield", 'title="Không dữ liệu nào rời khỏi máy"')
        : chip(`AI · ${ai.provider}`, "warning", "globe", 'title="Câu hỏi khó sẽ gửi kèm trích đoạn hoạt động"');
    },
    async load() {},
    html() {
      const msgs = S.chat.length ? S.chat.map((m) => `<div class="msg ${m.me ? "me" : "bot"}">${esc(m.text)}${m.used_llm ? `<div class="meta">${chip(`Đã gửi ${m.shared} mục cho AI`, "warning", "globe")}</div>` : ""}</div>`).join("")
        : `<div class="empty">${icon("bot")}Hỏi về lịch sử làm việc của bạn</div>`;
      return `<div class="chat"><div class="msgs" id="msgs">${msgs}${S.busy ? '<div class="msg bot typing">…</div>' : ""}</div>
        <div class="suggest">${SUGGEST.map((q) => `<span class="chip click" data-q="${esc(q)}">${esc(q)}</span>`).join("")}</div>
        <div class="composer"><input class="input" id="q" placeholder="Hỏi… vd: tìm login bug, bao lâu dayflow" maxlength="1000">
        <button class="btn primary" id="send" ${S.busy ? "disabled" : ""}>${icon("send")}Gửi</button></div></div>`;
    },
    bind(view) {
      const q = $("#q", view), msgs = $("#msgs", view);
      msgs.scrollTop = msgs.scrollHeight;
      const ask = async (text) => {
        text = (text || "").trim();
        if (!text || S.busy) return;
        S.chat.push({ me: true, text }); S.busy = true; rerender();
        try {
          const r = await api("POST", "/api/agent", { question: text });
          S.chat.push({ me: false, text: r.text, used_llm: r.used_llm, shared: r.shared });
        } catch (e) { S.chat.push({ me: false, text: "Không trả lời được lúc này." }); }
        S.busy = false;
        if (S.view === "chat") { rerender(); $("#q").focus(); }
      };
      $("#send", view).addEventListener("click", () => ask(q.value));
      q.addEventListener("keydown", (e) => { if (e.key === "Enter") ask(q.value); });
      $$("[data-q]", view).forEach((c) => c.addEventListener("click", () => ask(c.dataset.q)));
      q.focus();
    },
  };

  // ---------------------------------------------------------------- report
  function parseReport(md) {
    const keys = SECS.map((s) => s[0]);
    const out = Object.fromEntries(keys.map((k) => [k, []]));
    let cur = null, summary = "";
    for (const raw of (md || "").split(/\r?\n/)) {
      const line = raw.replace(/\s+$/, "");
      let m = line.match(/^##\s*(\d)\./);
      if (m) { cur = keys[+m[1] - 1] || null; continue; }
      if (/^#\s/.test(line)) continue;
      if (!cur) { if (/^_.*_$/.test(line.trim())) summary = line.trim().slice(1, -1); continue; }
      m = line.match(/^\s+-\s*_?Evidence:\s*(.*?)_?$/i);
      if (m && out[cur].length) { out[cur][out[cur].length - 1].ev = m[1].split(/;\s*/).filter(Boolean); continue; }
      m = line.match(/^\s*-\s+(.*)$/);
      if (m) {
        let t = m[1];
        if (/^_None[^_]*_$/.test(t)) continue;
        const inf = t.startsWith("(inferred) ");
        if (inf) t = t.slice(11);
        out[cur].push({ t, inf, ev: [] });
        continue;
      }
      if (line.trim() && out[cur].length) out[cur][out[cur].length - 1].t += " " + line.trim();
    }
    return { sections: out, summary };
  }

  // Minimal inline Markdown on already-escaped text: **bold** and `code` only.
  const inlineMd = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");

  function evidenceChip(e) {
    const m = e.match(/^(\d\d:\d\d[–-]\d\d:\d\d)\s+(.*)$/);
    return m ? `<span class="chip" ${tipAttrs(m[1], m[2])}>${icon("clock")}${esc(m[1])}</span>` : chip(e);
  }

  VIEWS.report = {
    title: "Báo cáo ngày",
    tools: dateTools,
    bindTools: bindDateTools,
    async load(soft) {
      if (soft && S.dirty) return;
      const r = await api("GET", `/api/report?date=${S.date}`);
      S.report = r.report; S.draft = null; S.text = r.report ? r.report.markdown : ""; S.dirty = false;
    },
    html() {
      const rep = S.report || S.draft;
      if (!rep) {
        return `<div class="card"><div class="empty">${icon("report")}<div>Chưa có báo cáo ngày ${esc(S.date)}</div>
          <button class="btn primary" id="gen">${icon("sparkle")}Tạo bản nháp</button></div></div>`;
      }
      const when = new Date(rep.generated_at * 1000);
      const meta = [
        chip(`${S.report ? "Đã lưu" : "Nháp"} · ${pad(when.getHours())}:${pad(when.getMinutes())}`, S.report ? "good" : "warning", S.report ? "check" : "edit"),
        (rep.generator || "").startsWith("llm:") ? chip(`AI tổng hợp · ${rep.generator.slice(4)}`, "violet", "sparkle")
          : rep.generator === "rules+llm" ? chip("AI viết lại", "violet", "sparkle") : chip("Quy tắc cục bộ", "", "shield"),
        rep.ai_error ? chip(`AI: ${rep.ai_error}`, "critical", "alert", `title="${esc(rep.ai_error)}"`) : "",
        rep.edited ? chip("Đã chỉnh sửa", "", "edit") : "",
        S.dirty ? chip("Chưa lưu", "warning", "alert") : "",
      ].join("");
      const actions = `<span class="sp"></span>
        <button class="btn ghost" id="gen">${icon("sparkle")}Tạo lại</button>
        <button class="btn ghost" id="mode">${S.editing ? icon("eye") + "Xem" : icon("edit") + "Sửa"}</button>
        <button class="btn icon ghost" id="copy" title="Sao chép Markdown">${icon("copy")}</button>
        <button class="btn icon ghost" id="dl" title="Tải file .md">${icon("download")}</button>
        <button class="btn primary" id="save" ${S.dirty ? "" : "disabled"}>${icon("check")}Lưu</button>`;
      let body;
      if (S.editing) {
        body = `<textarea class="textarea editor" id="md" spellcheck="false">${esc(S.text)}</textarea>`;
      } else {
        const p = parseReport(S.text);
        body = `${p.summary ? `<div class="row mb">${chip(p.summary, "", "clock")}</div>` : ""}
          <div class="rgrid">${SECS.map(([k, label, ic], idx) => {
            const items = p.sections[k];
            return `<div class="rsec sec-${k} ${idx === 0 ? "wide" : ""}"><div class="rh"><span class="ic">${icon(ic)}</span><b>${esc(label)}</b><span class="count chip num">${items.length}</span></div>
              ${items.length ? `<ul>${items.map((it) => `<li>${it.inf ? chip("suy luận", "inferred", "", 'title="Kết luận heuristic — hãy xác nhận hoặc xoá"') + " " : ""}${inlineMd(it.t)}
                ${it.ev.length ? `<div class="ev">${it.ev.map(evidenceChip).join("")}</div>` : ""}</li>`).join("")}</ul>` : `<div class="muted">—</div>`}</div>`;
          }).join("")}</div>`;
      }
      return `<div class="report-meta">${meta}${actions}</div>${body}`;
    },
    bind(view) {
      const gen = $("#gen", view);
      gen && gen.addEventListener("click", async () => {
        if ((S.report && S.report.edited || S.dirty) && !confirm("Thay nội dung hiện tại bằng bản nháp mới?")) return;
        gen.disabled = true;
        if (S.st.ai.reports && S.st.ai.provider !== "none") {
          gen.innerHTML = `${icon("clock")}AI đang viết…`;
          toast("AI đang tổng hợp báo cáo — có thể mất tới vài phút", "info");
        }
        try {
          const r = await api("POST", "/api/report/generate", { date: S.date });
          S.draft = r.report; S.text = r.report.markdown; S.dirty = true;
          if (S.report) { S.report = { ...S.report, generated_at: r.report.generated_at, generator: r.report.generator }; }
          rerender(); toast("Đã tạo bản nháp — nhớ Lưu", "warning");
        } catch (e) { gen.disabled = false; gen.innerHTML = `${icon("sparkle")}Tạo lại`; toast("Không tạo được báo cáo", "critical"); }
      });
      const mode = $("#mode", view);
      mode && mode.addEventListener("click", () => { S.editing = !S.editing; rerender(); });
      const md = $("#md", view);
      md && md.addEventListener("input", () => {
        S.text = md.value;
        if (!S.dirty) { S.dirty = true; $("#save").disabled = false; $(".report-meta").insertAdjacentHTML("afterbegin", chip("Chưa lưu", "warning", "alert")); }
      });
      const save = $("#save", view);
      save && save.addEventListener("click", async () => {
        const r = await api("PUT", "/api/report", { date: S.date, markdown: S.text, generated: S.draft });
        S.report = r.report; S.draft = null; S.dirty = false; rerender(); toast("Đã lưu báo cáo");
      });
      const copy = $("#copy", view);
      copy && copy.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(S.text); toast("Đã sao chép"); } catch (e) { toast("Không sao chép được", "critical"); }
      });
      const dl = $("#dl", view);
      dl && dl.addEventListener("click", () => {
        const url = URL.createObjectURL(new Blob([S.text], { type: "text/markdown;charset=utf-8" }));
        const a = document.createElement("a"); a.href = url; a.download = `bao-cao-${S.date}.md`; a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        toast("File tải về không được mã hoá", "warning");
      });
    },
  };

  // ---------------------------------------------------------------- settings
  const getPath = (o, k) => k.split(".").reduce((x, p) => (x == null ? x : x[p]), o);
  const setPath = (o, k, v) => { const ps = k.split("."); const last = ps.pop(); ps.reduce((x, p) => (x[p] = x[p] || {}), o)[last] = v; };

  function fSwitch(k, label, hint) {
    // A <label> wrapper so clicking the switch (or its text) toggles the visually hidden checkbox.
    return `<label class="field toggle"><span class="fl">${esc(label)}</span><span class="switch"><input type="checkbox" data-k="${k}" ${getPath(S.cfg, k) ? "checked" : ""}><span></span></span>${hint ? `<span class="fh">${esc(hint)}</span>` : ""}</label>`;
  }
  function fNum(k, label, unit, min, max) {
    return `<div class="field"><span class="fl">${esc(label)}</span><span class="row"><input class="input w-sm num" type="number" data-k="${k}" min="${min}" max="${max}" value="${esc(getPath(S.cfg, k))}"><span class="muted">${esc(unit)}</span></span></div>`;
  }
  function fText(k, label, ph, type = "text") {
    return `<div class="field col1"><span class="fl">${esc(label)}</span><input class="input" type="${type}" data-k="${k}" value="${esc(getPath(S.cfg, k))}" placeholder="${esc(ph || "")}"></div>`;
  }
  function fList(k, label, hint, t = "list") {
    let v = getPath(S.cfg, k) || [];
    v = t === "rules" ? v.map((r) => `${r.match} => ${r.project}`).join("\n") : v.join("\n");
    return `<div class="field col1"><span class="fl">${esc(label)}</span><textarea class="textarea" data-k="${k}" data-t="${t}" placeholder="${esc(hint || "")}">${esc(v)}</textarea></div>`;
  }
  function fSeg(k, label, opts) {
    const cur = getPath(S.cfg, k);
    return `<div class="field"><span class="fl">${esc(label)}</span><div class="seg" data-k="${k}">${opts.map(([v, l, ic]) => `<button type="button" data-v="${esc(v)}" class="${v === cur ? "on" : ""}">${ic ? icon(ic) : ""}${esc(l)}</button>`).join("")}</div></div>`;
  }

  VIEWS.settings = {
    title: "Cài đặt",
    async load() {
      const [r, info] = await Promise.all([api("GET", "/api/settings"), api("GET", "/api/ai")]);
      S.cfg = r.config; S.cfgSaved = JSON.parse(JSON.stringify(r.config)); S.aiInfo = info; S.pendingKeys = {};
      S.cfg.ai.models = S.cfg.ai.models || {};
    },
    html() {
      const c = S.cfg;
      return `<div class="settings">
        <div class="card"><h3>${icon("monitor")}Giao diện</h3>
          ${fSeg("ui_mode", "Kiểu giao diện", [["desktop", "Ứng dụng", "monitor"], ["web", "Web", "globe"]])}
          ${fNum("web_port", "Cổng web (127.0.0.1)", "", 1024, 65535)}
          ${fSwitch("run_at_startup", "Khởi động cùng Windows")}
          ${fSwitch("start_minimized", "Khởi động thu nhỏ xuống khay")}
          ${fSwitch("debug", "Log debug", "Không bao giờ ghi tiêu đề, URL hay nội dung báo cáo")}</div>
        <div class="card"><h3>${icon("lock")}Bảo mật</h3>
          ${fSwitch("security.lock_on_windows_lock", "Khoá khi Windows khoá")}
          ${fNum("security.auto_lock_idle_minutes", "Tự khoá khi không thao tác", "phút (0 = tắt)", 0, 480)}
          <div class="field"><span class="fl">PIN</span><span class="row"><button class="btn" id="chpin">${icon("key")}Đổi PIN</button><button class="btn" id="locknow">${icon("lock")}Khoá ngay</button></span></div></div>
        <div class="card"><h3>${icon("play")}Theo dõi</h3>
          ${fNum("tracking.sample_seconds", "Lấy mẫu mỗi", "giây", 1, 30)}
          ${fNum("tracking.idle_seconds", "Vắng mặt sau", "giây", 30, 3600)}
          ${fSwitch("tracking.start_paused", "Khởi động ở trạng thái dừng", "Thay đổi chu kỳ có hiệu lực sau khi khởi động lại")}</div>
        <div class="card"><h3>${icon("report")}Báo cáo ngày</h3>
          ${fSwitch("report.auto_generate", "Tự tạo bản nháp")}
          <div class="field"><span class="fl">Thời điểm</span><input class="input w-sm num" type="time" data-k="report.time" value="${esc(c.report.time)}"></div>
          ${fNum("report.block_minutes", "Gắn cờ bị chặn sau", "phút / vấn đề", 10, 480)}</div>
        <div class="card"><h3>${icon("eyeoff")}Quyền riêng tư</h3>
          ${fSeg("privacy.browser_url_mode", "URL trình duyệt", [["off", "Tắt"], ["domain", "Tên miền"], ["full", "Đầy đủ"]])}
          ${fSwitch("privacy.redact_secrets", "Che chuỗi giống bí mật", "Token, JWT, khoá API, mã OTP trong tiêu đề")}
          ${fList("privacy.blocked_apps", "Ứng dụng chặn (.exe)")}
          ${fList("privacy.blocked_keywords", "Từ khoá chặn")}
          ${fList("privacy.blocked_domains", "Tên miền chặn")}</div>
        ${aiCard()}
        <div class="card"><h3>${icon("link")}Tích hợp</h3>
          ${fText("integrations.jira_base_url", "Jira", "https://company.atlassian.net")}
          <div class="field col1"><span class="fl">Mã dự án ticket</span><input class="input" data-k="integrations.ticket_projects" data-t="csv" value="${esc((c.integrations.ticket_projects || []).join(", "))}" placeholder="PROJ, OPS (trống = mọi KEY-123)"></div>
          ${fList("integrations.project_rules", "Quy tắc dự án", "chữ trong tiêu đề => Tên dự án", "rules")}</div>
      </div>
      <div class="savebar"><button class="btn primary" id="savecfg">${icon("check")}Lưu cài đặt</button></div>`;
    },
    bind(view) {
      bindSegs(view);
      bindAi(view);
      $("#chpin", view).addEventListener("click", pinModal);
      $("#locknow", view).addEventListener("click", async () => { await api("POST", "/api/lock").catch(() => {}); refreshState(true); });
      $("#savecfg", view).addEventListener("click", saveSettings);
    },
  };


  // ---------------------------------------------------------------- AI provider card
  S.aiModels = {};
  const isLocalAi = (provider, url) => {
    const spec = S.aiInfo && S.aiInfo.providers.find((p) => p.id === provider);
    if (!spec) return provider === "none";
    if (spec.url_editable) return /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/i.test(url || spec.base_url);
    return spec.local;
  };

  function aiCard() {
    const ai = S.cfg.ai, info = S.aiInfo;
    const spec = info.providers.find((p) => p.id === ai.provider) || info.providers[0];
    const model = ai.models[spec.id] || spec.model || "";
    const options = [...new Set([...(S.aiModels[spec.id] || []), ...spec.models, model].filter(Boolean))];
    const pending = S.pendingKeys[spec.id];
    const keySaved = spec.key_set && pending !== "";
    const local = isLocalAi(spec.id, ai.base_url);
    const kind = spec.kind === "none" ? chip("Tắt — không gửi dữ liệu", "good", "shield")
      : local ? chip("Chạy trên máy này", "good", "shield")
        : spec.kind === "opencode" ? chip("CLI cục bộ · model đám mây", "warning", "globe") : chip("Dịch vụ đám mây", "warning", "globe");
    let body = "";
    if (spec.kind !== "none") {
      body += `<div class="row mb">${kind}${spec.key_url ? `<a class="chip click" href="${esc(spec.key_url)}" target="_blank" rel="noopener noreferrer">${icon("key")}Lấy API key</a>` : ""}</div>`;
      if (spec.url_editable) {
        body += `<div class="field col1"><span class="fl">Base URL</span><input class="input" id="ai-url" value="${esc(ai.base_url || spec.base_url)}" placeholder="${esc(spec.base_url)}"></div>`;
      }
      const custom = model && !options.includes(model);
      body += `<div class="field col1"><span class="fl">Model</span><div class="row">
          <select class="select flex1" id="ai-model">${options.map((m) => `<option value="${esc(m)}" ${m === model ? "selected" : ""}>${esc(m)}</option>`).join("")}
            <option value="__custom" ${custom || !options.length ? "selected" : ""}>Khác… (tự nhập)</option></select>
          <button class="btn" id="ai-load" title="Hỏi nhà cung cấp danh sách model hiện có">${icon("search")}Tải danh sách</button></div>
          <input class="input ${custom || !options.length ? "" : "hidden"}" id="ai-model-custom" value="${esc(custom ? model : "")}" placeholder="Tên model, vd: ${esc(spec.models[0] || "model-id")}"></div>`;
      if (spec.needs_key) {
        body += `<div class="field col1"><span class="fl">API key · ${esc(spec.label)}</span><div class="row">
          <input class="input flex1" type="password" id="ai-key" autocomplete="off" value="${esc(pending || "")}"
            placeholder="${keySaved ? "●●●●●● đã lưu (mã hoá trong kho) — nhập để thay" : "Dán API key"}">
          ${keySaved ? `<button class="btn danger" id="ai-key-clear" title="Xoá key đã lưu">${icon("trash")}</button>` : ""}</div>
          <span class="fh">${pending === "" ? "Key sẽ bị xoá khi lưu" : "Mỗi nhà cung cấp có key riêng, lưu mã hoá trong kho dữ liệu"}</span></div>`;
      }
      if (spec.kind === "opencode") {
        const oc = info.opencode;
        body += `<div class="field col1"><span class="fl">OpenCode CLI</span><div class="row">
            ${oc.found ? chip("Đã tìm thấy", "good", "check", `title="${esc(oc.path)}"`) : chip("Chưa tìm thấy", "critical", "alert")}
            <input class="input flex1" id="ai-ocpath" value="${esc(ai.opencode_path || "")}" placeholder="${esc(oc.path || "Tự phát hiện — hoặc nhập đường dẫn opencode.exe")}"></div></div>
          <div class="notice warning">${icon("alert")}<span>Model của OpenCode (kể cả Big Pickle miễn phí) chạy trên máy chủ OpenCode, không phải trên máy bạn.
            Mỗi lần gọi chạy trong thư mục trống; nếu agent định dùng công cụ, kết quả bị huỷ.</span></div>`;
      }
      body += `<div class="field"><span class="fl">Kiểm tra kết nối</span><span class="row"><span id="ai-result"></span>
          <button class="btn" id="ai-test">${icon("play")}Kiểm tra</button></span>
          <span class="fh">Gửi một câu cố định "Reply with exactly: OK" — không kèm dữ liệu của bạn</span></div>`;
      body += fSeg("ai.report_mode", "AI cho báo cáo", [["compose", "Tổng hợp từ lịch sử", "sparkle"], ["polish", "Chỉ viết lại câu", "edit"]]);
      body += fSeg("ai.report_language", "Ngôn ngữ báo cáo AI", [["vi", "Tiếng Việt"], ["en", "English"]]);
      body += fSwitch("ai.allow_reports", "Cho phép gửi lịch sử để viết báo cáo", "Gửi nhật ký hoạt động trong ngày (tiêu đề cửa sổ, dự án, ticket; mục riêng tư chỉ có thời lượng)");
      body += fSwitch("ai.allow_chat", "Cho phép gửi khi hỏi trợ lý", "Câu hỏi quy tắc cục bộ không trả lời được sẽ gửi kèm trích đoạn 2 ngày gần nhất");
    }
    return `<div class="card" id="aicard"><h3>${icon("sparkle")}AI</h3>
      <div class="field col1"><span class="fl">Nhà cung cấp</span><select class="select" id="ai-provider">
        ${info.providers.map((p) => `<option value="${esc(p.id)}" ${p.id === spec.id ? "selected" : ""}>${esc(p.label)}${p.key_set ? " ✓" : ""}</option>`).join("")}
      </select></div>${body}</div>`;
  }

  function currentModel() {
    const sel = $("#ai-model");
    if (!sel) return "";
    return sel.value === "__custom" ? ($("#ai-model-custom").value || "").trim() : sel.value;
  }

  function rerenderAi() {
    const card = $("#aicard");
    card.outerHTML = aiCard();
    const fresh = $("#aicard");
    bindSegs(fresh);
    bindAi(fresh);
  }

  function bindSegs(root) {
    $$(".seg[data-k] button", root).forEach((b) => b.addEventListener("click", () => {
      $$("button", b.parentElement).forEach((x) => x.classList.toggle("on", x === b));
      setPath(S.cfg, b.parentElement.dataset.k, b.dataset.v);
    }));
    $$("input[type=checkbox][data-k]", root).forEach((el) => el.addEventListener("change", () => setPath(S.cfg, el.dataset.k, el.checked)));
  }

  function bindAi(root) {
    const ai = S.cfg.ai;
    const prov = $("#ai-provider", root);
    if (!prov) return;
    prov.addEventListener("change", () => { ai.provider = prov.value; rerenderAi(); });
    const pid = ai.provider;
    const saveModel = () => { const m = currentModel(); if (m) { ai.models[pid] = m; ai.model = m; } };
    const sel = $("#ai-model", root);
    sel && sel.addEventListener("change", () => {
      $("#ai-model-custom", root).classList.toggle("hidden", sel.value !== "__custom");
      if (sel.value === "__custom") $("#ai-model-custom", root).focus();
      saveModel();
    });
    const customIn = $("#ai-model-custom", root);
    customIn && customIn.addEventListener("input", saveModel);
    const url = $("#ai-url", root);
    url && url.addEventListener("input", () => { ai.base_url = url.value.trim(); });
    const ocp = $("#ai-ocpath", root);
    ocp && ocp.addEventListener("input", () => { ai.opencode_path = ocp.value.trim(); });
    const key = $("#ai-key", root);
    key && key.addEventListener("input", () => { if (key.value) S.pendingKeys[pid] = key.value; else delete S.pendingKeys[pid]; });
    const clear = $("#ai-key-clear", root);
    clear && clear.addEventListener("click", () => { S.pendingKeys[pid] = ""; rerenderAi(); });
    const args = () => ({ provider: pid, base_url: url ? url.value.trim() : null, api_key: S.pendingKeys[pid] || null });
    const load = $("#ai-load", root);
    load && load.addEventListener("click", async () => {
      load.disabled = true;
      try {
        const r = await api("POST", "/api/ai/models", args());
        S.aiModels[pid] = r.models;
        toast(`Tìm thấy ${r.models.length} model`);
        rerenderAi();
      } catch (e) { load.disabled = false; toast(e.data.message || "Không tải được danh sách model", "critical"); }
    });
    const test = $("#ai-test", root), out = $("#ai-result", root);
    test && test.addEventListener("click", async () => {
      test.disabled = true;
      out.innerHTML = chip(pid === "opencode" ? "Đang chạy OpenCode… (có thể mất ~1 phút)" : "Đang kiểm tra…", "", "clock");
      try {
        const r = await api("POST", "/api/ai/test", { ...args(), model: currentModel() });
        out.innerHTML = chip(`OK · ${r.seconds}s`, "good", "check", `title="${esc(r.reply)}"`);
      } catch (e) {
        out.innerHTML = chip(e.data.message || e.message, "critical", "alert");
      }
      test.disabled = false;
    });
  }

  async function saveSettings() {
    const cfg = JSON.parse(JSON.stringify(S.cfg));
    $$("[data-k]", $("#view")).forEach((el) => {
      const k = el.dataset.k, t = el.dataset.t;
      let v;
      if (el.classList.contains("seg")) v = $(".on", el) ? $(".on", el).dataset.v : getPath(cfg, k);
      else if (el.type === "checkbox") v = el.checked;
      else if (el.type === "number") v = Number(el.value);
      else if (t === "list") v = el.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
      else if (t === "csv") v = el.value.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
      else if (t === "rules") v = el.value.split(/\r?\n/).map((s) => s.split("=>")).filter((p) => p.length === 2 && p[0].trim() && p[1].trim()).map(([m, p]) => ({ match: m.trim(), project: p.trim() }));
      else v = el.value.trim();
      setPath(cfg, k, v);
    });
    const was = S.cfgSaved.ai, now = cfg.ai;
    const cloud = (a) => !isLocalAi(a.provider, a.base_url) && a.provider !== "none";
    if (cloud(now) && (now.allow_chat || now.allow_reports) && !(cloud(was) && (was.allow_chat || was.allow_reports))
        && !confirm("Trích đoạn hoạt động sẽ được gửi tới dịch vụ AI bên ngoài khi dùng các tính năng này. Tiếp tục?")) return;
    try {
      await api("PUT", "/api/settings", { config: cfg, api_keys: S.pendingKeys });
    } catch (e) { toast("Cài đặt không hợp lệ", "critical"); return; }
    toast("Đã lưu cài đặt");
    if (cfg.ui_mode === "desktop" && S.cfgSaved.ui_mode !== "desktop") { S.switched = true; }
    if (cfg.web_port !== S.cfgSaved.web_port) toast("Đổi cổng có hiệu lực sau khi khởi động lại", "warning");
    await refreshState();
    renderView(true);
  }

  function pinModal() {
    modal(`<h2>Đổi PIN</h2>
      <div><label>PIN hiện tại</label><input class="input" type="password" id="o"></div>
      <div><label>PIN mới</label><input class="input" type="password" id="n1"></div>
      <div><label>Nhập lại PIN mới</label><input class="input" type="password" id="n2"></div>
      <div class="notice good">${chip("Dữ liệu giữ nguyên — chỉ khoá bọc thay đổi", "good", "shield")}</div>
      <div class="err" id="perr"></div>
      <div class="actions"><button class="btn ghost" id="pc">Huỷ</button><button class="btn primary" id="ps">${icon("key")}Đổi PIN</button></div>`,
    (ov, close) => {
      const err = $("#perr", ov);
      $("#pc", ov).addEventListener("click", close);
      $("#ps", ov).addEventListener("click", async () => {
        const n1 = $("#n1", ov).value;
        if (n1.length < S.st.min_pin) { err.innerHTML = `${icon("alert")}Tối thiểu ${S.st.min_pin} ký tự`; return; }
        if (n1 !== $("#n2", ov).value) { err.innerHTML = `${icon("alert")}Không khớp`; return; }
        try { await api("POST", "/api/pin", { old: $("#o", ov).value, new: n1 }); close(); toast("Đã đổi PIN"); }
        catch (e) { err.innerHTML = `${icon("alert")}${e.status === 403 ? "PIN hiện tại sai" : e.status === 429 ? "Thử lại sau ít phút" : "Không đổi được"}`; }
      });
    });
  }

  // ---------------------------------------------------------------- state & routing
  function render() {
    clearInterval(lockTimer);
    if (S.noToken) return renderNoToken();
    if (S.offline) return renderOffline();
    if (!S.st) { $("#app").innerHTML = ""; return; }
    if (S.st.vault === "uninitialized") return renderSetup();
    if (S.st.vault === "locked") return renderLock();
    if (!$("#view")) renderShell();
    renderView();
  }

  async function refreshState(force) {
    try {
      const st = await api("GET", "/api/state");
      const prev = S.st;
      S.st = st; S.offline = false;
      if (force || !prev || prev.vault !== st.vault) render();
      else {
        updateStatus();
        if (S.view === "dashboard") updateNow();
        if (S.view === "chat") $("#vtools").innerHTML = VIEWS.chat.tools();
      }
    } catch (e) { /* api() already switched to the right screen */ }
  }

  function readHash() {
    const h = location.hash.slice(1);
    const params = new URLSearchParams(h);
    if (params.get("t")) {
      sessionStorage.setItem("wa_token", params.get("t"));
      const v = params.get("v") || "dashboard";
      history.replaceState(null, "", location.pathname + "#" + v);
      return v;
    }
    return VIEWS[h] ? h : "dashboard";
  }

  window.addEventListener("hashchange", () => {
    const v = readHash();
    if (v === S.view) return;
    S.view = v;
    if ($("#view") && S.st && S.st.vault === "unlocked") renderView();
  });

  // tooltip
  document.addEventListener("mousemove", (e) => {
    const tip = $("#tip");
    const t = e.target.closest && e.target.closest("[data-th]");
    if (!t) { tip.classList.add("hidden"); return; }
    tip.innerHTML = `<div class="h">${t.dataset.tc ? `<span class="sw bg-cat c-${esc(t.dataset.tc)}"></span>` : ""}${esc(t.dataset.th)}</div>${t.dataset.ts ? `<div class="s">${esc(t.dataset.ts)}</div>` : ""}`;
    tip.classList.remove("hidden");
    const r = tip.getBoundingClientRect();
    tip.style.left = Math.min(e.clientX + 14, window.innerWidth - r.width - 8) + "px";
    tip.style.top = (e.clientY + 18 + r.height > window.innerHeight ? e.clientY - r.height - 10 : e.clientY + 18) + "px";
  });
  window.addEventListener("beforeunload", (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } });

  S.view = readHash();
  S.token = sessionStorage.getItem("wa_token");
  if (!S.token) { S.noToken = true; render(); return; }
  refreshState(true);
  setInterval(() => { if (!S.noToken && !(S.offline && S.switched)) refreshState(); }, 4000);
  setInterval(() => {
    if (document.hidden || !S.st || S.st.vault !== "unlocked") return;
    if ((S.view === "dashboard" || (S.view === "timeline" && S.date === today())) && !(document.activeElement && document.activeElement.id === "filter")) renderView(true);
  }, 30000);
})();
