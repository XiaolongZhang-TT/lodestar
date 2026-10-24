#!/usr/bin/env python3
# ==========================================================
#  Lodestar · 个人导航页 —— 后端服务（Flask）
#
#  启动:  pip install -r requirements.txt
#         python3 server.py
#  配置:  环境变量 NAV_USER / NAV_PASS  后台账号密码
#                        NAV_PORT       监听端口（默认 8091）
#                        NAV_STATUS_INTERVAL  服务状态探测间隔（秒，0 关闭）
#  数据:  data/bookmarks.json   书签数据（保存时自动备份）
#         data/backups/         历史备份（保留最近 10 份）
#         data/secret.key       会话签名密钥（自动生成，勿外泄）
#         data/icons/           网站图标缓存
# ==========================================================

import base64
import hashlib
import hmac
import io
import json
import os
import queue
import re
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

from flask import Flask, jsonify, request, send_file

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "bookmarks.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
BACKUP_KEEP = 10

USER = os.environ.get("NAV_USER", "admin")
PASS = os.environ.get("NAV_PASS", "lodestar-admin")
PORT = int(os.environ.get("NAV_PORT", "8091"))

SESSION_HOURS = 24 * 7      # 登录会话有效期：一周
DEFAULT_DATA = {"title": "Lodestar · 我的导航", "name": "", "categories": []}


# =========================================================
#  数据读写：mtime 内存缓存 + 写锁 + 原子备份
# =========================================================
DATA_LOCK = threading.Lock()
DATA_CACHE = {"mtime": None, "data": None}


def load_data():
    with DATA_LOCK:
        return _load_data()


def _load_data():
    try:
        mtime = os.path.getmtime(DATA_FILE)
    except OSError:
        mtime = None
    if mtime is not None and DATA_CACHE["mtime"] == mtime:
        return DATA_CACHE["data"]

    data = None
    for path in (DATA_FILE, DATA_FILE + ".bak"):   # 主文件缺失/损坏时回退 .bak
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            break
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    if data is None:
        data = DEFAULT_DATA
        _save_data(data)   # 首次运行：落一份默认数据
        return data

    DATA_CACHE.update(mtime=mtime, data=data)
    return data


def save_data(data):
    with DATA_LOCK:
        _save_data(data)


def _save_data(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if os.path.exists(DATA_FILE):
        _rotate_backups()
        os.replace(DATA_FILE, DATA_FILE + ".bak")   # 锁内替换，进程内读方无感知
    os.replace(tmp, DATA_FILE)                      # 原子落盘，任意时刻文件完整
    DATA_CACHE.update(mtime=os.path.getmtime(DATA_FILE), data=data)


def _rotate_backups():
    """把上一份 .bak 归档到 backups/，只保留最近 N 份"""
    bak = DATA_FILE + ".bak"
    if not os.path.exists(bak):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        os.replace(bak, os.path.join(BACKUP_DIR, f"bookmarks-{stamp}.json"))
    except OSError:
        return
    old_files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("bookmarks-"))
    for name in old_files[:-BACKUP_KEEP]:
        try:
            os.remove(os.path.join(BACKUP_DIR, name))
        except OSError:
            pass


# =========================================================
#  会话：HMAC 签名的过期时间戳即令牌
# =========================================================
def load_secret():
    path = os.path.join(DATA_DIR, "secret.key")
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        os.makedirs(DATA_DIR, exist_ok=True)
        key = secrets.token_hex(32)
        with open(path, "w") as f:
            f.write(key)
        os.chmod(path, 0o600)
        return key


SECRET = load_secret()


def make_token():
    exp = str(int(time.time()) + SESSION_HOURS * 3600)
    sig = hmac.new(SECRET.encode(), exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}:{sig}"


def check_token(token):
    try:
        exp, sig = token.split(":", 1)
        expect = hmac.new(SECRET.encode(), exp.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expect) and int(exp) > time.time()
    except (ValueError, AttributeError):
        return False


