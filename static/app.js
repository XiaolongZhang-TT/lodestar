/* =========================================================
 *  Lodestar · 个人导航页 —— 前台逻辑
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

/* 全局状态：声明必须放在使用之前（tick/boot 都会读写） */
let STATE = null;

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

/* 带端口的 host（如 media.example.com:10001），图标解析需要它区分同一域名的不同服务 */
function netlocOf(url) {
  try { return new URL(url).host; } catch { return ""; }
}

/* 首字母占位块的配色：根据名字取模挑一个，保证同名恒定同色 */
const LETTER_COLORS = [
  ["#6366f1", "#8b5cf6"], ["#ec4899", "#f43f5e"], ["#14b8a6", "#0ea5e9"],
  ["#f59e0b", "#f97316"], ["#8b5cf6", "#ec4899"], ["#0ea5e9", "#6366f1"],
];

function cardHTML(link, index) {
  const hostname = hostOf(link.url);
  const sub = link.desc || hostname.replace(/^www\./, "");
  const host = netlocOf(link.url);

  let icon;
  if (link.icon) {
    icon = `<span class="emoji">${esc(link.icon)}</span>`;
  } else if (host) {
    // 先显示首字母占位，图标加载成功后再覆盖；加载失败则保留首字母
    // v=3：图标服务端曾修复 MIME/viewBox，版本号变化可击穿旧缓存
    icon = `${letterHTML(link.name)}<img class="favicon" src="/api/icon?v=3&host=${encodeURIComponent(host)}" alt="" loading="lazy">`;
  } else {
    icon = letterHTML(link.name);
  }

  return `
    <a class="card" href="${esc(link.url)}" target="_blank" rel="noopener"
       style="animation-delay:${Math.min(index * 40, 360)}ms">
      <span class="icon-tile" data-name="${esc(link.name)}">${icon}</span>
      ${host ? `<i class="status-dot" data-host="${esc(host)}" title="状态未知"></i>` : ""}
      <span class="card-name">${esc(link.name)}</span>
      <span class="card-sub">${esc(sub)}</span>
    </a>`;
}

function sectionHTML(icon, title, links, startIndex, sectionIndex, extraClass = "") {
  return `
    <section class="category ${extraClass}" style="animation-delay:${sectionIndex * 60}ms">
      <header class="cat-head">
        <span class="cat-icon">${esc(icon)}</span>
        <h2>${esc(title)}</h2>
        <span class="cat-count">${links.length}</span>
        <i class="rule"></i>
      </header>
      <div class="links">${links.map((l, i) => cardHTML(l, startIndex + i)).join("")}</div>
    </section>`;
}

function letterHTML(name) {
  const chars = [...(name || "?")];
  const first = chars[0] || "?";
  const [c1, c2] = LETTER_COLORS[chars.reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % LETTER_COLORS.length];
  return `<span class="letter" style="background:linear-gradient(135deg,${c1},${c2})">${esc(first.toUpperCase())}</span>`;
}

function renderCategories(cats) {
  const root = $("#categories");

  if (!cats?.length) {
    root.innerHTML = `<div class="empty">还没有书签 —— 打开 <a href="/admin">后台管理</a> 添加第一个分类吧</div>`;
    return;
  }

  const allLinks = [];
  cats.forEach((cat) => cat.links.forEach((link) => allLinks.push(link)));
  const pinned = allLinks.filter((l) => l.pinned);
  const pinnedUrls = new Set(pinned.map((l) => l.url));
  const byUrl = new Map(allLinks.map((l) => [l.url, l]));

  // 最近访问：localStorage 里存 URL，过期/删除的链接自动忽略
  let recent = [];
  try {
    const urls = JSON.parse(store.get("nav-recent", "[]") || "[]");
    recent = urls
      .map((url) => byUrl.get(url))
      .filter((link) => link && !pinnedUrls.has(link.url))
      .slice(0, 8);
  } catch { /* 数据损坏时按没有最近访问处理 */ }

  const visibleCats = cats
    .map((cat) => ({ ...cat, links: cat.links.filter((l) => !l.pinned) }))
    .filter((cat) => cat.links.length);

  const sections = [];
  let index = 0;
  if (pinned.length) {
    sections.push(sectionHTML("⭐", "置顶", pinned, index, sections.length, "pinned-section"));
    index += pinned.length;
  }
  if (recent.length) {
    sections.push(sectionHTML("🕘", "最近访问", recent, index, sections.length, "recent-section"));
    index += recent.length;
  }
  visibleCats.forEach((cat) => {
    sections.push(sectionHTML(cat.icon || "📁", cat.name, cat.links, index, sections.length));
    index += cat.links.length;
  });

  if (!sections.length) {
    root.innerHTML = `<div class="empty">还没有书签 —— 打开 <a href="/admin">后台管理</a> 添加第一个分类吧</div>`;
    return;
  }

  root.innerHTML = sections.join("");
  bindFaviconLoad();
  applyStatus();
}

