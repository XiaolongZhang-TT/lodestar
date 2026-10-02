"""核心纯函数的单元测试：数据校验 / 会话令牌 / 图标内容识别

运行：pip install pytest && pytest
"""

import hashlib
import hmac
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402


# ---------- sanitize：书签数据校验 ----------
def test_sanitize_ok():
    data = {
        "title": "测试", "name": "张三",
        "categories": [{"name": "常用", "icon": "📁", "links": [
            {"name": "示例", "url": "https://example.com", "desc": " 备注 ", "icon": "🌐"},
        ]}],
    }
    clean, err = server.sanitize(data)
    assert err is None
    assert clean["title"] == "测试"
    link = clean["categories"][0]["links"][0]
    assert link["desc"] == "备注"          # 去除首尾空白
    assert link["url"] == "https://example.com"


def test_sanitize_bad_url_position():
    _, err = server.sanitize({"categories": [
        {"name": "开发", "links": [
            {"name": "a", "url": "https://ok"},
            {"name": "b", "url": "192.168.1.5:8080"},   # 缺协议
        ]},
    ]})
    assert err is not None and "第 2 条" in err and "http(s)" in err


def test_sanitize_missing_name_position():
    _, err = server.sanitize({"categories": [
        {"name": "开发", "links": [{"name": "", "url": "https://a"}]},
    ]})
    assert err is not None and "缺少名称" in err


def test_sanitize_not_dict():
    _, err = server.sanitize("not a dict")
    assert err is not None


# ---------- 会话令牌 ----------
def test_token_roundtrip():
    assert server.check_token(server.make_token())


def test_token_tampered():
    assert not server.check_token("1234567890:deadbeef")


def test_token_expired():
    exp = str(int(time.time()) - 10)   # 十秒前就过期
    sig = hmac.new(server.SECRET.encode(), exp.encode(), hashlib.sha256).hexdigest()
    assert not server.check_token(f"{exp}:{sig}")


def test_token_garbage():
    for bad in ("", "abc", "1:2:3", None):
        assert not server.check_token(bad)


# ---------- 图标内容识别 ----------
def test_image_magic():
    assert server.looks_like_image(b"\x89PNG\r\n\x1a\n" + b"0" * 20)     # PNG
    assert server.looks_like_image(b"\x00\x00\x01\x00" + b"0" * 20)      # ICO
    assert server.looks_like_image(b"<svg xmlns=...></svg>")             # SVG
    assert server.looks_like_image(b"\xff\xd8\xff\xe0" + b"0" * 20)      # JPEG


def test_html_is_not_image():
    # SPA 对任意路径返回 200 + HTML，绝不能当图标
    assert not server.looks_like_image(b"<!DOCTYPE html><html><body>hi</body></html>")
    assert not server.looks_like_image(b"")


# ---------- MIME 识别（SVG 必须返回 image/svg+xml 浏览器才渲染） ----------
def test_sniff_mime():
    assert server.sniff_mime(b"\x89PNG\r\n\x1a\n" + b"0" * 8) == "image/png"
    assert server.sniff_mime(b"\xff\xd8\xff" + b"0" * 8) == "image/jpeg"
    assert server.sniff_mime(b"RIFF\x00\x00\x00\x00WEBP") == "image/webp"
    assert server.sniff_mime(b"\x00\x00\x01\x00" + b"0" * 8) == "image/x-icon"
    assert server.sniff_mime(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>') == "image/svg+xml"
