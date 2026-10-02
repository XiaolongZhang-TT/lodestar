#!/usr/bin/env python3
# ==========================================================
#  Nav · 个人导航页 —— 后端服务（Flask）
#
#  启动:  pip install -r requirements.txt
#         python3 server.py
#  配置:  环境变量 NAV_USER / NAV_PASS  后台账号密码
#                        NAV_PORT       监听端口（默认 8091）
#  数据:  data/bookmarks.json  书签数据（后台保存后写回这里）
#         data/secret.key      会话签名密钥（自动生成，勿外泄）
#         data/icons/          网站图标缓存
# ==========================================================

import hashlib
import hmac
import io
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

from flask import Flask, jsonify, request, send_file

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "bookmarks.json")

USER = os.environ.get("NAV_USER", "admin")
PASS = os.environ.get("NAV_PASS", "nav-admin")
PORT = int(os.environ.get("NAV_PORT", "8091"))

SESSION_HOURS = 24 * 7      # 登录会话有效期：一周
DEFAULT_DATA = {"title": "Nav · 我的导航", "name": "", "categories": []}


# =========================================================
#  数据读写
# =========================================================
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
#  图标解析：/favicon.ico → 首页 HTML 里的 <link rel=icon>，结果缓存
# =========================================================
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


# =========================================================
#  提交数据校验：只保留认识的字段
# =========================================================
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


# =========================================================
#  Web 应用
# =========================================================
app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 1_000_000   # 请求体上限 1MB
app.json.ensure_ascii = False                  # JSON 中文原样输出


# ---------- 页面 ----------
@app.get("/")
def page_index():
    return app.send_static_file("index.html")


@app.get("/admin")
def page_admin():
    return app.send_static_file("admin.html")


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
    clean = sanitize(request.get_json(silent=True))
    if clean is None:
        return jsonify(ok=False, msg="书签数据不合法：每条链接都需要名称和 http(s) 网址"), 400
    save_data(clean)
    return jsonify(ok=True)


# ---------- 图标代理 API ----------
@app.get("/api/icon")
def api_icon():
    host = request.args.get("host", "")
    if not host or host not in known_hosts():
        return jsonify(ok=False, msg="host 不在书签列表中"), 403
    data = resolve_icon(host)
    if not data:
        return jsonify(ok=False, msg="未解析到图标"), 404
    return send_file(io.BytesIO(data), mimetype="image/x-icon")


# ---------- 通用：所有响应都要求浏览器重验证缓存 ----------
@app.after_request
def add_cache_headers(resp):
    resp.headers.setdefault("Cache-Control", "no-cache")
    return resp


def main():
    load_data()  # 确保数据文件存在
    print(f"Nav 导航页已启动: http://127.0.0.1:{PORT}  （后台管理 http://127.0.0.1:{PORT}/admin）", flush=True)
    if USER == "admin" and PASS == "nav-admin":
        print("⚠️  正在使用默认账号 admin / nav-admin，请通过环境变量 NAV_USER / NAV_PASS 修改！", flush=True)
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=PORT, threads=8)
    except ImportError:
        # 未装 waitress 时退回 Flask 自带服务器（家用足够）
        app.run(host="0.0.0.0", port=PORT, threaded=True)


if __name__ == "__main__":
    main()