function bindFaviconLoad() {
  // 图标位默认显示首字母；图片加载成功后覆盖首字母，失败则重试两次后保留首字母
  $("#categories").querySelectorAll(".favicon").forEach((img) => {
    const show = () => {
      img.classList.add("is-ready");
      const letter = img.parentElement?.querySelector(".letter");
      if (letter) letter.style.visibility = "hidden";
    };
    img.addEventListener("load", show);
    img.addEventListener("error", () => {
      const tries = +(img.dataset.retry || 0);
      if (tries < 2) {
        img.dataset.retry = tries + 1;
        setTimeout(() => {
          img.src = img.src.replace(/&r=\d*/, "") + `&r=${tries + 1}`;
        }, 3000);
      } else {
        img.remove();   // 保留底层首字母，不再出现空白块
      }
    });
    if (img.complete && img.naturalWidth > 0) show();   // 极快命中缓存时补一次
  });
}

/* ---------- 4. 服务在线状态 ---------- */
let STATUS = {};

async function loadStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    STATUS = await res.json();
    applyStatus(STATUS);
  } catch { /* 后端不可达时维持旧状态 */ }
}

function applyStatus(status = STATUS) {
  document.querySelectorAll(".status-dot").forEach((dot) => {
    const info = status[dot.dataset.host];
    dot.className = "status-dot";
    if (!info) {
      dot.title = "状态未知";
      return;
    }
    if (info.ok) {
      const warn = typeof info.code === "number" && info.code >= 500;
      dot.classList.add(warn ? "warn" : "online");
      const ms = Number.isFinite(info.ms) ? ` · ${info.ms}ms` : "";
      dot.title = `${warn ? "响应异常" : "在线"}${ms}${info.code ? ` · HTTP ${info.code}` : ""}`;
    } else {
      dot.classList.add("offline");
      dot.title = "离线";
    }
  });
}

/* ---------- 5. 最近访问：点击卡片时记录，下次打开页面时展示 ---------- */
document.addEventListener("click", (e) => {
  const card = e.target.closest?.(".card");
  if (!card) return;
  const url = card.getAttribute("href");
  if (!url) return;
  try {
    const list = JSON.parse(store.get("nav-recent", "[]") || "[]");
    const next = [url, ...list.filter((item) => item !== url)].slice(0, 12);
    store.set("nav-recent", JSON.stringify(next));
  } catch { /* 隐私模式下 localStorage 不可用时忽略 */ }
});

loadStatus();
setInterval(loadStatus, 60000);

/* ---------- 6. 本地书签筛选：输入即时过滤卡片（不是搜索引擎） ---------- */
const filterInput = $("#filterInput");

filterInput.addEventListener("input", () => {
  const q = filterInput.value.trim().toLowerCase();
  document.querySelectorAll(".category").forEach((sec) => {
    let shown = 0;
    sec.querySelectorAll(".card").forEach((card) => {
      const hit = !q
        || card.textContent.toLowerCase().includes(q)
        || card.href.toLowerCase().includes(q);
      card.classList.toggle("filtered-out", !hit);
      if (hit) shown++;
    });
    sec.classList.toggle("filtered-out", shown === 0);
  });
});

/* 快捷键：/ 聚焦筛选，Esc 清空并退出 */
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement !== filterInput) {
    e.preventDefault();
    filterInput.focus();
  } else if (e.key === "Escape" && document.activeElement === filterInput) {
    filterInput.value = "";
    filterInput.dispatchEvent(new Event("input"));
    filterInput.blur();
  }
});

/* ---------- 7. 启动：拉取后端数据（失败自动重试，避免白屏） ---------- */
async function boot() {
  const ctrl = new AbortController();           // 手动超时：兼容所有浏览器
  const timer = setTimeout(() => ctrl.abort(), 5000);
  try {
    const res = await fetch("/api/data", { signal: ctrl.signal });
    if (!res.ok) throw new Error();
    STATE = await res.json();
    document.title = STATE.title || "Lodestar";
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