def logged_in():
    return check_token(request.cookies.get("nav_token", ""))


# =========================================================
#  图标解析：只在后台线程做网络请求，请求线程永不阻塞
# =========================================================
ICON_DIR = os.path.join(DATA_DIR, "icons")
ICON_MAX_BYTES = 512 * 1024
MAX_ICON_CANDIDATES = 6      # 首页 icon 链接最多尝试几个
MAX_MANIFEST_CANDIDATES = 2  # manifest 最多尝试几个
ICON_LOCK = threading.Lock()     # 串行解析，避免并发冲击同一域名
ICON_QUEUE = queue.Queue()       # 待解析任务队列（后台 worker 消费）
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False   # 内网/自签证书的服务也要能取图标
SSL_CTX.verify_mode = ssl.CERT_NONE

# ---------- 服务在线状态 ----------
try:
    STATUS_INTERVAL = int(os.environ.get("NAV_STATUS_INTERVAL", "300"))
except ValueError:
    STATUS_INTERVAL = 300
if STATUS_INTERVAL != 0:
    STATUS_INTERVAL = max(60, STATUS_INTERVAL)   # 最小 60 秒；设为 0 可关闭
STATUS_ENABLED = STATUS_INTERVAL > 0
STATUS_TIMEOUT = 3
STATUS_CACHE = {}
STATUS_LOCK = threading.Lock()
STATUS_REFRESH = threading.Event()


def hosts_of(data):
    """从书签数据里提取出现过的 host:port 集合"""
    hosts = set()
    for cat in (data or {}).get("categories", []):
        for link in cat.get("links", []):
            try:
                hosts.add(urllib.parse.urlsplit(link["url"]).netloc)
            except Exception:
                pass
    return hosts


def known_hosts():
    """当前书签里出现过的 host:port 集合，图标代理只服务这些（防滥用）"""
    return hosts_of(load_data())


def probe_host(host):
    """探测一个 host 是否在线：有 HTTP 响应即算在线（401/403/404/5xx 也说明服务活着）"""
    start = time.time()
    code = None
    ok = False
    try:
        req = urllib.request.Request(
            f"https://{host}/",
            headers={"User-Agent": "Mozilla/5.0 lodestar-status-checker"},
        )
        with urllib.request.urlopen(req, timeout=STATUS_TIMEOUT, context=SSL_CTX) as r:
            r.read(1)                 # 读到首字节即可，避免下载整页
            code = r.status
            ok = True
    except urllib.error.HTTPError as e:
        code = e.code
        ok = True                     # 服务返回了 HTTP 错误，但进程是活着的
    except Exception:
        ok = False
    return {
        "ok": ok,
        "ms": int((time.time() - start) * 1000),
        "code": code,
        "at": int(time.time()),
    }


def _status_worker():
    """后台定时探测全部书签 host，结果写入 STATUS_CACHE"""
    while True:
        hosts = sorted(known_hosts())
        results = {}
        if hosts:
            with ThreadPoolExecutor(max_workers=4) as pool:
                for host, result in zip(hosts, pool.map(probe_host, hosts)):
                    results[host] = result
        with STATUS_LOCK:
            STATUS_CACHE.clear()
            STATUS_CACHE.update(results)
        STATUS_REFRESH.wait(STATUS_INTERVAL)
        STATUS_REFRESH.clear()


