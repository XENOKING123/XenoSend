/* XenoSend desktop UI controller. Vanilla JS; talks to Python via pywebview. */
"use strict";

const api = () => (window.pywebview && window.pywebview.api) || null;
const el = (id) => document.getElementById(id);
const clear = (n) => { while (n && n.firstChild) n.removeChild(n.firstChild); };
const h = (tag, attrs = {}, kids = []) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) n.setAttribute(k, v);
  }
  for (const kid of [].concat(kids)) if (kid != null) n.append(kid.nodeType ? kid : document.createTextNode(kid));
  return n;
};

const state = { prefs: { theme: "xeno", display_name: "" }, meta: {}, connected: false, route: "home", trainerQuery: "", trainerOffset: 0, trainerTotal: 0, trainerScope: "all", trainerCollection: "", payloadGroups: [], updateBadge: false };

/* ------------------------------------------------------------- event bus */
const handlers = {};
window.__xenoEvent = (event, payload) => { (handlers[event] || []).forEach((fn) => fn(payload)); };
const on = (event, fn) => { (handlers[event] = handlers[event] || []).push(fn); };

/* --------------------------------------------------------------- toasts */
function toast(msg, kind = "") {
  const t = h("div", { class: `toast ${kind}` }, msg);
  el("toasts").append(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; setTimeout(() => t.remove(), 300); }, 3600);
}

/* ------------------------------------------------------------ navigation */
const NAV = [
  { section: "Main" },
  { id: "home", label: "Home", ico: "🏠" },
  { section: "Xeno", gold: true },
  { id: "trainers", label: "Trainers", ico: "🎯", gold: true },
  { id: "installed", label: "Installed", ico: "💾", gold: true },
  { id: "host", label: "Host/ReLapse", ico: "🔗", gold: true },
  { id: "autoload", label: "Auto-Load", ico: "⚡", gold: true },
  { id: "payloads", label: "Payloads", ico: "📦", gold: true },
  { section: "Install" },
  { id: "pkg", label: "PKG Installer", ico: "💿" },
  { id: "youtube", label: "YouTube", ico: "▶️" },
  { id: "y2jb", label: "Y2JB Backup", ico: "💾" },
  { section: "Setup" },
  { id: "connection", label: "Connection", ico: "🎮" },
  { id: "settings", label: "Settings", ico: "⚙️", badge: () => state.updateBadge ? "●" : "" },
  { id: "about", label: "About", ico: "✨" },
];

function renderNav() {
  const nav = el("nav");
  clear(nav);
  for (const item of NAV) {
    if (item.section) {
      nav.append(h("div", { class: "nav-section" + (item.gold ? " gold" : "") }, item.section));
      continue;
    }
    const badge = item.badge ? item.badge() : "";
    const row = h("div", {
      class: "nav-item" + (item.gold ? " gold" : "") + (state.route === item.id ? " active" : ""),
      onclick: () => go(item.id),
    }, [
      h("span", { class: "ico" }, item.ico),
      h("span", {}, item.label),
      badge ? h("span", { class: "pill" }, badge) : null,
    ]);
    nav.append(row);
  }
}

const TITLES = { home: "Home", trainers: "Trainers", installed: "Installed Games", host: "Host / ReLapse", autoload: "Auto-Loader", payloads: "Payload Library", pkg: "PKG Installer", youtube: "YouTube", y2jb: "Y2JB Backup", connection: "Connection", settings: "Settings", about: "About" };

function go(route) {
  state.route = route;
  el("pageTitle").textContent = TITLES[route] || "XenoSend";
  renderNav();
  const scr = el("screen");
  scr.className = "screen anim-screen" + (route === "home" ? " flush" : "");
  clear(scr);
  (PAGES[route] || PAGES.home)(scr);
  scr.scrollTop = 0;
}

/* --------------------------------------------------------- connection bar */
function conn() { return { ip: el("ipInput").value.trim(), port: el("portInput").value.trim() || String(state.meta.default_port || 9021) }; }
function setConnected(ok, text) {
  state.connected = ok;
  el("connDot").className = "dot" + (ok ? " on" : "");
  el("connStatus").textContent = text || (ok ? "Connected" : "Not connected");
}

async function doDiscover() {
  const { port } = conn();
  setConnected(false, "Searching…");
  el("connStatus").classList.add("pulse");
  const r = await api().discover(port);
  el("connStatus").classList.remove("pulse");
  if (r.ok && r.found) { el("ipInput").value = r.ip; setConnected(true, `PS5 at ${r.ip}`); toast(`Found PS5 at ${r.ip}`, "good"); }
  else if (r.ok) { setConnected(false, "No PS5 found"); toast(`No PS5 on ${r.cidr || "the network"}`, "bad"); }
  else { setConnected(false, "Scan failed"); toast(r.error || "Discovery failed", "bad"); }
}

/* =========================================================== PAGES ======= */
const THEMES = {
  xeno:    { label: "Xeno",    accent: "#459fff", accent2: "#5ad1ff", soft: "#113d70", contrast: "#021018" },
  gold:    { label: "Gold",    accent: "#f4bf3f", accent2: "#ffd873", soft: "#4b3300", contrast: "#1a1206" },
  crimson: { label: "Crimson", accent: "#ff5468", accent2: "#ff8a98", soft: "#5a1420", contrast: "#1a0408" },
  emerald: { label: "Emerald", accent: "#2fd48a", accent2: "#6af0b5", soft: "#0f4a30", contrast: "#02140c" },
  violet:  { label: "Violet",  accent: "#a77bff", accent2: "#c5a8ff", soft: "#34206e", contrast: "#0c0620" },
};
function applyTheme(key) {
  const t = THEMES[key] || THEMES.xeno, root = document.documentElement.style;
  root.setProperty("--accent", t.accent); root.setProperty("--accent-2", t.accent2);
  root.setProperty("--accent-soft", t.soft); root.setProperty("--accent-contrast", t.contrast);
}

const PAGES = {};

