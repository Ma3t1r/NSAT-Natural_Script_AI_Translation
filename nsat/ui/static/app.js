/* NSAT Studio 前端逻辑 */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const state = {
  root: "",
  files: [],
  tabs: new Map(),     // path -> {el, host, editor, dirty, savedValue}
  activePath: null,
  jobId: null,
  chatHistory: [],
  openFiles: [],
};

/* ---------------- 会话记忆（记住上次项目/文件） ---------------- */
let _sessionTimer = null;
function scheduleSessionSave() {
  clearTimeout(_sessionTimer);
  _sessionTimer = setTimeout(saveSession, 500);
}

function saveSession() {
  api("/api/session", "POST", { root: state.root, files: state.openFiles.slice(0, 20) }).catch(() => {});
}

function recordOpen(path) {
  state.openFiles = [path, ...state.openFiles.filter((p) => p !== path)].slice(0, 20);
  scheduleSessionSave();
}

async function restoreSession() {
  try {
    const r = await api("/api/session");
    const s = r.session || {};
    if (!s.root) return;
    const res = await api(`/api/project?root=${encodeURIComponent(s.root)}`);
    if (!res.ok) return;
    state.root = res.root;
    state.files = res.files;
    $("#st-root").textContent = res.root;
    renderTree();
    log(`已恢复上次项目: ${res.root}`);
    for (const f of s.files || []) {
      openFile(f).catch(() => {});
    }
  } catch (e) { /* 静默 */ }
}

