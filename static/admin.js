/* =========================================================
 *  Lodestar · 后台管理 —— 登录 + 书签增删改
 *  未登录渲染登录卡片；登录后渲染编辑器，保存时整体提交
 * ========================================================= */

const $ = (sel) => document.querySelector(sel);

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

/* 主题与前台保持一致 */
document.documentElement.dataset.theme =
  localStorage.getItem("nav-theme") ||
  (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

/* 全部数据：{ title, name, categories: [{ name, icon, links: [...] }] } */
let data = null;

/* 未保存更改跟踪：按钮呼吸提示 + 离开页面拦截 */
let dirty = false;

function markDirty() {
  if (dirty) return;
  dirty = true;
  $("#saveBtn")?.classList.add("dirty");
}

function clearDirty() {
  dirty = false;
  $("#saveBtn")?.classList.remove("dirty");
}

window.addEventListener("beforeunload", (e) => {
  if (dirty) {   // 有未保存更改时，浏览器弹出离开确认
    e.preventDefault();
    e.returnValue = "";
  }
});

/* ---------- 启动：已登录进编辑器，未登录进登录页 ---------- */
async function boot() {
  let authed = false;
  try {
    authed = (await fetch("/api/auth")).ok;
  } catch { /* 后端不可达时按未登录处理 */ }

  if (!authed) return renderLogin();

  const res = await fetch("/api/data");
  if (!res.ok) return renderLogin("会话已过期，请重新登录");
  data = await res.json();
  renderEditor();
}

/* ---------- 登录卡片 ---------- */
function renderLogin(msg = "") {
  $("#app").innerHTML = `
    <form class="admin-login" id="loginForm">
      <h1>Lodestar 后台</h1>
      <input id="user" placeholder="用户名" autocomplete="username" required>
      <input id="pass" type="password" placeholder="密码" autocomplete="current-password" required>
      <button class="btn" type="submit">登 录</button>
      <p class="admin-msg ${msg ? "err" : ""}">${esc(msg)}</p>
      <a class="admin-back" href="/">← 返回主页</a>
    </form>`;

  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user: $("#user").value, pass: $("#pass").value }),
    });
    res.ok ? boot() : renderLogin("用户名或密码错误");
  });
}

/* ---------- 编辑器 ---------- */
function renderEditor() {
  $("#app").innerHTML = `
    <header class="admin-top">
      <h1>书签管理</h1>
      <div class="admin-actions">
        <span id="saveMsg" class="admin-msg"></span>
        <a class="btn btn-ghost" href="/" target="_blank">查看主页</a>
        <button class="btn btn-ghost" id="logoutBtn">退出</button>
        <button class="btn" id="saveBtn">保存</button>
      </div>
    </header>

    <div class="admin-meta">
      <label>页面标题 <input id="metaTitle" placeholder="Lodestar · 我的导航"></label>
      <label>问候名字 <input id="metaName" placeholder="留空则只显示问候语"></label>
    </div>

    <main id="catList"></main>
    <button class="btn btn-ghost admin-add-cat" id="addCatBtn">＋ 添加分类</button>`;

  $("#metaTitle").value = data.title || "";
  $("#metaName").value = data.name || "";
  $("#metaTitle").oninput = (e) => { data.title = e.target.value; markDirty(); };
  $("#metaName").oninput = (e) => { data.name = e.target.value; markDirty(); };
  $("#saveBtn").onclick = save;
  $("#logoutBtn").onclick = async () => {
    if (dirty && !confirm("有未保存的更改，确定退出？")) return;
    await fetch("/api/logout", { method: "POST" });
    clearDirty();
    renderLogin();
  };
  $("#addCatBtn").onclick = () => {
    data.categories.push({ name: "新分类", icon: "📁", links: [] });
    markDirty();
    renderCatList();
  };

  clearDirty();
  renderCatList();
}