PAGES.home = async (scr) => {
  const hero = h("div", { class: "hero" }, [
    h("div", { class: "hero-inner" }, [
      h("h1", {}, "XENOSEND"),
      state.prefs.display_name ? h("div", { style: "color:var(--accent-2);font-weight:600;margin-bottom:6px" }, "Welcome back, " + state.prefs.display_name) : null,
      h("p", {}, "Send payloads and PKGs to your jailbroken PS5, browse thousands of game trainers, and auto-load your cheat stack — all in one place."),
      h("div", { class: "cta" }, [
        h("button", { class: "btn gold big", onclick: () => go("autoload") }, ["⚡ Auto-Load Cheats"]),
        h("button", { class: "btn primary big", onclick: () => go("payloads") }, ["📦 Payload Library"]),
        h("button", { class: "btn big", onclick: () => go("trainers") }, ["🎯 Browse Trainers"]),
      ]),
      h("div", { class: "stat-row", id: "homeStats" }, [
        h("div", { class: "stat gold" }, [h("div", { class: "n" }, "…"), h("div", { class: "l" }, "Trainers")]),
        h("div", { class: "stat" }, [h("div", { class: "n" }, "…"), h("div", { class: "l" }, "Payload sources")]),
        h("div", { class: "stat" }, [h("div", { class: "n" }, "8"), h("div", { class: "l" }, "Languages")]),
      ]),
    ]),
  ]);
  const showcase = h("div", { class: "showcase" }, [
    h("h2", {}, "Featured game trainers"),
    h("div", { class: "marquee-wrap" }, [h("div", { class: "marquee", id: "marquee" }, [h("div", { class: "spinner", style: "margin:70px auto" })])]),
  ]);
  scr.append(hero, showcase);

  const [tr, pl, cov] = await Promise.all([api().list_trainers("", 0, 1), api().list_payloads(), api().showcase_covers(40)]);
  const stats = el("homeStats");
  if (tr.ok) stats.children[0].querySelector(".n").textContent = tr.total.toLocaleString();
  if (pl.ok) stats.children[1].querySelector(".n").textContent = pl.groups.filter((g) => g.repo !== "Local files").length;

  const mq = el("marquee");
  clear(mq);
  const covers = (cov.ok ? cov.covers : []).filter((c) => c.cover);
  if (!covers.length) { mq.append(h("div", { class: "empty" }, "Cover art loads when you're online.")); mq.style.animation = "none"; }
  else {
    const make = (c) => h("img", { class: "cover", src: c.cover, loading: "lazy", title: c.title, onerror: function () { this.style.display = "none"; } });
    [...covers, ...covers].forEach((c) => mq.append(make(c)));
  }
};

const SCOPES = [
  { id: "all", label: "All", ico: "🎮" },
  { id: "favorites", label: "Favorites", ico: "⭐" },
  { id: "custom", label: "My Cheats", ico: "🧩" },
];

PAGES.trainers = async (scr) => {
  const toolbar = h("div", { class: "toolbar" }, [
    h("div", { class: "search" }, [
      h("span", { class: "mag" }, "🔍"),
      h("input", { class: "input", id: "tsearch", placeholder: "Search games — try “Wolverine”", value: state.trainerQuery, oninput: debounce(onSearch, 280) }),
    ]),
    h("div", { class: "count-note", id: "tcount" }, "Loading…"),
    h("button", { class: "btn gold", onclick: () => addCheatsModal() }, ["➕ Add cheats"]),
  ]);
  const scopeRow = h("div", { class: "chips", id: "tscopes", style: "margin-bottom:12px" },
    SCOPES.map((s) => h("div", {
      class: "chip" + (s.id !== "all" ? " gold" : "") + (state.trainerScope === s.id ? " active" : ""),
      onclick: () => setScope(s.id),
    }, [h("span", {}, s.ico), h("span", {}, s.label)])));
  const collRow = h("div", { class: "chips", id: "tcolls", style: "margin-bottom:14px" });
  const grid = h("div", { class: "tgrid", id: "tgrid" });
  const more = h("div", { style: "text-align:center;margin:24px 0" }, [h("button", { class: "btn", id: "tmore", onclick: loadMore }, "Load more")]);
  scr.append(toolbar, scopeRow, collRow, grid, more);
  state.trainerOffset = 0;
  await refreshCollections();
  await loadTrainers(true);

  function onSearch(e) { state.trainerQuery = e.target.value.trim(); state.trainerOffset = 0; loadTrainers(true); }
  async function loadMore() { state.trainerOffset += 60; await loadTrainers(false); }
};

function setScope(scope) {
  state.trainerScope = scope;
  state.trainerOffset = 0;
  if (scope !== "custom") state.trainerCollection = "";
  const row = el("tscopes");
  if (row) [...row.children].forEach((c, i) => c.classList.toggle("active", SCOPES[i].id === scope));
  renderCollections();
  loadTrainers(true);
}

async function refreshCollections() {
  const r = await api().list_collections();
  state.collections = r.ok ? r.collections : [];
  renderCollections();
}

function renderCollections() {
  const row = el("tcolls"); if (!row) return;
  clear(row);
  if (state.trainerScope !== "custom" || !(state.collections || []).length) { row.style.display = "none"; return; }
  row.style.display = "flex";
  const mk = (name, label, count) => h("div", {
    class: "chip" + (state.trainerCollection === name ? " active" : ""),
    onclick: () => { state.trainerCollection = name; state.trainerOffset = 0; renderCollections(); loadTrainers(true); },
  }, count == null ? [label] : [h("span", {}, "📁"), h("span", {}, label), h("span", { class: "n" }, `${count}`)]);
  row.append(mk("", "All", null));
  state.collections.forEach((c) => row.append(mk(c.name, c.name, c.count)));
}

async function loadTrainers(reset) {
  const grid = el("tgrid"); if (!grid) return;
  if (reset) clear(grid);
  const r = await api().list_trainers(state.trainerQuery, state.trainerOffset, 60, state.trainerScope, state.trainerCollection);
  if (!r.ok) { grid.append(h("div", { class: "empty" }, r.error || "Failed to load")); return; }
  state.trainerTotal = r.total;
  el("tcount").textContent = `${r.total.toLocaleString()} game${r.total === 1 ? "" : "s"}`;
  if (!r.rows.length && reset) {
    const msg = state.trainerScope === "favorites" ? "No favorites yet — tap the ☆ on any game."
      : state.trainerScope === "custom" ? "No custom cheats yet — tap “➕ Add cheats”."
      : "No games match that search.";
    grid.append(h("div", { class: "empty" }, msg));
  }
  r.rows.forEach((g, i) => grid.append(trainerCard(g, i)));
  const more = el("tmore");
  if (more) more.style.display = state.trainerOffset + 60 < r.total ? "" : "none";
}