/* ---------------- API ---------------- */
async function api(path, method = "GET", body = null) {
  const opt = { method, headers: {} };
  if (body !== null) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const res = await fetch(path, opt);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${path}`);
  return data;
}

/* ---------------- 通用对话框 ---------------- */
let _modalResolve = null;
function modal(html) {
  $("#modal-box").innerHTML = html;
  $("#modal-mask").classList.remove("hidden");
  return new Promise((resolve) => { _modalResolve = resolve; });
}
function modalResolve(data) { $("#modal-mask").classList.add("hidden"); _modalResolve && _modalResolve(data); }

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function respond(payload) {
  if (!state.jobId) return;
  await api(`/api/jobs/${state.jobId}/respond`, "POST", payload);
}

async function showAsk(ev) {
  switch (ev.type) {
    case "ask_logic_issues": return showAskLogic(ev);
    case "ask_permission": return showAskPermission(ev);
    case "ask_language": return showAskList(ev, "language", "选择目标语言");
    case "ask_entry": return showAskList(ev, "entry", "选择入口文件");
    case "ask_provide_file": return showAskFile(ev);
    case "ask_next": return showAskNext(ev);
    case "ask_input": return showAskInput(ev);
    default: return;
  }
}

function showAskLogic(ev) {
  const issues = ev.issues || [];
  const html = `<h3>AI 检测到可疑逻辑问题（${issues.length} 个）</h3>
    ${issues.map((it) => `<div class="issue ${it.severity}">
      <span class="l">${it.line ? "第 " + it.line + " 行" : "全文"}</span>
      <span class="badge ${it.severity}">${it.severity}</span>
      <div class="c">${esc(it.concern)}</div>
      <div class="s">建议：${esc(it.suggestion)}</div>
    </div>`).join("")}
    <div class="modal-row" id="diy-row" style="display:none">
      <input type="text" id="diy-input" placeholder="输入你的解决方案（自然语言）…">
    </div>
    <div class="modal-actions">
      <button class="btn primary" data-d="proceed">继续</button>
      <button class="btn" data-d="refix">AI 修复</button>
      <button class="btn" data-d="custom">自己给方案</button>
      <button class="btn" data-d="manual">自己改</button>
      <button class="btn" data-d="quit">退出</button>
    </div>`;
  modal(html);
  $("#diy-row").querySelector("input");
  $$("#modal-box [data-d]").forEach((b) => {
    b.onclick = async () => {
      const d = b.dataset.d;
      if (d === "custom") {
        const row = $("#diy-row");
        row.style.display = "block";
        $("#diy-input").focus();
        return;
      }
      if (d === "manual") {
        modalResolve({ decision: "manual" });
        await respond({ decision: "manual" });
        return;
      }
      modalResolve({ decision: d });
      await respond({ decision: d });
    };
  });
  $("#diy-input").addEventListener("keydown", async (e) => {
    if (e.key === "Enter") {
      const sol = $("#diy-input").value.trim();
      modalResolve({ decision: "custom", solution: sol });
      await respond({ decision: "custom", solution: sol });
    }
  });
}

function showAskPermission(ev) {
  modal(`<h3>AI 请求文件操作权限</h3>
    <div class="issue"><span class="l">${esc(ev.operation)}</span><div class="c">${esc(ev.path)}</div></div>
    <div class="modal-actions">
      <button class="btn primary" data-r='{"allowed":true,"remember":false}'>允许</button>
      <button class="btn" data-r='{"allowed":false,"remember":false}'>拒绝</button>
      <button class="btn" data-r='{"allowed":true,"remember":true}'>本会话都允许</button>
      <button class="btn" data-r='{"allowed":false,"remember":true}'>本会话都拒绝</button>
    </div>`);
  $$("#modal-box [data-r]").forEach((b) => {
    b.onclick = async () => {
      const r = JSON.parse(b.dataset.r);
      modalResolve(r);
      await respond(r);
    };
  });
}

function showAskList(ev, key, title) {
  const opts = ev.options || [];
  modal(`<h3>${title}</h3>
    <div class="opt-list">${opts.map((o) => `<div class="opt-item" data-v="${esc(o)}">${esc(o)}</div>`).join("")}</div>`);
  $$("#modal-box .opt-item").forEach((el) => {
    el.onclick = async () => {
      const v = el.dataset.v;
      modalResolve({ [key]: v });
      await respond({ [key]: v });
    };
  });
}

function showAskFile(ev) {
  modal(`<h3>AI 需要文件</h3>
    <div class="modal-row">需要文件 <b>${esc(ev.fname)}</b>，项目里没找到。<br>
    输入绝对路径，或相对项目根的路径：</div>
    <div class="modal-row"><input type="text" id="file-input" placeholder="如 D:\\proj\\data.nsat"></div>
    <div class="modal-actions">
      <button class="btn primary" id="file-ok">提供</button>
      <button class="btn" id="file-skip">跳过</button>
    </div>`);
  const go = async (path) => {
    modalResolve({ path });
    await respond({ path });
  };
  $("#file-ok").onclick = () => go($("#file-input").value.trim());
  $("#file-skip").onclick = () => go("");
  $("#file-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#file-ok").click(); });
}

function showAskNext(ev) {
  modal(`<h3>本轮运行结束</h3>
    <div class="modal-row">输入下一轮修改意见（自然语言），或直接结束。</div>
    <div class="modal-row"><input type="text" id="next-input" placeholder="例如：把输出改成倒序（/exit 退出）"></div>
    <div class="modal-actions">
      <button class="btn primary" id="next-submit">提交修改</button>
      <button class="btn" id="next-end">结束本轮</button>
    </div>`);
  const go = async (v) => { modalResolve({ instruction: v }); await respond({ instruction: v }); };
  $("#next-submit").onclick = () => go($("#next-input").value.trim());
  $("#next-end").onclick = () => go(null);
  $("#next-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#next-submit").click(); });
}

function showAskInput(ev) {
  modal(`<h3>输入</h3><div class="modal-row">${esc(ev.prompt || "")}</div>
    <div class="modal-row"><input type="text" id="gen-input"></div>
    <div class="modal-actions"><button class="btn primary" id="gen-ok">确定</button></div>`);
  const go = async () => {
    const v = $("#gen-input").value;
    modalResolve({ text: v });
    await respond({ text: v });
  };
  $("#gen-ok").onclick = go;
  $("#gen-input").addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
}

/* ---------------- 控制台 ---------------- */
function log(text, cls = "") {
  const line = document.createElement("div");
  line.className = `log-${cls || "info"}`;
  line.textContent = text;
  $("#console").appendChild(line);
  $("#panel-console").scrollTop = $("#panel-console").scrollHeight;
}
function logErr(text) { log(text, "err"); }

/* ---------------- 任务与 SSE ---------------- */
function switchPanel(tab) {
  $$(".ptab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".panel-body").forEach((b) => b.classList.toggle("active", b.id === `panel-${tab}`));
}

async function submitJob(kind) {
  if (state.jobId) { logErr("已有任务在运行，请等待完成"); return; }
  const save = await saveAllTabs();
  if (!save.ok) return;
  // 运行：优先当前打开的文件；构建：整个项目文件夹
  let target = "";
  if (kind === "build") {
    target = state.root || "";
  } else if (state.activePath && /\.nsat$/i.test(state.activePath)) {
    target = state.activePath;
  } else {
    target = state.root || "";
  }
  if (!target) { logErr("请先打开项目或 .nsat 文件"); return; }
  const isFile = /\.nsat$/i.test(target);
  log(`▶ ${kind === "build" ? "构建" : "运行"}：${isFile ? "文件 " + target : "文件夹 " + target}`);
  const body = {
    target,
    inline: $("#mode-select").value === "single",
    lang: currentLang(),
  };
  if (kind === "build") body.out = null;
  const res = await api(`/api/${kind}`, "POST", body);
  state.jobId = res.job_id;
  setStatus("job", `任务运行中…`);
  log(`—— 启动 ${kind}: ${target} ——`);
  $("#job-out").textContent = "";
  $("#check-out").textContent = "";
  switchPanel("console");
  const es = new EventSource(`/api/jobs/${res.job_id}/stream`);
  es.onmessage = async (e) => {
    const ev = JSON.parse(e.data);
    await handleJobEvent(ev);
  };
  es.onerror = () => { es.close(); state.jobId = null; setStatus("job", "连接中断"); };
}

async function handleJobEvent(ev) {
  switch (ev.type) {
    case "log": log(ev.text); break;
    case "error": logErr(ev.message); setStatus("msg", "出错：" + ev.message); break;
    case "check_result": {
      const ok = ev.ok;
      const issues = ev.issues || [];
      $("#check-out").textContent = ok
        ? "校验通过 ✓"
        : issues.map((it) => `第 ${it.line ?? "?"} 行: ${it.message}`).join("\n");
      switchPanel("check");
      break;
    }
    case "assistant_reply": appendChat("ai", ev.text); break;
    case "done": {
      state.jobId = null;
      setStatus("job", "空闲");
      log("—— 完成 ——");
      break;
    }
    default:
      if (String(ev.type).startsWith("ask_")) await showAsk(ev);
  }
}

/* ---------------- 文件树 ---------------- */
async function openProject(root) {
  const rootDir = root || state.root || "";
  if (!rootDir) { logErr("请先选择项目文件夹（文件 → 打开项目）"); return; }
  try {
    const res = await api(`/api/project?root=${encodeURIComponent(rootDir)}`);
    state.root = res.root;
    state.files = res.files;
    $("#st-root").textContent = res.root;
    renderTree();
    recordRecent(res.root, "folder");
    scheduleSessionSave();
    log(`已打开项目: ${res.root}（${res.files.length} 个文件）`);
  } catch (e) {
    logErr("打开项目失败: " + e.message);
  }
}

function renderTree() {
  const box = $("#file-tree");
  box.innerHTML = "";
  const nsat = state.files.filter((f) => f.type === "nsat");
  const other = state.files.filter((f) => f.type !== "nsat");
  [...nsat, ...other].forEach((f) => {
    const el = document.createElement("div");
    el.className = `tree-item ${f.type}`;
    el.dataset.path = f.path;
    const ico = f.type === "nsat"
      ? `<img src="static/icon.ico" alt="">`
      : `<span>📎</span>`;
    el.innerHTML = `<span class="ico">${ico}</span><span class="rel">${esc(f.rel)}</span>`;
    el.onclick = () => openFile(f.path);
    el.oncontextmenu = (e) => { e.preventDefault(); treeContextMenu(f); };
    box.appendChild(el);
  });
  if (!state.files.length) box.innerHTML = `<div style="color:var(--fg-dim);padding:8px">空项目</div>`;
}

/* ---------------- 通用右键菜单 ---------------- */
let ctxMenu = null;
function showContextMenu(items, x, y) {
  hideContextMenu();
  const menu = document.createElement("div");
  menu.className = "ctx-menu";
  items.forEach((it) => {
    if (it.sep) {
      const s = document.createElement("div");
      s.className = "ctx-sep";
      menu.appendChild(s);
      return;
    }
    const el = document.createElement("div");
    el.className = "ctx-item" + (it.danger ? " danger" : "");
    el.textContent = it.label;
    el.addEventListener("click", () => { hideContextMenu(); it.action && it.action(); });
    menu.appendChild(el);
  });
  document.body.appendChild(menu);
  const w = menu.offsetWidth, h = menu.offsetHeight;
  menu.style.left = Math.min(x, window.innerWidth - w - 8) + "px";
  menu.style.top = Math.min(y, window.innerHeight - h - 8) + "px";
  ctxMenu = menu;
}
function hideContextMenu() { if (ctxMenu) { ctxMenu.remove(); ctxMenu = null; } }
document.addEventListener("click", hideContextMenu);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideContextMenu(); });

function dirOf(p) { return p.substring(0, Math.max(p.lastIndexOf("\\"), p.lastIndexOf("/"))); }
function baseOf(p) { return String(p).split(/[\\/]/).pop(); }

async function refreshProject() { if (state.root) await openProject(state.root); }

async function newFileIn(dir) {
  const name = prompt("新 .nsat 文件名：", "new.nsat");
  if (!name) return;
  let fn = name.trim();
  if (!/\.nsat$/i.test(fn)) fn += ".nsat";
  const target = joinPath(dir || state.root, fn);
  try {
    await api("/api/save", "POST", { path: target, content: "我想把这个文件编译成 Python\n\n" });
    await refreshProject();
    openFile(target);
  } catch (e) { logErr("新建失败: " + e.message); }
}

async function newFolderIn(dir) {
  const name = prompt("新文件夹名：");
  if (!name) return;
  try {
    await api("/api/mkdir", "POST", { path: joinPath(dir || state.root, name.trim()) });
    await refreshProject();
  } catch (e) { logErr("新建文件夹失败: " + e.message); }
}

async function renamePath(path, isFile) {
  const oldName = baseOf(path);
  const name = prompt("新名称：", oldName);
  if (!name || name === oldName) return;
  try {
    await api("/api/rename", "POST", { old: path, new: joinPath(dirOf(path), name.trim()) });
    if (state.tabs.has(path)) await closeTab(path);
    await refreshProject();
    if (isFile) openFile(joinPath(dirOf(path), name.trim()));
  } catch (e) { logErr("重命名失败: " + e.message); }
}

async function deletePath(path) {
  if (!confirm(`确定删除 ${baseOf(path)}？`)) return;
  try {
    await api("/api/delete", "POST", { path });
    if (state.tabs.has(path)) await closeTab(path);
    await refreshProject();
    log(`已删除 ${baseOf(path)}`);
  } catch (e) { logErr("删除失败: " + e.message); }
}

function treeContextMenu(f) {
  const path = f.path;
  const parent = dirOf(path) || state.root;
  const items = [
    { label: "打开", action: () => openFile(path) },
    { sep: true },
    { label: "在此文件夹新建文件", action: () => newFileIn(parent) },
    { label: "在此文件夹新建文件夹", action: () => newFolderIn(parent) },
    { sep: true },
    { label: "重命名", action: () => renamePath(path, true) },
    { label: "删除", danger: true, action: () => deletePath(path) },
  ];
  showContextMenu(items, event.clientX, event.clientY);
}

function treeRootContextMenu() {
  const items = [
    { label: "新建文件", action: () => newFileIn(state.root) },
    { label: "新建文件夹", action: () => newFolderIn(state.root) },
  ];
  showContextMenu(items, event.clientX, event.clientY);
}

/* ---------------- 编辑器标签 ---------------- */
async function openFile(path) {
  recordOpen(path);
  const existing = state.tabs.get(path);
  if (existing) {
    state.activePath = path;
    renderTabs();
    return;
  }
  let content = "";
  try {
    const res = await api(`/api/read?path=${encodeURIComponent(path)}`);
    content = res.content;
  } catch (e) {
    logErr("读取失败: " + e.message);
    content = "";
  }
  const host = document.createElement("div");
  host.className = "editor-host";
  $("#editors").appendChild(host);
  const isNsat = path.toLowerCase().endsWith(".nsat");
  const mode = isNsat ? "python" : langFromExt(path);
  const editor = window.NSATEditor.create(host, {
    value: content,
    mode: mode || "text",
    onChange: () => {
      const t = state.tabs.get(path);
      if (t && !t.dirty) {
        t.dirty = t.editor.getValue() !== t.savedValue;
        renderTabs();
      }
    },
  });
  state.tabs.set(path, { el: host, editor, dirty: false, savedValue: content });
  state.activePath = path;
  renderTabs();
}

function langFromExt(path) {
  const e = (path.split(".").pop() || "").toLowerCase();
  return { py: "python", js: "javascript", go: "go", rs: "rust", c: "c", cpp: "cpp", java: "java" }[e] || "";
}

function renderTabs() {
  const tabs = $("#tabs");
  tabs.innerHTML = "";
  state.tabs.forEach((t, path) => {
    const el = document.createElement("div");
    const name = path.split(/[\\/]/).pop();
    el.className = "tab" + (path === state.activePath ? " active" : "");
    el.innerHTML = `<span class="tab-dot${t.dirty ? " dirty" : ""}"></span><span class="tab-name">${esc(name)}</span><span class="close" title="关闭">✕</span>`;
    el.onclick = () => {
      state.activePath = path;
      showActiveEditor();
      renderTabs();
    };
    el.querySelector(".close").onclick = (e) => {
      e.stopPropagation();
      closeTab(path);
    };
    tabs.appendChild(el);
  });
  showActiveEditor();
}

function showActiveEditor() {
  state.tabs.forEach((t, path) => {
    t.el.classList.toggle("hidden", path !== state.activePath);
  });
  const active = state.activePath && state.tabs.get(state.activePath);
  if (active) {
    $("#empty-hint").style.display = "none";
  } else {
    $("#empty-hint").style.display = "flex";
  }
}

async function closeTab(path) {
  const t = state.tabs.get(path);
  if (t && t.dirty) {
    if (!confirm(`文件 ${path.split(/[\\/]/).pop()} 有未保存修改，确定关闭？`)) return;
  }
  t.editor.destroy();
  t.el.remove();
  state.tabs.delete(path);
  if (state.activePath === path) {
    state.activePath = state.tabs.keys().next().value || null;
  }
  renderTabs();
}

async function saveAllTabs() {
  let ok = true;
  for (const [path, t] of state.tabs) {
    if (t.dirty) {
      try {
        await api("/api/save", "POST", { path, content: t.editor.getValue() });
        t.savedValue = t.editor.getValue();
        t.dirty = false;
        log(`已保存 ${path.split(/[\\/]/).pop()}`);
      } catch (e) {
        logErr("保存失败: " + e.message);
        ok = false;
      }
    }
  }
  renderTabs();
  return { ok };
}

/* ---------------- AI 助手 ---------------- */
function appendChat(role, text) {
  const el = document.createElement("div");
  el.className = `chat-msg ${role}`;
  el.textContent = text;
  $("#chat-list").appendChild(el);
  $("#chat-list").scrollTop = $("#chat-list").scrollHeight;
}

async function sendChat() {
  const msg = $("#chat-input").value.trim();
  if (!msg || state.jobId) return;
  if (!state.root) { logErr("请先打开项目"); return; }
  $("#chat-input").value = "";
  appendChat("user", msg);
  appendChat("system", "…思考中");
  const res = await api("/api/ask", "POST", { target: state.root, message: msg });
  state.jobId = res.job_id;
  const es = new EventSource(`/api/jobs/${res.job_id}/stream`);
  let replied = false;
  es.onmessage = async (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === "assistant_reply") {
      // 移除“思考中”
      const last = $("#chat-list").lastChild;
      if (last && last.className === "chat-msg system") last.remove();
      appendChat("ai", ev.text);
      replied = true;
    } else if (ev.type === "error") {
      const last = $("#chat-list").lastChild;
      if (last && last.className === "chat-msg system") last.remove();
      appendChat("system", "错误：" + ev.message);
      replied = true;
    } else if (String(ev.type).startsWith("ask_")) {
      await showAsk(ev);
    } else if (ev.type === "done") {
      state.jobId = null;
      es.close();
    }
  };
  es.onerror = () => es.close();
}

/* ---------------- 可拖拽分隔条 ---------------- */
function makeVSplit(handle, target, minH, maxH) {
  let dragging = false, startY = 0, startH = 0;
  handle.addEventListener("mousedown", (e) => {
    dragging = true; startY = e.clientY; startH = target.getBoundingClientRect().height;
    document.body.style.cursor = "row-resize";
    e.preventDefault();
  });
  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const h = startH + (startY - e.clientY); // 向上拖变高
    target.style.height = Math.max(minH, Math.min(maxH, h)) + "px";
  });
  document.addEventListener("mouseup", () => { dragging = false; document.body.style.cursor = ""; });
}

function makeHSplit(handle, target, minW, maxW) {
  let dragging = false, startX = 0, startW = 0;
  handle.addEventListener("mousedown", (e) => {
    dragging = true; startX = e.clientX; startW = target.getBoundingClientRect().width;
    document.body.style.cursor = "col-resize";
    e.preventDefault();
  });
  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const w = startW + (e.clientX - startX); // 向右拖变宽
    target.style.width = Math.max(minW, Math.min(maxW, w)) + "px";
  });
  document.addEventListener("mouseup", () => { dragging = false; document.body.style.cursor = ""; });
}

/* ---------------- 菜单栏 ---------------- */
function currentLang() {
  const v = $("#lang-select").value;
  if (v === "__custom__") {
    const c = $("#custom-lang").value.trim();
    return c || null;
  }
  return v || null;
}

function closeMenus() {
  $$("#menubar .menu").forEach((m) => m.classList.remove("open"));
}

function menuAction(act) {
  closeMenus();
  switch (act) {
    case "open-project": openProjectDialog(); break;
    case "open-file": openFileDialog(); break;
    case "new-nsat": newNsat(); break;
    case "save-all": saveAllTabs(); break;
    case "exit": api("/api/exit", "POST", {}).catch(() => {}); break;
    case "run": submitJob("run"); break;
    case "build": submitJob("build"); break;
    case "check": checkCurrent(); break;
    case "refresh": if (state.root) openProject(state.root); break;
    case "settings": openSettings(); break;
    case "assoc": runAssoc(); break;
    case "about": aboutDialog(); break;
  }
}

/* ---------------- 后端目录浏览器对话框 ---------------- */
function joinPath(a, b) {
  if (!a) return b || "";
  const sep = a.includes("/") ? "/" : "\\";
  return a.replace(/[\\/]+$/, "") + sep + String(b).replace(/^[\\/]+/, "");
}

function closeModalBox() { $("#modal-mask").classList.add("hidden"); }

function openProjectDialog() {
  // 用内置目录浏览器（后端驱动、可靠，不依赖 pywebview 桥接）
  browseDialog({ title: "打开项目", mode: "folder" }).then((root) => {
    if (root) openProject(root);
  });
}

function openFileDialog() {
  browseDialog({ title: "打开文件", mode: "file", filter: ".nsat" }).then((path) => {
    if (path) openFileWithDir(path);
  });
}

function openFileWithDir(path) {
  const dir = path.substring(0, Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/")));
  if (dir && dir !== state.root) {
    state.root = dir;
    $("#st-root").textContent = dir;
    openProject(dir).then(() => openFile(path));
  } else {
    openFile(path);
  }
}

function browseDialog({ title, mode, filter }) {
  return new Promise((resolve) => {
    const bs = { path: "" };
    const box = $("#modal-box");
    $("#modal-mask").classList.remove("hidden");
    async function render() {
      let res, recents = [];
      try {
        const [b, r] = await Promise.all([
          api(`/api/browse?path=${encodeURIComponent(bs.path)}&mode=${mode}`),
          api("/api/recent"),
        ]);
        res = b; recents = r.items || [];
      } catch (e) {
        box.innerHTML = `<h3>错误</h3><div>${esc(e.message)}</div>`;
        return;
      }
      if (!res.ok) { box.innerHTML = `<h3>错误</h3><div>${esc(res.error || "")}</div>`; return; }
      bs.path = res.path;
      let html = `<div class="dlg-head">
          <h3>${title}</h3>
          <button class="dlg-x" id="b-close" title="关闭">✕</button>
        </div>
        <div class="browse-pathrow">
          <input id="b-path" value="${esc(bs.path)}" placeholder="输入路径后回车前往（如 C:\\Users\\me\\proj）" spellcheck="false">
          <button class="btn" id="b-go">前往</button>
        </div>
        <div class="recent-row">最近打开：
          ${recents.length ? recents.map((r) =>
            `<span class="chip ${r.type}" data-path="${esc(r.path)}" data-type="${esc(r.type)}">${esc(r.type === "folder" ? r.path : r.path.split(/[\\/]/).pop())}</span>`
          ).join("") : `<span class="recent-empty">暂无</span>`}
        </div>
        <div class="browse-path">${esc(bs.path || "我的电脑")}</div>
        <div class="browse-body">`;
      if (bs.path) {
        html += `<div class="bdir" data-path="${esc(res.parent || "")}">⬆  上级目录</div>`;
      }
      for (const d of res.dirs || []) {
        html += `<div class="bdir" data-path="${esc(joinPath(bs.path, d))}">📁  ${esc(d)}</div>`;
      }
      if (mode === "file") {
        for (const f of res.files || []) {
          if (filter && !f.toLowerCase().endsWith(filter)) continue;
          html += `<div class="bfile" data-path="${esc(joinPath(bs.path, f))}">📄  ${esc(f)}</div>`;
        }
      }
      html += `</div>
        <div class="browse-actions">
          <button class="btn" id="b-newdir">新建文件夹</button>
          ${mode === "folder" ? `<button class="btn primary" id="b-ok">选择此文件夹</button>` : ""}
          <button class="btn" id="b-cancel">取消</button>
        </div>`;
      box.innerHTML = html;

      const go = () => {
        const v = $("#b-path").value.trim();
        if (!v) return;
        bs.path = v;
        recordRecent(v, "folder");
        render();
      };
      $("#b-go").onclick = go;
      $("#b-path").addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
      $("#b-close").onclick = () => { resolve(null); closeModalBox(); };

      $$("#modal-box .chip").forEach((el) => {
        el.onclick = () => {
          const p = el.dataset.path;
          if (el.dataset.type === "folder") { bs.path = p; render(); }
          else { bs.path = p.substring(0, Math.max(p.lastIndexOf("\\"), p.lastIndexOf("/"))); render(); }
        };
      });
      $$("#modal-box .bdir").forEach((el) => { el.onclick = () => { bs.path = el.dataset.path; render(); }; });
      $$("#modal-box .bfile").forEach((el) => { el.onclick = () => { recordRecent(el.dataset.path, "file"); resolve(el.dataset.path); closeModalBox(); }; });
      const ok = $("#b-ok");
      if (ok) ok.onclick = () => { recordRecent(bs.path, "folder"); resolve(bs.path); closeModalBox(); };
      $("#b-cancel").onclick = () => { resolve(null); closeModalBox(); };
      $("#b-newdir").onclick = async () => {
        const name = prompt("新文件夹名：");
        if (!name) return;
        try { await api("/api/mkdir", "POST", { path: joinPath(bs.path, name.trim()) }); }
        catch (e) { logErr("新建文件夹失败: " + e.message); }
        render();
      };
    }
    render();
  });
}

function recordRecent(path, type) {
  if (!path) return;
  api("/api/recent", "POST", { path, type }).catch(() => {});
}

function newNsat() {
  if (!state.root) { logErr("请先打开项目"); return; }
  const name = prompt("新建 .nsat 文件名：", "new.nsat");
  if (!name) return;
  let fname = name.trim();
  if (!/\.nsat$/i.test(fname)) fname += ".nsat";
  const path = state.root.replace(/[\\/]+$/, "") + "\\" + fname;
  api("/api/save", "POST", { path, content: "我想把这个文件编译成 Python\n\n" }).then(() => {
    openProject().then(() => openFile(path));
  }).catch((e) => logErr("新建失败: " + e.message));
}

async function checkCurrent() {
  const t = state.tabs.get(state.activePath);
  if (!t) { logErr("请先打开一个 .nsat 文件"); return; }
  await saveAllTabs();
  const res = await api("/api/check", "POST", { target: state.activePath });
  state.jobId = res.job_id;
  switchPanel("check");
  const es = new EventSource(`/api/jobs/${res.job_id}/stream`);
  es.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === "check_result") {
      $("#check-out").textContent = ev.ok ? "校验通过 ✓" : (ev.issues || []).map((i) => `第 ${i.line ?? "?"} 行: ${i.message}`).join("\n");
      switchPanel("check");
    }
    if (ev.type === "error") { $("#check-out").textContent = "错误: " + ev.message; switchPanel("check"); }
    if (ev.type === "done") { state.jobId = null; es.close(); }
  };
}

async function runAssoc() {
  try {
    const r = await api("/api/assoc", "POST", {});
    log(r.ok ? r.message : "关联失败: " + r.message);
  } catch (e) {
    logErr("关联失败: " + e.message);
  }
}

function aboutDialog() {
  modal(`<h3>NSAT Studio</h3>
    <p style="color:var(--fg-dim);line-height:1.7">
      自然语言编程工作台：写 NSAT → AI 补全逻辑并翻译成目标语言 → 运行测试迭代。<br><br>
      单文件 / 多文件模式、AI 助手、插件支持（plugins 目录）。<br>
      反馈：<a href="#" onclick="return false">当前为实验版</a>
    </p>
    <div class="modal-actions"><button class="btn" onclick="modalResolve(null)">关闭</button></div>`);
}

/* ---------------- 设置窗口 ---------------- */
let settingsHasKey = false;
let settingsClearKey = false;

async function openSettings() {
  try {
    const cfg = await api("/api/settings");
    const ai = cfg.ai || {};
    $("#set-provider").value = ai.provider || "deepseek";
    $("#set-model").value = ai.model || "";
    settingsHasKey = ai.api_key === "********";
    settingsClearKey = false;
    $("#set-apikey").value = "";
    $("#set-apikey").placeholder = settingsHasKey ? "已保存（已隐藏），输入新值可覆盖" : "输入 API Key";
    $("#set-baseurl").value = ai.base_url || "";
    $("#set-logicmode").value = (cfg.logic_errors && cfg.logic_errors.mode) || "ask";
    $("#set-permmode").value = (cfg.permissions && cfg.permissions.mode) || "ask";
    $("#set-runcommand").checked = !!(cfg.permissions && cfg.permissions.allow_run_command);
    const as = (cfg.ui && cfg.ui.autosave) || {};
    const asEnabled = typeof as === "boolean" ? as : !!as.enabled;
    const asInterval = typeof as === "boolean" ? 1 : (parseInt(as.interval, 10) || 1);
    $("#set-autosave").checked = asEnabled;
    $("#set-autosave-interval").value = asInterval;
    $("#set-msg").textContent = "";
    $("#settings-mask").classList.remove("hidden");
  } catch (e) {
    logErr("读取设置失败: " + e.message);
  }
}

function closeSettings() { $("#settings-mask").classList.add("hidden"); }

function clearApiKeyField() {
  settingsClearKey = true;
  settingsHasKey = false;
  $("#set-apikey").value = "";
  $("#set-apikey").placeholder = "输入 API Key（保存后清除旧 Key）";
  $("#set-apikey").focus();
}

async function saveSettings() {
  const typedKey = $("#set-apikey").value.trim();
  let apiKey;
  if (settingsClearKey) apiKey = "__clear__";
  else if (typedKey) apiKey = typedKey;
  else if (settingsHasKey) apiKey = "********"; // 未改动，保持不变
  else apiKey = "";
  const payload = {
    ai: {
      provider: $("#set-provider").value,
      model: $("#set-model").value.trim(),
      base_url: $("#set-baseurl").value.trim(),
      api_key: apiKey,
    },
    logic_errors: { mode: $("#set-logicmode").value },
    permissions: {
      mode: $("#set-permmode").value,
      allow_run_command: $("#set-runcommand").checked,
    },
    ui: {
      autosave: {
        enabled: $("#set-autosave").checked,
        interval: parseInt($("#set-autosave-interval").value, 10) || 1,
      },
    },
  };
  try {
    const r = await api("/api/settings", "PUT", payload);
    settingsClearKey = false;
    settingsHasKey = !!typedKey || settingsHasKey;
    $("#set-msg").textContent = "已保存 ✓";
    if (!$("#settings-mask").classList.contains("hidden")) {
      setTimeout(() => { if (!$("#settings-mask").classList.contains("hidden")) $("#set-msg").textContent = ""; }, 2500);
    }
  } catch (e) {
    $("#set-msg").textContent = "保存失败: " + e.message;
  }
}

let _autosaveTimer = null;
function autosaveSettings() {
  if (!$("#set-autosave").checked) return;
  const secs = parseInt($("#set-autosave-interval").value, 10) || 1;
  clearTimeout(_autosaveTimer);
  _autosaveTimer = setTimeout(saveSettings, secs * 1000);
}

function wireAutosave() {
  [
    "#set-provider", "#set-model", "#set-apikey", "#set-baseurl",
    "#set-logicmode", "#set-permmode", "#set-runcommand",
    "#set-autosave", "#set-autosave-interval",
  ].forEach((sel) => {
    const el = $(sel);
    if (el) el.addEventListener("change", autosaveSettings);
  });
  // 文本框实时输入也触发（防抖按设置的间隔）
  ["#set-model", "#set-apikey", "#set-baseurl"].forEach((sel) => {
    const el = $(sel);
    if (el) el.addEventListener("input", autosaveSettings);
  });
}

/* ---------------- 单实例轮询：别的实例要打开的文件 ---------------- */
function startInstancePolling() {
  setInterval(async () => {
    try {
      const r = await api("/api/instance/pending");
      if (r.path) {
        log(`收到打开请求: ${r.path}`);
        // 若文件不在当前项目，切到其所在目录
        if (!state.root || !r.path.startsWith(state.root)) {
          const dir = r.path.substring(0, Math.max(r.path.lastIndexOf("\\"), r.path.lastIndexOf("/")));
          if (dir && dir !== state.root) {
            state.root = dir;
            $("#st-root").textContent = dir;
            renderTree();
            await openProject(dir);
          }
        }
        openFile(r.path);
      }
    } catch (e) { /* 静默 */ }
  }, 2000);
}

/* ---------------- 事件绑定 ---------------- */
function setStatus(key, val) {
  const el = $("#st-" + key);
  if (el) el.textContent = val;
}

document.addEventListener("DOMContentLoaded", () => {
  $("#btn-run").onclick = () => submitJob("run");
  $("#btn-build").onclick = () => submitJob("build");
  $("#btn-check").onclick = checkCurrent;
  $("#btn-ai").onclick = () => switchActivity("assistant");
  $("#chat-send").onclick = sendChat;
  $("#chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });

  // 菜单栏：悬停自动展开 + 点击切换
  $$("#menubar .menu").forEach((m) => {
    m.addEventListener("mouseenter", () => {
      closeMenus();
      m.classList.add("open");
    });
    m.addEventListener("click", (e) => {
      e.stopPropagation();
      m.classList.toggle("open");
    });
  });
  $("#menubar").addEventListener("mouseleave", closeMenus);
  document.addEventListener("click", closeMenus);
  $$("#menubar .mi").forEach((mi) => {
    mi.addEventListener("click", (e) => {
      e.stopPropagation();
      menuAction(mi.dataset.act);
    });
  });

  // 自定义语言
  $("#lang-select").addEventListener("change", () => {
    $("#custom-lang").style.display = $("#lang-select").value === "__custom__" ? "" : "none";
  });

  // 新建/打开项目按钮
  $("#tree-new").onclick = newNsat;
  $("#tree-open").onclick = openProjectDialog;
  $("#set-save").onclick = saveSettings;
  $("#set-cancel").onclick = closeSettings;
  $("#set-keyclear").onclick = clearApiKeyField;
  wireAutosave();

  // 文件树空白区右键：新建
  $("#file-tree").addEventListener("contextmenu", (e) => {
    if (e.target.closest(".tree-item")) return; // 项目自身处理
    e.preventDefault();
    if (state.root) treeRootContextMenu();
  });

  // 编辑器右键菜单：剪贴/复制/粘贴/删除/全选/撤销/重做
  $("#editors").addEventListener("contextmenu", (e) => {
    if (!e.target.closest(".cm-editor")) return;
    e.preventDefault();
    const active = state.activePath && state.tabs.get(state.activePath);
    if (!active || !active.editor || !active.editor.commands) return;
    const c = active.editor.commands;
    showContextMenu([
      { label: "撤销", action: () => c.undo() },
      { label: "重做", action: () => c.redo() },
      { sep: true },
      { label: "剪切", action: () => c.cut() },
      { label: "复制", action: () => c.copy() },
      { label: "粘贴", action: () => c.paste() },
      { label: "删除", action: () => c.deleteSelection() },
      { sep: true },
      { label: "全选", action: () => c.selectAll() },
    ], e.clientX, e.clientY);
  });

  // 终端/输出右键菜单：复制
  $("#panel-console").addEventListener("contextmenu", (e) => {
    e.preventDefault();
    showContextMenu([
      {
        label: "复制选中",
        action: async () => {
          const s = (window.getSelection() || "").toString();
          if (s) { try { await navigator.clipboard.writeText(s); } catch (err) {} }
        },
      },
      {
        label: "复制全部",
        action: async () => {
          try { await navigator.clipboard.writeText($("#console").textContent); } catch (err) {}
        },
      },
      { sep: true },
      { label: "清空输出", action: () => { $("#console").textContent = ""; } },
    ], e.clientX, e.clientY);
  });

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      saveAllTabs();
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "enter") {
      e.preventDefault();
      submitJob("run");
    }
  });
  $$(".act-btn").forEach((b) => b.onclick = () => switchActivity(b.dataset.view));
  $$(".ptab").forEach((b) => b.onclick = () => switchPanel(b.dataset.tab));
  makeVSplit($("#vsplit"), $("#bottom-panel"), 80, window.innerHeight * 0.8);
  makeHSplit($("#hsplit"), $("#sidebar"), 140, 600);
  startInstancePolling();
  // 打开默认目录：文件关联 / ?root= 参数优先；否则恢复上次会话
  const qp = new URLSearchParams(location.search);
  const cwd = qp.get("root") || "";
  const openFileParam = qp.get("file") || "";
  if (cwd) {
    openProject(cwd).then(() => {
      if (openFileParam) openFile(openFileParam);
    });
  } else {
    restoreSession();
  }
});

function switchActivity(view) {
  $$(".act-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $("#view-explorer").classList.toggle("hidden", view !== "explorer");
  $("#view-assistant").classList.toggle("hidden", view !== "assistant");
  if (view === "output") switchPanel("console");
}