def fetch(url, timeout=5, max_bytes=ICON_MAX_BYTES):
    """请求 URL，返回 (内容, 最终 URL)；urllib 会自动跟随重定向"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 lodestar-icon-fetcher"})
    for attempt in (1, 2):  # 失败立即重试一次，消除瞬时网络抖动
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                return r.read(max_bytes), r.geturl()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)


def fetch_url(url, timeout=5, max_bytes=ICON_MAX_BYTES):
    """只要内容（兼容只关心字节的调用方）"""
    return fetch(url, timeout=timeout, max_bytes=max_bytes)[0]


def _svg_head(data):
    """跳过 BOM / XML 声明 / 注释，返回 SVG 根标签附近的头部；不是 SVG 时返回 b"""""
    head = data[:2048]
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    head = head.lstrip()
    if head[:5].lower() == b"<?xml":
        end = head.find(b"?>")
        if end < 0:
            return b""
        head = head[end + 2:].lstrip()
    while head.startswith(b"<!--"):
        end = head.find(b"-->")
        if end < 0:
            return b""
        head = head[end + 3:].lstrip()
    return head


def is_svg_image(data):
    """严格判断 SVG：根元素必须是完整的 <svg>，避免 HTML 里的内联 <svg 片段被误判"""
    head = _svg_head(data)
    if head[:4].lower() != b"<svg":
        return False
    tag_end = head.find(b">")
    if tag_end < 0:               # <svg 标签都没闭合，肯定不是有效图片
        return False
    if head[:tag_end].rstrip().endswith(b"/"):   # <svg ... />
        return True
    return b"</svg" in data.lower()


def looks_like_image(data):
    """很多 SPA 服务对任意路径都返回 200 + HTML，必须校验内容真的是图片"""
    if not data:
        return False
    if data[:4] == b"\x89PNG" or data[:3] == b"GIF8" or data[:3] == b"\xff\xd8\xff":
        return True
    if data[:4] in (b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"):  # ICO / CUR
        return True
    if data[:2] == b"BM":  # BMP
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return is_svg_image(data)


def sniff_mime(data):
    """按内容返回正确的 MIME。SVG 必须是 image/svg+xml，浏览器才肯当图片渲染"""
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:3] == b"GIF8":
        return "image/gif"
    if data[:4] in (b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"):
        return "image/x-icon"
    if data[:2] == b"BM":
        return "image/bmp"
    if is_svg_image(data):
        return "image/svg+xml"
    return "application/octet-stream"


# ---------- data: URI 图标 ----------
_DATA_URI_RE = re.compile(r"^data:([^,]*),(.*)$", re.S | re.I)


def decode_data_uri(uri, max_bytes=ICON_MAX_BYTES):
    """解码 data: URI（支持 base64 与百分号编码），不是合法 data URI 时返回 b"""""
    m = _DATA_URI_RE.match((uri or "").strip())
    if not m:
        return b""
    meta, payload = m.group(1), m.group(2)
    try:
        if ";base64" in meta.lower():
            raw = base64.b64decode(payload + "=" * (-len(payload) % 4))
        else:
            raw = urllib.parse.unquote_to_bytes(payload)
    except Exception:
        return b""
    return raw if 0 < len(raw) <= max_bytes else b""


# ---------- 从 HTML 里解析图标声明 ----------
class _IconLinkParser(HTMLParser):
    """用 HTMLParser 解析 <link>，正确处理多行标签、单双引号与 data: URI"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.base = ""
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = {k.lower(): (v or "").strip() for k, v in attrs}
        if tag.lower() == "base":
            if not self.base:
                self.base = attrs.get("href", "")
        elif tag.lower() == "link":
            rel = attrs.get("rel", "").lower().split()
            href = attrs.get("href", "")
            if rel and href:
                self.links.append((rel, href))


def _dedupe(items):
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def parse_icon_links(html, page_url):
    """返回 (icon_urls, manifest_urls)，图标按 favicon → apple-touch-icon → mask-icon 排序"""
    parser = _IconLinkParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    base = urllib.parse.urljoin(page_url, parser.base) if parser.base else page_url
    icons, apple, mask, manifests = [], [], [], []
    for rel, href in parser.links:
        rel_text = " ".join(rel)
        if "manifest" in rel:
            manifests.append(urllib.parse.urljoin(base, href))
        elif "apple-touch-icon" in rel_text:
            apple.append(urllib.parse.urljoin(base, href))
        elif "mask-icon" in rel_text:
            mask.append(urllib.parse.urljoin(base, href))
        elif "icon" in rel:
            icons.append(urllib.parse.urljoin(base, href))
    return _dedupe(icons + apple + mask), _dedupe(manifests)