function starButton(g) {
  const btn = h("button", { class: "star" + (g.favorite ? " on" : ""), title: "Favorite",
    onclick: async (e) => {
      e.stopPropagation();
      const res = await api().toggle_favorite(g.id);
      if (res.ok) { g.favorite = res.favorite; btn.className = "star" + (res.favorite ? " on" : ""); btn.textContent = res.favorite ? "★" : "☆";
        if (state.trainerScope === "favorites" && !res.favorite && state.route === "trainers") loadTrainers(true); }
    } }, g.favorite ? "★" : "☆");
  return btn;
}

function trainerCard(g, i) {
  const art = h("div", { class: "art" }, [
    g.cover ? h("img", { src: g.cover, loading: "lazy", onerror: function () { this.replaceWith(h("div", { class: "ph" }, (g.title || "?")[0])); } }) : h("div", { class: "ph" }, (g.title || "?")[0]),
    starButton(g),
    g.cheats_total ? h("span", { class: "badge gold n" }, `${g.cheats_total}`) : null,
    g.custom ? h("span", { class: "badge gold cust" }, "CUSTOM") : null,
  ]);
  const fm = h("div", { class: "fm" }, (g.formats || []).map((f) => h("span", { class: `badge ${f}` }, f.toUpperCase())));
  return h("div", { class: "tcard", style: `animation-delay:${Math.min(i, 12) * 18}ms`, onclick: () => trainerModal(g) }, [
    art, h("div", { class: "meta" }, [h("div", { class: "t" }, g.title), h("div", { class: "i" }, g.custom && g.author ? "by " + g.author : g.id), fm]),
  ]);
}

function trainerModal(g) {
  const body = h("div", { class: "mbody" });
  const metaRow = h("div", { class: "row", style: "gap:8px;flex-wrap:wrap;margin-bottom:6px" }, [
    ...(g.formats || []).map((f) => h("span", { class: `badge ${f}` }, f.toUpperCase())),
    g.version ? h("span", { class: "badge" }, "v" + g.version) : null,
    g.author ? h("span", { class: "badge" }, "by " + g.author) : null,
    g.collection ? h("span", { class: "badge gold" }, "📁 " + g.collection) : null,
  ]);

  // static cheat list (default) — attach swaps this for live toggles
  const cheatBox = h("div", {});
  const renderStatic = () => {
    clear(cheatBox);
    cheatBox.append(h("h3", { style: "margin:14px 0 2px" }, `Cheats (${g.cheats_total})`));
    if (g.cheats && g.cheats.length) cheatBox.append(h("ul", { class: "cheat-list" }, g.cheats.map((c) => h("li", {}, c))));
    else cheatBox.append(h("div", { class: "empty", style: "padding:20px" }, "Cheat names load on-console once attached."));
  };
  renderStatic();

  const status = h("div", { style: "font-size:12px;color:var(--muted);margin:6px 0 2px;min-height:16px" }, "");
  const setStatus = (t, c) => { status.textContent = t; status.style.color = c || "var(--muted)"; };

  const renderLive = (cheats) => {
    clear(cheatBox);
    cheatBox.append(h("h3", { style: "margin:14px 0 2px" }, `Live cheats (${cheats.length})`));
    cheats.forEach((c) => {
      const sw = h("div", { class: "sw" + (c.enabled ? " on" : "") });
      const dot = h("div", { class: "live-dot" + (c.enabled ? " on" : "") });
      sw.addEventListener("click", async () => {
        const next = !sw.classList.contains("on");
        sw.classList.toggle("on", next); dot.classList.toggle("on", next);
        const res = await api().toggle_trainer_cheat(conn().ip, g.id, c.index, next);
        if (!res.ok) { sw.classList.toggle("on", !next); dot.classList.toggle("on", !next); setStatus(res.error, "var(--bad)"); }
        else if (res.cheats) renderLive(res.cheats);
      });
      cheatBox.append(h("div", { class: "live-row" }, [dot, h("div", { class: "t" }, c.name || `#${c.index}`), sw]));
    });
    const dis = h("button", { class: "btn", style: "margin-top:6px", onclick: async () => {
      const res = await api().disable_all_trainer(conn().ip, g.id);
      if (res.ok && res.cheats) { renderLive(res.cheats); setStatus("All cheats disabled.", "var(--good)"); }
      else setStatus(res.error || "Failed", "var(--bad)");
    } }, "Disable all");
    cheatBox.append(dis);
  };

  const attachBtn = h("button", { class: "btn gold", onclick: async () => {
    if (!conn().ip) { toast("Set your PS5 IP first", "bad"); return; }
    attachBtn.disabled = true; setStatus("Attaching to CheatRunner…");
    const res = await api().attach_trainer(conn().ip, g.id);
    attachBtn.disabled = false;
    if (!res.ok) { setStatus(res.error, "var(--bad)"); return; }
    if (!res.cheats.length) { setStatus(res.message || "Attached, no cheats returned.", "var(--warn)"); return; }
    setStatus((res.launched ? "Launched & attached • " : "Attached • ") + res.cheats.length + " cheats", "var(--good)");
    renderLive(res.cheats);
    detachBtn.style.display = "";
  } }, "⚡ Attach & toggle live");
  const detachBtn = h("button", { class: "btn", style: "display:none", onclick: () => { renderStatic(); setStatus("Detached."); detachBtn.style.display = "none"; } }, "Detach");

  // added cheat files for this game
  const filesBox = h("div", { style: "margin-top:16px" });
  const renderFiles = async () => {
    clear(filesBox);
    filesBox.append(h("div", { class: "row", style: "justify-content:space-between" }, [
      h("h3", { style: "margin:0;font-size:14px" }, "Your added cheat files"),
      h("button", { class: "btn", style: "padding:6px 12px", onclick: addFile }, "📎 Add file"),
    ]));
    const r = await api().trainer_files(g.id);
    const files = r.ok ? r.files : [];
    if (!files.length) { filesBox.append(h("div", { style: "color:var(--muted);font-size:12px;margin-top:8px" }, "Drop a .json/.shn/.mc4 cheat file here for this game.")); return; }
    files.forEach((f) => filesBox.append(h("div", { class: "file-chip", style: "display:flex;width:100%;margin-top:8px" }, [
      h("span", {}, f.format.toUpperCase()),
      h("span", { style: "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" }, f.name + (f.cheats && f.cheats.length ? ` · ${f.cheats.length} cheats` : "")),
      h("button", { class: "btn", style: "padding:4px 10px", onclick: () => { api().upload_trainer_file_to_console(conn().ip, g.id, f.name); toast("Uploading " + f.name + "…"); } }, "⬆ PS5"),
      h("span", { class: "x", onclick: async () => { await api().remove_trainer_file(g.id, f.name); renderFiles(); } }, "✕"),
    ])));
  };
  async function addFile() {
    const picked = await api().pick_file("cheat");
    if (!picked.ok || picked.cancelled || !picked.path) return;
    const res = await api().add_trainer_file(g.id, picked.path);
    if (res.ok) { toast("Added " + res.file.name, "good"); renderFiles(); } else toast(res.error, "bad");
  }
  renderFiles();

  body.append(metaRow, h("div", { class: "row", style: "gap:8px;margin:10px 0 2px" }, [attachBtn, detachBtn]), status, cheatBox, filesBox);
  openModal(g.title, g.custom && g.author ? "by " + g.author : g.id, g.cover, body);
}