/* 分类列表：结构变化（增删）时整体重绘，输入变化只改内存不重绘 */
function renderCatList() {
  $("#catList").innerHTML = data.categories.map((cat, ci) => `
    <section class="admin-cat">
      <header class="admin-cat-head">
        <input class="cat-icon-input" value="${esc(cat.icon)}" title="分类图标（emoji）"
               data-ci="${ci}" data-k="icon">
        <input class="cat-name-input" value="${esc(cat.name)}"
               data-ci="${ci}" data-k="name">
        <button class="btn-danger" data-delcat="${ci}">删除分类</button>
      </header>
      <div class="admin-links">${cat.links.map((l, li) => linkRow(l, ci, li)).join("")}</div>
      <button class="btn btn-ghost admin-add-link" data-addlink="${ci}">＋ 添加链接</button>
    </section>`).join("");

  onAll("[data-delcat]", (btn) => btn.onclick = () => {
    const ci = +btn.dataset.delcat;
    if (confirm(`确定删除分类「${data.categories[ci].name}」及其全部链接？`)) {
      data.categories.splice(ci, 1);
      markDirty();
      renderCatList();
    }
  });
  onAll("[data-addlink]", (btn) => btn.onclick = () => {
    data.categories[+btn.dataset.addlink].links
      .push({ name: "", url: "https://", desc: "", icon: "" });
    markDirty();
    renderCatList();
  });
  onAll("[data-dellink]", (btn) => btn.onclick = () => {
    const { ci, li } = btn.dataset;
    data.categories[+ci].links.splice(+li, 1);
    markDirty();
    renderCatList();
  });
  onAll("input[data-k]", (inp) => inp.oninput = (e) => {
    const { ci, li, k } = e.target.dataset;
    if (li === undefined) data.categories[+ci][k] = e.target.value;        // 分类字段
    else data.categories[+ci].links[+li][k] = e.target.value;              // 链接字段
    markDirty();
  });
}

function linkRow(l, ci, li) {
  const cell = (k, cls, ph) =>
    `<input class="${cls}" placeholder="${ph}" value="${esc(l[k])}"
            data-ci="${ci}" data-li="${li}" data-k="${k}">`;
  return `
    <div class="admin-link">
      ${cell("icon", "cell-icon", "emoji")}
      ${cell("name", "cell-name", "名称")}
      ${cell("url", "cell-url", "https://…")}
      ${cell("desc", "cell-desc", "备注")}
      <button class="btn-danger" data-dellink data-ci="${ci}" data-li="${li}">✕</button>
    </div>`;
}

/* 小工具：批量绑定元素事件 */
function onAll(sel, bind) {
  $("#catList").querySelectorAll(sel).forEach(bind);
}

/* ---------- 保存 ---------- */

/* 提交前整理：去掉首尾空白，网址缺协议时自动补 https:// */
function normalizeData() {
  data.title = (data.title || "").trim();
  data.name = (data.name || "").trim();
  data.categories.forEach((cat) => {
    cat.name = (cat.name || "").trim();
    cat.icon = (cat.icon || "").trim();
    cat.links.forEach((l) => {
      l.name = (l.name || "").trim();
      l.desc = (l.desc || "").trim();
      l.icon = (l.icon || "").trim();
      l.url = (l.url || "").trim();
      if (l.name && l.url && !/^https?:\/\//i.test(l.url)) {
        l.url = "https://" + l.url;   // 内网地址习惯不带协议，自动补全
      }
    });
  });
}

async function save() {
  const msg = $("#saveMsg");
  msg.className = "admin-msg";
  msg.textContent = "保存中…";

  normalizeData();
  const res = await fetch("/api/data", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const out = await res.json().catch(() => ({}));

  if (res.ok) {
    const t = new Date();
    msg.textContent = `已保存 ${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
    clearDirty();
    renderCatList();   // 回填自动补全后的网址
  } else {
    msg.className = "admin-msg err";
    msg.textContent = out.msg || "保存失败";
  }
}

boot();