def _parse_size(sizes):
    """把 manifest 的 sizes（如 "16x16 32x32"）转成面积，用于优先选大图"""
    best = 0
    for part in str(sizes or "").lower().split():
        w, sep, h = part.partition("x")
        if sep and w.isdigit() and h.isdigit():
            best = max(best, int(w) * int(h))
    return best


def manifest_icon_urls(manifest_url, max_icons=3):
    """读取 Web App Manifest 的 icons，按尺寸从大到小返回图标 URL"""
    manifest_url = (manifest_url or "").strip()
    if not manifest_url.lower().startswith(("http://", "https://", "data:")):
        return []
    try:
        if manifest_url.lower().startswith("data:"):
            raw = decode_data_uri(manifest_url)
            manifest_base = manifest_url
        else:
            raw, manifest_base = fetch(manifest_url)
        manifest = json.loads(raw.decode("utf-8", "ignore"))
        icons = manifest.get("icons", []) if isinstance(manifest, dict) else []
    except Exception:
        return []
    candidates = []
    for icon in icons:
        if not isinstance(icon, dict):
            continue
        src = str(icon.get("src", "")).strip()
        if src:
            candidates.append((_parse_size(icon.get("sizes")), src))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return _dedupe([urllib.parse.urljoin(manifest_base, src) for _, src in candidates])[:max_icons]


def _load_icon(url):
    """取单个候选图标（支持 data: URI 与 http(s)），内容不是图片则返回 b"""""
    try:
        url = (url or "").strip()
        if url.lower().startswith("data:"):
            data = decode_data_uri(url)
        elif re.match(r"^https?://", url, re.I):
            data = fetch_url(url)
        else:  # file: / javascript: 等一律拒绝，避免被页面声明利用读取本地文件
            return b""
        return data if looks_like_image(data) else b""
    except Exception:
        return b""


def normalize_svg(data):
    """给缺 viewBox 的 SVG 补上：否则缩放渲染时内容被裁剪而非缩放（如 AList 的图标）"""
    try:
        text = data.decode("utf-8", "ignore")
        m = re.search(r"<svg\b[^>]*>", text)
        if not m or "viewBox" in m.group(0):
            return data
        tag = m.group(0)
        w = re.search(r"""width=["']([\d.]+)["']""", tag)
        h = re.search(r"""height=["']([\d.]+)["']""", tag)
        if not (w and h):
            return data
        patched = tag.replace("<svg", f'<svg viewBox="0 0 {w.group(1)} {h.group(1)}"', 1)
        return text.replace(tag, patched, 1).encode()
    except Exception:
        return data


def icon_cache(host):
    """只读缓存，不发网络请求。返回 b"" 表示负缓存有效（确定无图标），None 表示需要解析"""
    cache = os.path.join(ICON_DIR, host.replace(":", "_"))
    if not os.path.exists(cache):
        return None
    age = time.time() - os.path.getmtime(cache)
    with open(cache, "rb") as f:
        data = f.read()
    if data and age < 7 * 24 * 3600:   # 成功缓存 7 天
        return data if looks_like_image(data) else None   # 兼容旧版误缓存的 HTML
    if not data and age < 600:         # 失败负缓存 10 分钟后可重试（网络抖动恢复要快）
        return data
    return None                        # 缓存缺失或已过期