function addCheatsModal(targetId) {
  const colls = (state.collections || []).map((c) => c.name);
  const form = h("div", { class: "form" });
  const field = (label, node) => h("div", {}, [h("label", {}, label), node]);
  const titleIn = h("input", { class: "input", placeholder: "Game or trainer name" });
  const authorIn = h("input", { class: "input", placeholder: "Your name / original author" });
  const collIn = h("input", { class: "input", placeholder: "New or existing collection (optional)", list: "coll-list" });
  const collList = h("datalist", { id: "coll-list" }, colls.map((c) => h("option", { value: c })));
  const cheatsIn = h("textarea", { class: "input", placeholder: "One cheat name per line (optional)" });
  const targetIn = h("input", { class: "input", placeholder: "Target title id, e.g. PPSA03671 (optional)", value: targetId || "" });

  let imagePath = "", cheatPath = "";
  const imgLabel = h("span", { class: "path" }, "No image chosen");
  const cheatLabel = h("span", { class: "path" }, "No cheat file chosen");
  const pickImg = h("button", { class: "btn", onclick: async () => { const r = await api().pick_file("image"); if (r.ok && r.path) { imagePath = r.path; imgLabel.textContent = r.path.split(/[\\/]/).pop(); } } }, "🖼 Image");
  const pickCheat = h("button", { class: "btn", onclick: async () => { const r = await api().pick_file("cheat"); if (r.ok && r.path) { cheatPath = r.path; cheatLabel.textContent = r.path.split(/[\\/]/).pop(); } } }, "📎 Cheat file");

  form.append(
    field("Title *", titleIn),
    field("Author", authorIn),
    field("Collection", h("div", {}, [collIn, collList])),
    field("Cheats", cheatsIn),
    field("Cover image", h("div", { class: "pick-row" }, [pickImg, imgLabel])),
    field("Import cheat file (.json/.shn/.mc4)", h("div", { class: "pick-row" }, [pickCheat, cheatLabel])),
    field("Attach to game (optional)", targetIn),
  );
  const save = h("button", { class: "btn gold big", onclick: async () => {
    const title = titleIn.value.trim();
    if (!title) { toast("A title is required", "bad"); return; }
    save.disabled = true;
    const res = await api().add_custom_cheats({
      title, author: authorIn.value.trim(), collection: collIn.value.trim(),
      target_id: targetIn.value.trim(), cheats: cheatsIn.value, image: imagePath, cheat_file: cheatPath,
    });
    save.disabled = false;
    if (!res.ok) { toast(res.error, "bad"); return; }
    toast("Added “" + title + "”", "good");
    scrim.remove();
    await refreshCollections();
    if (state.route === "trainers") loadTrainers(true);
  } }, "💾 Save to library");
  form.append(h("div", { style: "margin-top:6px" }, save));

  const scrim = openSheet("➕ Add cheats", form);
}

