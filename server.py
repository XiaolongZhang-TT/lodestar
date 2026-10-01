#!/usr/bin/env python3
# ==========================================================
#  Nav · 个人导航页 —— 后端服务（仅 Python 标准库，零依赖）
#
#  职责：托管静态页面 / 提供书签数据 API / 后台登录会话
#
#  启动:  python3 server.py
#  配置:  环境变量 NAV_USER / NAV_PASS  后台账号密码
#                        NAV_PORT       监听端口（默认 8091）
#  数据:  data/bookmarks.json  书签数据（后台保存后写回这里）
#         data/secret.key      会话签名密钥（自动生成，勿外泄）
# ==========================================================

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import ssl
import threading
import time
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "bookmarks.json")

USER = os.environ.get("NAV_USER", "admin")
PASS = os.environ.get("NAV_PASS", "nav-admin")
PORT = int(os.environ.get("NAV_PORT", "8091"))

SESSION_HOURS = 24 * 7      # 登录会话有效期：一周
MAX_BODY = 1_000_000        # 请求体上限 1MB
DEFAULT_DATA = {"title": "Nav · 我的导航", "name": "", "categories": []}


# ---------- 数据读写 ----------
def load_data():
    # 主文件缺失或损坏时依次回退，避免读到半份数据
    for path in (DATA_FILE, DATA_FILE + ".bak"):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    save_data(DEFAULT_DATA)  # 首次运行：落一份默认数据
    return DEFAULT_DATA


def save_data(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if os.path.exists(DATA_FILE):
        shutil.copyfile(DATA_FILE, DATA_FILE + ".bak")  # 备份旧数据（原文件保持完整）
    os.replace(tmp, DATA_FILE)  # 原子替换，任意时刻读到的都是完整文件


# ---------- 会话：HMAC 签名的过期时间戳即令牌 ----------
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


# ---------- 提交数据校验：只保留认识的字段 ----------
URL_RE = re.compile(r"^https?://\S+$")


def sanitize(data):
    if not isinstance(data, dict):
        return None
    categories = []
    for cat in data.get("categories", []):
        if not isinstance(cat, dict) or not str(cat.get("name", "")).strip():
            return None
        links = []
        for link in cat.get("links", []):
            if not isinstance(link, dict):
                return None
            url = str(link.get("url", "")).strip()
            if not str(link.get("name", "")).strip() or not URL_RE.match(url):
                return None
            links.append({
                "name": str(link["name"]).strip(),
                "url": url,
                "desc": str(link.get("desc", "")).strip(),
                "icon": str(link.get("icon", "")).strip(),
            })
        categories.append({
            "name": str(cat["name"]).strip(),
            "icon": str(cat.get("icon", "")).strip(),
            "links": links,
        })
    return {
        "title": str(data.get("title", "")).strip() or "Nav · 我的导航",
        "name": str(data.get("name", "")).strip(),
        "categories": categories,
    }


# ---------- 图标解析：/favicon.ico → 首页 HTML 里的 <link rel=icon>，结果缓存 ----------
ICON_DIR = os.path.join(DATA_DIR, "icons")
ICON_LOCK = threading.Lock()   # 串行解析，避免并发冲击同一域名导致握手超时
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False  # 内网/自签证书的服务也要能取图标
SSL_CTX.verify_mode = ssl.CERT_NONE


def known_hosts():
    """当前书签里出现过的 host:port 集合，图标代理只服务这些（防滥用）"""
    hosts = set()
    for cat in load_data().get("categories", []):
        for link in cat.get("links", []):
            try:
                hosts.add(urllib.parse.urlsplit(link["url"]).netloc)
            except Exception:
                pass
    return hosts


def fetch_url(url, timeout=5, max_bytes=512 * 1024):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 nav-icon-fetcher"})
    for attempt in (1, 2):  # 失败立即重试一次，消除瞬时网络抖动
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                return r.read(max_bytes)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)


def looks_like_image(data):
    """很多 SPA 服务对任意路径都返回 200 + HTML，必须校验内容真的是图片"""
    if not data:
        return False
    if data[:4] == b"\x89PNG":                    return True
    if data[:3] == b"GIF8":                       return True
    if data[:3] == b"\xff\xd8\xff":               return True  # JPEG
    if data[:4] in (b"\x00\x00\x01\x00",          # ICO
                    b"\x00\x00\x02\x00"):         return True  # CUR
    if data[:2] == b"BM":                         return True  # BMP
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP": return True
    if b"<svg" in data[:1024].lower():            return True  # SVG
    return False