def resolve_icon(host):
    """完整解析（含网络请求）。只在后台 worker / 预热线程中调用"""
    with ICON_LOCK:
        cached = icon_cache(host)
        if cached is not None:
            return cached

        data = b""
        base = f"https://{host}/"
        try:  # 1) 标准路径 /favicon.ico
            got = fetch_url(base + "favicon.ico")
            if looks_like_image(got):
                data = got
        except Exception:
            pass

        if not data:
            try:  # 2) 首页声明的 icon（含 data: URI）、apple-touch-icon、mask-icon
                page, final_url = fetch(base)
                html = page.decode("utf-8", "ignore")
                # 用重定向后的最终地址作为基准，./icon.png 这类相对路径才能拼对
                icon_urls, manifest_urls = parse_icon_links(html, final_url)
                for url in icon_urls[:MAX_ICON_CANDIDATES]:
                    data = _load_icon(url)
                    if data:
                        break
                if not data:  # 3) Web App Manifest 里的 icons
                    for manifest_url in manifest_urls[:MAX_MANIFEST_CANDIDATES]:
                        for url in manifest_icon_urls(manifest_url):
                            data = _load_icon(url)
                            if data:
                                break
                        if data:
                            break
            except Exception:
                pass

        os.makedirs(ICON_DIR, exist_ok=True)
        with open(os.path.join(ICON_DIR, host.replace(":", "_")), "wb") as f:
            f.write(data)              # 成功与失败都缓存
        return data


def _icon_worker():
    while True:
        host = ICON_QUEUE.get()
        try:
            resolve_icon(host)
        except Exception:
            pass
        finally:
            ICON_QUEUE.task_done()


def warm_icons(hosts=None):
    """把指定 host 入队预热；不传参数时预热全部（仅供启动时使用）"""
    for host in sorted(known_hosts() if hosts is None else hosts):
        ICON_QUEUE.put(host)


# =========================================================
#  提交数据校验：只保留认识的字段，错误定位到具体条目
# =========================================================
URL_RE = re.compile(r"^https?://\S+$")


def sanitize(data):
    """返回 (干净数据, None) 或 (None, 人类可读的错误信息)"""
    if not isinstance(data, dict):
        return None, "数据格式不正确"
    categories = []
    for ci, cat in enumerate(data.get("categories", []), 1):
        if not isinstance(cat, dict) or not str(cat.get("name", "")).strip():
            return None, f"第 {ci} 个分类缺少名称"
        links = []
        for li, link in enumerate(cat.get("links", []), 1):
            if not isinstance(link, dict):
                return None, f"「{cat['name']}」第 {li} 条链接格式不正确"
            url = str(link.get("url", "")).strip()
            if not str(link.get("name", "")).strip():
                return None, f"「{cat['name']}」第 {li} 条链接缺少名称"
            if not URL_RE.match(url):
                return None, f"「{cat['name']}」第 {li} 条链接的网址需要以 http(s):// 开头"
            links.append({
                "name": str(link["name"]).strip(),
                "url": url,
                "desc": str(link.get("desc", "")).strip(),
                "icon": str(link.get("icon", "")).strip(),
                "pinned": link.get("pinned") is True,
            })
        categories.append({
            "name": str(cat["name"]).strip(),
            "icon": str(cat.get("icon", "")).strip(),
            "links": links,
        })
    return {
        "title": str(data.get("title", "")).strip() or "Lodestar · 我的导航",
        "name": str(data.get("name", "")).strip(),
        "categories": categories,
    }, None


# =========================================================
#  Web 应用
# =========================================================
app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 1_000_000               # 请求体上限 1MB
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 7 * 24 * 3600    # 版本化 ?v=N 资源可长缓存
app.json.ensure_ascii = False                              # JSON 中文原样输出


# ---------- 页面 ----------
@app.get("/")
def page_index():
    resp = app.send_static_file("index.html")
    resp.headers["Cache-Control"] = "no-cache"   # HTML 必须重验证，子资源才能安全长缓存
    return resp