PAGES.host = async (scr) => {
  const statusBox = h("div", { id: "hostStatusBox", style: "margin-bottom:24px" });
  const startBtn = h("button", { class: "btn gold big", id: "hostStart", onclick: () => startHost() }, "▶ Start host server");
  const stopBtn = h("button", { class: "btn big", id: "hostStop", style: "display:none", onclick: () => stopHost() }, "■ Stop");
  const btnRow = h("div", { class: "row", style: "gap:8px;margin-bottom:20px" }, [startBtn, stopBtn]);

  scr.append(h("div", { class: "toolbar" }, [
    h("div", { style: "flex:1" }, [
      h("div", { style: "font-size:14px;color:var(--muted)" }, "Run a local exploit host on your network. PS5 reaches your PC's IP and runs the bundled ReLapse payload."),
    ]),
  ]));

  scr.append(statusBox, btnRow, h("div", { class: "card", id: "hostInfo", style: "display:none" }, [
    h("h3", {}, "🔗 Connected"),
    h("div", { id: "hostConnInfo" }),
  ]));

  await updateHostStatus();
  clearInterval(state.hostTimer);
  state.hostTimer = setInterval(() => { if (state.route === "host") updateHostStatus(); else clearInterval(state.hostTimer); }, 2000);

  async function updateHostStatus() {
    const r = await api().host_status();
    if (!r.ok) return;
    const sb = el("hostStatusBox");
    if (!sb) return;
    clear(sb);
    const stBg = r.running ? "var(--good)" : "var(--muted)";
    const stTxt = r.running ? "RUNNING" : "STOPPED";
    sb.append(h("div", { style: `display:flex;gap:8px;align-items:center;padding:14px;background:var(--surface-3);border-radius:12px;border:1px solid var(--border)` }, [
      h("span", { style: `width:14px;height:14px;border-radius:50%;background:${stBg};box-shadow:0 0 8px ${stBg}` }),
      h("div", { style: "flex:1" }, [
        h("div", { style: "font-size:14px;font-weight:600" }, stTxt),
        r.running ? h("div", { style: "font-size:12px;color:var(--muted);margin-top:3px" }, r.endpoint || r.host_label) : null,
        r.client_ip ? h("div", { style: "font-size:12px;color:var(--good);margin-top:4px" }, "PS5 connected: " + r.client_ip) : null,
      ]),
    ]));
    el("hostStart").style.display = r.running ? "none" : "";
    el("hostStop").style.display = r.running ? "" : "none";
    const inf = el("hostInfo");
    if (inf) inf.style.display = r.client_ip ? "" : "none";
    if (r.client_ip) {
      clear(el("hostConnInfo"));
      el("hostConnInfo").append(h("div", { style: "font-size:13px;line-height:1.6" }, [
        h("div", {}, "🎮 PS5 IP: " + r.client_ip),
        h("div", { style: "margin-top:6px;color:var(--muted)" }, "The console is currently connected to your host server. Payloads and exploits are available to the PS5."),
      ]));
    }
  }

  async function startHost() {
    const b = el("hostStart");
    b.disabled = true;
    b.textContent = "Starting…";
    await api().host_start();
  }

  async function stopHost() {
    const b = el("hostStop");
    b.disabled = true;
    b.textContent = "Stopping…";
    await api().host_stop();
  }
};

PAGES.youtube = async (scr) => {
  scr.append(h("div", { class: "toolbar" }, [
    h("div", { style: "flex:1;font-size:14px;color:var(--muted)" }, "Install a YouTube app update on your PS5, then activate the signed-in account. Set your PS5 in Connection first."),
    h("button", { class: "btn gold", onclick: () => { const { ip, port } = conn(); if (!ip) { toast("Set your PS5 IP first", "bad"); return; } toast("Activating account…"); api().activate_youtube_account(ip, port); } }, "🔑 Activate account"),
  ]));
  const wrap = h("div", { id: "ytWrap" });
  scr.append(wrap);
  const r = await api().list_youtube_updates();
  if (!r.ok || !r.rows.length) { wrap.append(h("div", { class: "empty" }, r.error || "No updates available.")); return; }
  wrap.append(h("div", { class: "lib-list" }, r.rows.map((it) => h("div", { class: "lib-item" }, [
    h("div", { class: "ic" }, "▶️"),
    h("div", { class: "nm" }, [h("div", { class: "t" }, it.label), it.version ? h("div", { class: "v" }, it.version) : null]),
    h("button", { class: "btn primary", style: "padding:7px 14px", onclick: () => { const { ip, port } = conn(); if (!ip) { toast("Set your PS5 IP first", "bad"); return; } toast("Installing " + it.label + "…"); api().install_youtube_update(it.key, ip, port); } }, "Install"),
  ]))));
};

PAGES.y2jb = async (scr) => {
  scr.append(h("div", { class: "toolbar" }, [h("div", { style: "font-size:14px;color:var(--muted)" }, "Back up Y2JB to a USB drive. Pick the variant that matches your firmware.")]));
  const wrap = h("div", {});
  scr.append(wrap);
  const r = await api().list_y2jb_variants();
  if (!r.ok || !r.rows.length) { wrap.append(h("div", { class: "empty" }, r.error || "No variants available.")); return; }
  wrap.append(h("div", { class: "lib-list" }, r.rows.map((v) => h("div", { class: "lib-item" }, [
    h("div", { class: "ic" }, "💾"),
    h("div", { class: "nm" }, [h("div", { class: "t" }, v.firmware + " · " + v.package), v.version ? h("div", { class: "v" }, v.version) : null]),
    h("button", { class: "btn primary", style: "padding:7px 14px", onclick: () => { toast("Running backup…"); api().run_y2jb_backup(v.key); } }, "Run backup"),
  ]))));
};

PAGES.installed = async (scr) => {
  scr.append(h("div", { class: "toolbar" }, [
    h("div", { style: "flex:1;font-size:14px;color:var(--muted)" }, "Games CheatRunner sees installed on your PS5. Attach one to toggle its cheats live."),
    h("button", { class: "btn primary", id: "instRefresh", onclick: () => loadInstalled() }, "🔄 Refresh"),
  ]));
  scr.append(h("div", { id: "instWrap" }, [h("div", { class: "spinner", style: "margin:60px auto" })]));
  await loadInstalled();
};

async function loadInstalled() {
  const wrap = el("instWrap"); if (!wrap) return;
  clear(wrap); wrap.append(h("div", { class: "spinner", style: "margin:60px auto" }));
  if (!conn().ip) { clear(wrap); wrap.append(h("div", { class: "empty" }, "Set your PS5 IP in Connection, then Refresh.")); return; }
  const r = await api().list_installed_games(conn().ip);
  clear(wrap);
  if (!r.ok) {
    wrap.append(h("div", { class: "empty" }, (r.unreachable ? "CheatRunner isn't running on your PS5 yet — send it from Auto-Load or Payloads first. " : "") + (r.error || "")));
    return;
  }
  if (!r.rows.length) { wrap.append(h("div", { class: "empty" }, "No installed games reported.")); return; }
  r.rows.forEach((g) => {
    const row = h("div", { class: "inst-row" }, [
      starButton(g),
      h("div", { class: "nm" }, [
        h("div", { class: "t" }, [g.running ? h("span", { class: "dotled run" }) : null, g.title].filter(Boolean)),
        h("div", { class: "i" }, g.id + (g.version ? " · v" + g.version : "")),
      ]),
      g.is_app ? h("span", { class: "badge" }, "APP") : null,
      g.has_cheat ? h("span", { class: "badge gold" }, "CHEATS") : h("span", { class: "badge" }, "no cheats"),
      g.added_files ? h("span", { class: "badge json" }, `${g.added_files} added`) : null,
      h("button", { class: "btn primary", style: "padding:7px 14px", onclick: () => trainerModal({
        id: g.id, title: g.title, version: g.version, cheats_total: 0, cheats: [], creators: [],
        formats: [], cover: g.cover, favorite: g.favorite, custom: false, author: "",
      }) }, "Open"),
    ]);
    wrap.append(row);
  });
}