def resolve_icon(host):
    with ICON_LOCK:  # 串行解析 + 双重检查缓存，同一时刻只对外发一个请求
        os.makedirs(ICON_DIR, exist_ok=True)
        cache = os.path.join(ICON_DIR, host.replace(":", "_"))

        if os.path.exists(cache):
            age = time.time() - os.path.getmtime(cache)
            with open(cache, "rb") as f:
                data = f.read()
            if data and age < 7 * 24 * 3600:   # 成功缓存 7 天
                return data
            if not data and age < 3600:        # 失败负缓存 1 小时后可重试
                return data

        data = b""
        try:
            got = fetch_url(f"https://{host}/favicon.ico")
            if looks_like_image(got):
                data = got
        except Exception:
            pass
        if not data:
            try:  # 抓首页，解析 <link rel="icon" href="..."> 再下载
                html = fetch_url(f"https://{host}/").decode("utf-8", "ignore")
                m = (re.search(r'<link[^>]+rel=["\'](?:shortcut )?icon["\'][^>]*href=["\']([^"\']+)["\']', html, re.I)
                     or re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]*rel=["\'](?:shortcut )?icon["\']', html, re.I))
                if m:
                    got = fetch_url(urllib.parse.urljoin(f"https://{host}/", m.group(1)))
                    if looks_like_image(got):
                        data = got
            except Exception:
                pass

        with open(cache, "wb") as f:   # 成功与失败都缓存
            f.write(data)
        return data


# ---------- HTTP 处理 ----------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    # ---- 小工具 ----
    def reply_bytes(self, body, ctype, status=200, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def reply_json(self, obj, status=200, cookie=None):
        self.reply_bytes(json.dumps(obj, ensure_ascii=False).encode(),
                         "application/json; charset=utf-8", status, cookie)

    def end_headers(self):
        # 所有响应都要求浏览器重验证后再用缓存，保证更新（代码/数据）立即生效
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not 0 < length <= MAX_BODY:
            return None
        return json.loads(self.rfile.read(length).decode())

    def logged_in(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get("nav_token")
        return bool(token and check_token(token.value))

    # ---- GET：API + 静态页面 ----
    def do_GET(self):
        if self.path == "/api/data":
            return self.reply_json(load_data())

        if self.path == "/api/auth":  # 后台页面据此决定显示登录框还是编辑器
            ok = self.logged_in()
            return self.reply_json({"ok": ok}, 200 if ok else 401)

        if self.path.startswith("/api/icon"):  # 图标代理：只解析书签里的 host
            host = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("host", [""])[0]
            if not host or host not in known_hosts():
                return self.send_error(403)
            data = resolve_icon(host)
            if not data:
                return self.send_error(404)
            return self.reply_bytes(data, "image/x-icon")

        if self.path == "/admin":
            self.path = "/admin.html"

        # data/ 里的数据和密钥、后端源码不允许被当静态文件下载
        if self.path.startswith("/data/") or self.path.startswith("/.") or self.path == "/server.py":
            return self.send_error(403, "Forbidden")

        return super().do_GET()

    # ---- POST：登录 / 登出 / 保存数据 ----
    def do_POST(self):
        if self.path == "/api/login":
            try:
                body = self.read_body() or {}
            except json.JSONDecodeError:
                return self.reply_json({"ok": False, "msg": "请求格式错误"}, 400)
            user_ok = hmac.compare_digest(str(body.get("user", "")), USER)
            pass_ok = hmac.compare_digest(str(body.get("pass", "")), PASS)
            if user_ok and pass_ok:
                cookie = (f"nav_token={make_token()}; Path=/; HttpOnly; "
                          f"SameSite=Lax; Max-Age={SESSION_HOURS * 3600}")
                return self.reply_json({"ok": True}, cookie=cookie)
            time.sleep(0.5)  # 拖慢暴力尝试
            return self.reply_json({"ok": False, "msg": "用户名或密码错误"}, 401)

        if self.path == "/api/logout":
            return self.reply_json({"ok": True},
                                   cookie="nav_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")

        if self.path == "/api/data":
            if not self.logged_in():
                return self.reply_json({"ok": False, "msg": "请先登录"}, 401)
            try:
                clean = sanitize(self.read_body())
            except json.JSONDecodeError:
                return self.reply_json({"ok": False, "msg": "请求格式错误"}, 400)
            if clean is None:
                return self.reply_json(
                    {"ok": False, "msg": "书签数据不合法：每条链接都需要名称和 http(s) 网址"}, 400)
            save_data(clean)
            return self.reply_json({"ok": True})

        return self.send_error(404)


def main():
    load_data()  # 确保数据文件存在
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Nav 导航页已启动: http://127.0.0.1:{PORT}  （后台管理 http://127.0.0.1:{PORT}/admin）", flush=True)
    if USER == "admin" and PASS == "nav-admin":
        print("⚠️  正在使用默认账号 admin / nav-admin，请通过环境变量 NAV_USER / NAV_PASS 修改！", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
