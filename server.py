#!/usr/bin/env python3
# ==========================================================
#  Nav · 个人导航页 —— 后端服务（Flask）
#
#  启动:  pip install -r requirements.txt
#         python3 server.py
#  配置:  环境变量 NAV_USER / NAV_PASS  后台账号密码
#                        NAV_PORT       监听端口（默认 8091）
#  数据:  data/bookmarks.json   书签数据（保存时自动备份）
#         data/backups/         历史备份（保留最近 10 份）
#         data/secret.key       会话签名密钥（自动生成，勿外泄）
#         data/icons/           网站图标缓存
# ==========================================================

import hashlib
import hmac
import io
import json
import os
import queue
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
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
BACKUP_KEEP = 10

USER = os.environ.get("NAV_USER", "admin")
PASS = os.environ.get("NAV_PASS", "nav-admin")
PORT = int(os.environ.get("NAV_PORT", "8091"))

SESSION_HOURS = 24 * 7      # 登录会话有效期：一周
DEFAULT_DATA = {"title": "Nav · 我的导航", "name": "", "categories": []}


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
ICON_LOCK = threading.Lock()     # 串行解析，避免并发冲击同一域名
ICON_QUEUE = queue.Queue()       # 待解析任务队列（后台 worker 消费）
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False   # 内网/自签证书的服务也要能取图标
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


def sniff_mime(data):
    """按内容返回正确的 MIME。SVG 必须是 image/svg+xml，浏览器才肯当图片渲染"""
    if data[:4] == b"\x89PNG":                    return "image/png"
    if data[:3] == b"\xff\xd8\xff":               return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP": return "image/webp"
    if data[:3] == b"GIF8":                       return "image/gif"
    if data[:4] in (b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"): return "image/x-icon"
    if data[:2] == b"BM":                         return "image/bmp"
    if b"<svg" in data[:1024].lower():            return "image/svg+xml"
    return "application/octet-stream"


def normalize_svg(data):
    """给缺 viewBox 的 SVG 补上：否则缩放渲染时内容被裁剪而非缩放（如 AList 的图标）"""
    try:
        text = data.decode("utf-8", "ignore")
        m = re.search(r"<svg\b[^>]*>", text)
        if not m or "viewBox" in m.group(0):
            return data
        tag = m.group(0)
        w = re.search(r'width="([\d.]+)"', tag)
        h = re.search(r'height="([\d.]+)"', tag)
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
        return data
    if not data and age < 3600:        # 失败负缓存 1 小时
        return data
    return None                        # 缓存缺失或已过期


def resolve_icon(host):
    """完整解析（含网络请求）。只在后台 worker / 预热线程中调用"""
    with ICON_LOCK:
        cached = icon_cache(host)
        if cached is not None:
            return cached

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


def warm_icons():
    """把全部书签 host 入队预热（启动和每次保存后调用）"""
    for host in sorted(known_hosts()):
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
    save_data(clean)
    warm_icons()   # 新书签的图标后台预热
    return jsonify(ok=True)


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
    print(f"Nav 导航页已启动: http://127.0.0.1:{PORT}  （后台管理 http://127.0.0.1:{PORT}/admin）", flush=True)
    if USER == "admin" and PASS == "nav-admin":
        print("⚠️  正在使用默认账号 admin / nav-admin，请通过环境变量 NAV_USER / NAV_PASS 修改！", flush=True)

    threading.Thread(target=_icon_worker, daemon=True).start()
    warm_icons()  # 启动即预热全部图标

    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=PORT, threads=8)
    except ImportError:
        # 未装 waitress 时退回 Flask 自带服务器（家用足够）
        app.run(host="0.0.0.0", port=PORT, threaded=True)


if __name__ == "__main__":
    main()
