/* =========================================================
 *  Nav · 个人导航页 —— 前台逻辑
 *  书签数据来自后端 /api/data（在 /admin 后台维护）
 *  三个独立小模块：主题 / 时钟 / 书签渲染
 * ========================================================= */

const $ = (sel) => document.querySelector(sel);

/* 防止数据里的特殊字符破坏页面结构 */
const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

const store = {
  get: (k, fallback) => localStorage.getItem(k) ?? fallback,
  set: (k, v) => localStorage.setItem(k, v),
};

/* ---------- 1. 主题：跟随系统，可手动切换并记住 ---------- */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  store.set("nav-theme", theme);
}

applyTheme(
  store.get("nav-theme", matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
);
$("#themeToggle").addEventListener("click", () =>
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark")
);

/* ---------- 2. 时钟与问候语 ---------- */
const WEEK = ["日", "一", "二", "三", "四", "五", "六"];
const pad = (n) => String(n).padStart(2, "0");

function greeting(hour) {
  if (hour < 5)  return "夜深了";
  if (hour < 9)  return "早上好";
  if (hour < 12) return "上午好";
  if (hour < 14) return "中午好";
  if (hour < 18) return "下午好";
  if (hour < 19) return "傍晚好";
  if (hour < 23) return "晚上好";
  return "夜深了";
}

function tick() {
  const now = new Date();
  $("#time").textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
  $("#sec").textContent = pad(now.getSeconds());
  $("#date").textContent =
    `${now.getMonth() + 1}月${now.getDate()}日 星期${WEEK[now.getDay()]}`;
  $("#greeting").textContent = greeting(now.getHours()) + (STATE?.name ? `，${STATE.name}` : "");
}
tick();
setInterval(tick, 1000);

/* ---------- 3. 书签渲染 ---------- */
function hostOf(url) {
  try { return new URL(url).hostname; } catch { return ""; }
}

/* 首字母占位块的配色：根据名字取模挑一个，保证同名恒定同色 */
const LETTER_COLORS = [
  ["#6366f1", "#8b5cf6"], ["#ec4899", "#f43f5e"], ["#14b8a6", "#0ea5e9"],
  ["#f59e0b", "#f97316"], ["#8b5cf6", "#ec4899"], ["#0ea5e9", "#6366f1"],
];

function cardHTML(link, index) {
  const host = hostOf(link.url);
  const sub = link.desc || host.replace(/^www\./, "");

  let icon;
  if (link.icon) {
    icon = `<span class="emoji">${esc(link.icon)}</span>`;
  } else if (host) {
    // 优先用网站自带的 favicon，加载失败再退回首字母
    icon = `<img class="favicon" src="https://${esc(host)}/favicon.ico" alt="" loading="lazy">`;
  } else {
    icon = letterHTML(link.name);
  }

  return `
    <a class="card" href="${esc(link.url)}" target="_blank" rel="noopener"
       style="animation-delay:${Math.min(index * 40, 360)}ms">
      <span class="icon-tile" data-name="${esc(link.name)}">${icon}</span>
      <span class="card-name">${esc(link.name)}</span>
      <span class="card-sub">${esc(sub)}</span>
    </a>`;
}

function letterHTML(name) {
  const [c1, c2] = LETTER_COLORS[[...name].reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % LETTER_COLORS.length];
  return `<span class="letter" style="background:linear-gradient(135deg,${c1},${c2})">${esc(name[0].toUpperCase())}</span>`;
}

function renderCategories(cats) {
  const root = $("#categories");

  if (!cats?.length) {
    root.innerHTML = `<div class="empty">还没有书签 —— 打开 <a href="/admin">后台管理</a> 添加第一个分类吧</div>`;
    return;
  }

  root.innerHTML = cats.map((cat, i) => `
    <section class="category" style="animation-delay:${i * 60}ms">
      <header class="cat-head">
        <span class="cat-icon">${esc(cat.icon || "📁")}</span>
        <h2>${esc(cat.name)}</h2>
        <span class="cat-count">${cat.links.length}</span>
        <i class="rule"></i>
      </header>
      <div class="links">${cat.links.map(cardHTML).join("")}</div>
    </section>`).join("");

  // favicon 加载失败 → 换成首字母方块
  root.querySelectorAll(".favicon").forEach((img) => {
    img.addEventListener("error", () => {
      const tile = img.closest(".icon-tile");
      tile.innerHTML = letterHTML(tile.dataset.name);
    }, { once: true });
  });
}

/* ---------- 4. 启动：拉取后端数据（失败自动重试，避免白屏） ---------- */
let STATE = null;

async function boot() {
  const ctrl = new AbortController();           // 手动超时：兼容所有浏览器
  const timer = setTimeout(() => ctrl.abort(), 5000);
  try {
    const res = await fetch("/api/data", { signal: ctrl.signal });
    if (!res.ok) throw new Error();
    STATE = await res.json();
    document.title = STATE.title || "Nav";
    renderCategories(STATE.categories);
  } catch {
    $("#categories").innerHTML =
      `<div class="empty">连不上后端服务，正在自动重试…<br>
       <small>若一直失败，请确认服务已启动（python3 server.py 或 docker compose up -d）</small></div>`;
    setTimeout(boot, 3000); // 服务恢复后自动补上，无需手动刷新
  } finally {
    clearTimeout(timer);
  }
}

boot();
