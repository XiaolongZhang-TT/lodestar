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
import time
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


# ---------- HTTP 处理 ----------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    # ---- 小工具 ----
    def reply_json(self, obj, status=200, cookie=None):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

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