PAGES.payloads = async (scr) => {
  const bar = h("div", { class: "toolbar" }, [
    h("div", { style: "flex:1" }, [h("div", { style: "font-size:14px;color:var(--muted)" }, "ELF / BIN payloads grouped by GitHub source. Pick one and send it to your PS5.")]),
    h("button", { class: "btn", onclick: () => api().open_payload_folder().then((r) => r.ok ? toast("Opened " + r.path) : toast(r.error, "bad")) }, "📁 Local folder"),
    h("button", { class: "btn primary", id: "checkUpd", onclick: checkPayloadUpdates }, ["🔄 Check for updates"]),
  ]);
  const wrap = h("div", { id: "libWrap" }, [h("div", { class: "spinner", style: "margin:60px auto" })]);
  scr.append(bar, wrap);
  await loadPayloads();

  async function checkPayloadUpdates() {
    const btn = el("checkUpd"); btn.disabled = true; btn.textContent = "Checking…";
    await api().check_payload_updates();
  }
};

async function loadPayloads() {
  const wrap = el("libWrap"); if (!wrap) return;
  const r = await api().list_payloads();
  clear(wrap);
  if (!r.ok) { wrap.append(h("div", { class: "empty" }, r.error || "Failed")); return; }
  state.payloadGroups = r.groups;
  for (const g of r.groups) {
    const items = h("div", { class: "lib-list" }, g.items.map((it) => h("div", { class: "lib-item" }, [
      h("div", { class: "ic" }, it.kind === "local" ? "📄" : "📦"),
      h("div", { class: "nm" }, [h("div", { class: "t" }, it.label), it.version ? h("div", { class: "v" }, it.version) : null]),
      h("button", { class: "btn primary", style: "padding:7px 14px", onclick: () => sendPayload(it) }, "Send"),
    ])));
    wrap.append(h("div", { class: "lib-group" }, [
      h("div", { class: "ghead" }, [
        h("span", {}, g.repo === "Local files" ? "📁" : "🐙"),
        h("span", { class: "repo" }, g.repo),
        h("span", { class: "cnt" }, `${g.items.length} payload${g.items.length === 1 ? "" : "s"}`),
      ]),
      items,
    ]));
  }
}

function sendPayload(it) {
  const { ip, port } = conn();
  if (!ip) { toast("Enter or discover your PS5 IP first", "bad"); go("connection"); return; }
  toast(`Sending ${it.label}…`);
  api().send_payload(it.key, ip, port);
}

PAGES.autoload = async (scr) => {
  const card = h("div", { class: "card autoload-card" }, [
    h("div", { class: "glyph" }, "⚡"),
    h("h3", { style: "font-size:20px;margin:10px 0 2px" }, "Auto-Loader"),
    h("p", { class: "sub" }, "Sends kstuff, then CheatRunner, in the right order with the right timing — your whole cheat stack in one tap."),
    h("div", { class: "steps", id: "alSteps" }, [stepEl(1, "kstuff"), stepEl(2, "CheatRunner")]),
    h("div", { class: "progress" }, [h("div", { class: "bar", id: "alBar" })]),
    h("div", { id: "alMsg", style: "margin-top:12px;color:var(--muted);font-size:13px;min-height:18px" }, ""),
    h("div", { style: "margin-top:20px" }, [h("button", { class: "btn gold big", id: "alRun", onclick: runAutoload }, "⚡ Run Auto-Load")]),
  ]);
  scr.append(h("div", { style: "max-width:560px;margin:10px auto" }, card));

  function stepEl(n, label) { return h("div", { class: "step", id: "alStep" + n }, [h("span", { class: "n" }, String(n)), h("span", {}, label)]); }
  function runAutoload() {
    const { ip, port } = conn();
    if (!ip) { toast("Enter or discover your PS5 IP first", "bad"); go("connection"); return; }
    el("alRun").disabled = true;
    el("alBar").style.width = "0";
    [1, 2].forEach((n) => el("alStep" + n).className = "step");
    el("alMsg").textContent = "Starting…";
    api().auto_load(ip, port);
  }
};

PAGES.pkg = async (scr) => {
  const bar = h("div", { class: "toolbar" }, [
    h("div", { style: "flex:1" }, [h("div", { style: "font-size:14px;color:var(--muted)" }, "PS5 packages grouped by source. Installing sends kstuff first, then the package — set your PS5 in Connection.")]),
    h("button", { class: "btn", onclick: () => api().open_pkg_folder().then((r) => r.ok ? toast("Opened " + r.path) : toast(r.error, "bad")) }, "📁 Local folder"),
    h("button", { class: "btn primary", id: "pkgUpd", onclick: checkPkgUpdates }, ["🔄 Check for updates"]),
  ]);
  const wrap = h("div", { id: "pkgWrap" }, [h("div", { class: "spinner", style: "margin:60px auto" })]);
  scr.append(bar, wrap);
  await loadPkgs();
  async function checkPkgUpdates() { const b = el("pkgUpd"); b.disabled = true; b.textContent = "Checking…"; await api().check_pkg_updates(); }
};