@app.get("/admin")
def page_admin():
    resp = app.send_static_file("admin.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ---------- 会话 API ----------
@app.post("/api/login")
def api_login():
    body = request.get_json(silent=True) or {}
    user_ok = hmac.compare_digest(str(body.get("user", "")), USER)
    pass_ok = hmac.compare_digest(str(body.get("pass", "")), PASS)
    if not (user_ok and pass_ok):
        time.sleep(0.5)  # 拖慢暴力尝试
        return jsonify(ok=False, msg="用户名或密码错误"), 401

    resp = jsonify(ok=True)
    resp.set_cookie("nav_token", make_token(), max_age=SESSION_HOURS * 3600,
                    httponly=True, samesite="Lax", path="/")
    return resp


@app.post("/api/logout")
def api_logout():
    resp = jsonify(ok=True)
    resp.set_cookie("nav_token", "", max_age=0, httponly=True, samesite="Lax", path="/")
    return resp


@app.get("/api/auth")
def api_auth():
    """后台页面据此决定显示登录框还是编辑器"""
    if logged_in():
        return jsonify(ok=True)
    return jsonify(ok=False), 401


# ---------- 书签数据 API ----------
@app.get("/api/data")
def api_data_get():
    return jsonify(load_data())


@app.post("/api/data")
def api_data_save():
    if not logged_in():
        return jsonify(ok=False, msg="请先登录"), 401
    clean, err = sanitize(request.get_json(silent=True))
    if err:
        return jsonify(ok=False, msg=err), 400
    old_hosts = hosts_of(load_data())
    save_data(clean)
    new_hosts = hosts_of(clean) - old_hosts
    if new_hosts:
        warm_icons(new_hosts)   # 只预热本次新增（或改了域名）的 host
    STATUS_REFRESH.set()        # 立即刷新在线状态，不用等下一轮
    return jsonify(ok=True)


# ---------- 服务状态 API ----------
@app.get("/api/status")
def api_status():
    with STATUS_LOCK:
        return jsonify(dict(STATUS_CACHE))


# ---------- 图标代理 API ----------
@app.get("/api/icon")
def api_icon():
    host = request.args.get("host", "")
    if not host or host not in known_hosts():
        return jsonify(ok=False, msg="host 不在书签列表中"), 403

    data = icon_cache(host)
    if data is None:   # 无缓存/已过期：入队后台解析，本次立即返回
        ICON_QUEUE.put(host)
        return jsonify(ok=False, msg="解析中，稍后自动重试"), 404
    if not data:
        return jsonify(ok=False, msg="未解析到图标"), 404

    mime = sniff_mime(data)
    if mime == "image/svg+xml":
        data = normalize_svg(data)   # 补 viewBox，让无坐标系的 SVG 能正常缩放
    resp = send_file(io.BytesIO(data), mimetype=mime)
    resp.headers["Cache-Control"] = "public, max-age=3600"   # 图标按 host 稳定，1 小时免回源
    return resp


# ---------- 通用 ----------
@app.after_request
def add_cache_headers(resp):
    resp.headers.setdefault("Cache-Control", "no-cache")
    return resp


def main():
    load_data()  # 确保数据文件存在
    print(f"Lodestar 导航页已启动: http://127.0.0.1:{PORT}  （后台管理 http://127.0.0.1:{PORT}/admin）", flush=True)
    if USER == "admin" and PASS == "lodestar-admin":
        print("⚠️  正在使用默认账号 admin / lodestar-admin，请通过环境变量 NAV_USER / NAV_PASS 修改！", flush=True)

    threading.Thread(target=_icon_worker, daemon=True).start()
    warm_icons()  # 启动即预热全部图标
    if STATUS_ENABLED:
        threading.Thread(target=_status_worker, daemon=True).start()

    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=PORT, threads=8)
    except ImportError:
        # 未装 waitress 时退回 Flask 自带服务器（家用足够）
        app.run(host="0.0.0.0", port=PORT, threaded=True)


if __name__ == "__main__":
    main()