async function loadPkgs() {
  const wrap = el("pkgWrap"); if (!wrap) return;
  const r = await api().list_pkgs();
  clear(wrap);
  if (!r.ok) { wrap.append(h("div", { class: "empty" }, r.error || "Failed")); return; }
  if (!r.groups.length) { wrap.append(h("div", { class: "empty" }, "No packages available.")); return; }
  for (const g of r.groups) {
    const items = h("div", { class: "lib-list" }, g.items.map((it) => h("div", { class: "lib-item" }, [
      h("div", { class: "ic" }, it.kind === "local" ? "📄" : "💿"),
      h("div", { class: "nm" }, [h("div", { class: "t" }, it.label), it.version ? h("div", { class: "v" }, it.version) : null]),
      h("button", { class: "btn primary", style: "padding:7px 14px", onclick: () => installPkg(it) }, "Install"),
    ])));
    wrap.append(h("div", { class: "lib-group" }, [
      h("div", { class: "ghead" }, [h("span", {}, g.repo === "Local files" ? "📁" : "🐙"), h("span", { class: "repo" }, g.repo), h("span", { class: "cnt" }, `${g.items.length} package${g.items.length === 1 ? "" : "s"}`)]),
      items,
    ]));
  }
}

function installPkg(it) {
  const { ip, port } = conn();
  if (!ip) { toast("Enter or discover your PS5 IP first", "bad"); go("connection"); return; }
  toast(`Installing ${it.label}…`);
  api().install_pkg(it.key, ip, port);
}

PAGES.connection = async (scr) => {
  const card = h("div", { class: "card", style: "max-width:520px;margin:10px auto" }, [
    h("h3", {}, "🎮 Connect to your PS5"),
    h("p", { class: "sub" }, "Your PS5 and this PC must be on the same network. Auto-discover scans your subnet for the payload port."),
    h("label", { style: "display:block;font-size:13px;color:var(--muted);margin:10px 0 4px" }, "PS5 IP address"),
    h("input", { class: "input", id: "connIp", placeholder: "192.168.x.x", value: el("ipInput").value, spellcheck: "false" }),
    h("label", { style: "display:block;font-size:13px;color:var(--muted);margin:14px 0 4px" }, "Payload port"),
    h("input", { class: "input", id: "connPort", value: el("portInput").value || String(state.meta.default_port || 9021), spellcheck: "false" }),
    h("div", { class: "row", style: "margin-top:20px;gap:10px" }, [
      h("button", { class: "btn primary", onclick: () => { el("ipInput").value = el("connIp").value.trim(); el("portInput").value = el("connPort").value.trim(); doDiscover(); } }, "🔍 Auto-discover"),
      h("button", { class: "btn", onclick: () => { el("ipInput").value = el("connIp").value.trim(); el("portInput").value = el("connPort").value.trim(); const ip = el("connIp").value.trim(); setConnected(!!ip, ip ? "Set to " + ip : ""); toast("Saved", "good"); } }, "Save"),
    ]),
  ]);
  scr.append(card);
};

PAGES.settings = async (scr) => {
  scr.append(h("div", { class: "card", style: "max-width:560px;margin:10px auto" }, [
    h("h3", {}, "⚙️ Settings"),
    h("div", { class: "row", style: "justify-content:space-between;margin-top:14px;padding:12px 0;border-bottom:1px solid var(--border)" }, [
      h("div", {}, [h("div", {}, "Version"), h("div", { style: "color:var(--muted);font-size:12px" }, "XenoSend " + (state.meta.version || ""))]),
      h("button", { class: "btn", id: "updBtn", onclick: () => { el("updBtn").textContent = "Checking…"; api().check_app_update(); } }, "Check for updates"),
    ]),
    h("div", { style: "padding:14px 0;border-bottom:1px solid var(--border)" }, [
      h("div", { style: "margin-bottom:8px" }, "Display name"),
      h("input", { class: "input", id: "prefName", maxlength: "24", placeholder: "Shown on the Home screen", value: state.prefs.display_name }),
    ]),
    h("div", { style: "padding:14px 0" }, [
      h("div", { style: "margin-bottom:10px" }, "Colour theme"),
      h("div", { class: "chips", id: "prefThemes" }, Object.keys(THEMES).map((k) => h("div", {
        class: "chip" + (state.prefs.theme === k ? " active" : ""), "data-theme": k,
        onclick: () => { state.prefs.theme = k; applyTheme(k); [...el("prefThemes").children].forEach((c) => c.classList.toggle("active", c.dataset.theme === k)); },
      }, [h("span", { style: `width:10px;height:10px;border-radius:50%;background:${THEMES[k].accent}` }), h("span", {}, THEMES[k].label)]))),
    ]),
    h("button", { class: "btn gold", onclick: async () => {
      state.prefs.display_name = el("prefName").value.trim();
      const r = await api().set_prefs(state.prefs.theme, state.prefs.display_name);
      if (r.ok) { state.prefs.display_name = r.display_name; toast("Saved", "good"); } else toast(r.error, "bad");
    } }, "💾 Save"),
  ]));
};

PAGES.about = async (scr) => {
  scr.append(h("div", { class: "card", style: "max-width:560px;margin:10px auto;text-align:center" }, [
    h("img", { src: "../../assets/xeno/brand/xeno_icon_256.png", style: "width:84px;border-radius:18px", onerror: function () { this.style.display = "none"; } }),
    h("h3", { style: "margin-top:14px;font-size:20px" }, "XenoSend"),
    h("p", { class: "sub" }, "v" + (state.meta.version || "") + " · PS5 payload / PKG sender with a built-in trainer library and auto-loader."),
    h("p", { style: "color:var(--muted);font-size:13px" }, "A rebuilt and extended PS5 companion, based on sendpp."),
  ]));
};

/* ------------------------------------------------------------------ modal */
function openModal(title, id, cover, bodyNode) {
  const scrim = h("div", { class: "scrim", onclick: (e) => { if (e.target === scrim) scrim.remove(); } }, [
    h("div", { class: "modal" }, [
      h("button", { class: "close", onclick: () => scrim.remove() }, "✕"),
      h("div", { class: "mhead" }, [
        cover ? h("img", { src: cover, onerror: function () { this.style.display = "none"; } }) : null,
        h("div", { class: "fade" }),
        h("div", { class: "ttl" }, [h("h2", {}, title), h("div", { class: "id" }, id)]),
      ]),
      bodyNode,
    ]),
  ]);
  document.body.append(scrim);
  const onKey = (e) => { if (e.key === "Escape") { scrim.remove(); document.removeEventListener("keydown", onKey); } };
  document.addEventListener("keydown", onKey);
}

function openSheet(title, bodyNode) {
  const scrim = h("div", { class: "scrim", onclick: (e) => { if (e.target === scrim) scrim.remove(); } }, [
    h("div", { class: "modal" }, [
      h("button", { class: "close", onclick: () => scrim.remove() }, "✕"),
      h("div", { class: "mbody" }, [h("h3", { style: "margin:0 0 14px;font-size:18px" }, title), bodyNode]),
    ]),
  ]);
  document.body.append(scrim);
  const onKey = (e) => { if (e.key === "Escape") { scrim.remove(); document.removeEventListener("keydown", onKey); } };
  document.addEventListener("keydown", onKey);
  return scrim;
}

/* ------------------------------------------------------------- utilities */
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

/* ----------------------------------------------------------- event wiring */
on("send:progress", (p) => { if (state.route === "payloads") toast(p.message + (p.percent != null ? ` ${p.percent}%` : "")); });
on("send:done", (p) => toast(`✅ Sent ${p.label} (${(p.bytes / 1024 | 0)} KB)`, "good"));
on("send:error", (p) => toast("❌ " + p.error, "bad"));
on("payloads:updated", () => { const b = el("checkUpd"); if (b) { b.disabled = false; b.textContent = "🔄 Check for updates"; } if (state.route === "payloads") loadPayloads(); toast("Payload sources refreshed", "good"); });
on("payloads:error", (p) => { const b = el("checkUpd"); if (b) { b.disabled = false; b.textContent = "🔄 Check for updates"; } toast(p.error, "bad"); });
on("autoload:step", (p) => { const s = el("alStep" + p.index); if (s) s.className = "step active"; if (p.index > 1) { const prev = el("alStep" + (p.index - 1)); if (prev) prev.className = "step done"; } const bar = el("alBar"); if (bar) bar.style.width = `${(p.index - 1) / p.total * 100}%`; const m = el("alMsg"); if (m) m.textContent = `Sending ${p.label} (${p.index}/${p.total})…`; });
on("autoload:progress", (p) => { const m = el("alMsg"); if (m && p.message) m.textContent = p.message + (p.percent != null ? ` ${p.percent}%` : ""); });
on("autoload:done", () => { [1, 2].forEach((n) => { const s = el("alStep" + n); if (s) s.className = "step done"; }); const bar = el("alBar"); if (bar) bar.style.width = "100%"; const m = el("alMsg"); if (m) m.textContent = "Done — cheats loaded."; const b = el("alRun"); if (b) b.disabled = false; toast("⚡ Auto-Load complete", "good"); });
on("autoload:error", (p) => { const m = el("alMsg"); if (m) m.textContent = "Failed: " + p.error; const b = el("alRun"); if (b) b.disabled = false; toast("❌ " + p.error, "bad"); });
on("appupdate:available", (p) => { state.updateBadge = true; renderNav(); const b = el("updBtn"); if (b) b.textContent = "Update " + p.version + " available"; toast("🎉 Update " + p.version + " available", "good"); });
on("appupdate:none", () => { const b = el("updBtn"); if (b) b.textContent = "Up to date"; toast("You're on the latest version", "good"); });
on("appupdate:error", () => { const b = el("updBtn"); if (b) b.textContent = "Check for updates"; });
on("cheatfile:uploaded", (p) => toast("✅ Uploaded " + p.name + " to PS5", "good"));
on("cheatfile:error", (p) => toast("❌ " + (p.error || "Upload failed"), "bad"));
on("pkg:progress", (p) => { if (state.route === "pkg") toast(p.message + (p.percent != null ? ` ${p.percent}%` : "")); });
on("pkg:done", (p) => toast(`✅ Installed ${p.label}`, "good"));
on("pkg:error", (p) => toast("❌ " + p.error, "bad"));
on("pkg:updated", () => { const b = el("pkgUpd"); if (b) { b.disabled = false; b.textContent = "🔄 Check for updates"; } if (state.route === "pkg") loadPkgs(); toast("PKG sources refreshed", "good"); });
on("host:started", (p) => { if (state.route === "host") { const b = el("hostStart"); if (b) b.disabled = false; } toast("✅ Host started: " + (p.endpoint || "running"), "good"); });
on("host:stopped", () => { if (state.route === "host") { const b = el("hostStart"); if (b) b.disabled = false; } toast("Host stopped", "good"); });
on("youtube:progress", (p) => toast(p.message + (p.percent != null ? ` ${p.percent}%` : "")));
on("youtube:done", (p) => toast("✅ Installed " + p.label, "good"));
on("youtube:activated", () => toast("✅ Account activated", "good"));
on("youtube:error", (p) => toast("❌ " + p.error, "bad"));
on("y2jb:progress", (p) => toast(p.message + (p.percent != null ? ` ${p.percent}%` : "")));
on("y2jb:done", (p) => toast("✅ Backup copied to " + p.usb_path, "good"));
on("y2jb:error", (p) => toast("❌ " + p.error, "bad"));
on("host:error", (p) => toast("❌ " + p.error, "bad"));

/* ------------------------------------------------------------------ boot */
let booted = false;
async function boot() {
  if (booted) return;
  const a = api();
  if (!a) { setTimeout(boot, 60); return; }
  booted = true;
  const meta = await a.get_meta();
  if (meta.ok) { state.meta = meta; el("brandVer").textContent = "v" + meta.version; }
  const pr = await a.get_prefs();
  if (pr.ok) { state.prefs = { theme: pr.theme, display_name: pr.display_name }; applyTheme(pr.theme); }
  const c = await a.get_connection();
  if (c.ok && c.ip) { el("ipInput").value = c.ip; setConnected(true, c.ip); }
  if (c.ok) el("portInput").value = String(c.port || meta.default_port || 9021);
  el("discoverBtn").addEventListener("click", doDiscover);
  renderNav();
  go("home");
  a.check_app_update();
  setTimeout(() => { const s = el("splash"); if (s) { s.style.opacity = "0"; } el("app").style.display = "flex"; setTimeout(() => s && s.remove(), 420); }, 1400);
}

window.addEventListener("pywebviewready", boot);
document.addEventListener("DOMContentLoaded", () => setTimeout(boot, 400));
