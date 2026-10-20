"""图标解析测试：HTML 误判、data URI、apple-touch-icon、manifest 与缓存兼容"""

import base64
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402

SVG = (
    b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
    b"<rect width='64' height='64'/></svg>"
)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
PNG_SMALL = b"\x89PNG\r\n\x1a\n" + b"1" * 32
ICO = b"\x00\x00\x01\x00" + b"0" * 32

# 模拟 Tern 这类 SPA：多行 <link> + 内联 data URI SVG，且 /favicon.ico 返回同一份 HTML
SPA_HTML = (
    "<!doctype html><html><head><link\n"
    "  rel=\"icon\"\n"
    "  href=\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 64 64'><rect width='64' height='64'/></svg>\"\n"
    "/></head><body>not an icon</body></html>"
).encode()


@pytest.fixture
def icon_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ICON_DIR", str(tmp_path / "icons"))
    return tmp_path / "icons"


def fake_fetch(routes):
    """routes: {url: bytes | (bytes, final_url) | callable | Exception}"""
    calls = []

    def fetch(url, timeout=5, max_bytes=server.ICON_MAX_BYTES):
        calls.append(url)
        handler = routes.get(url)
        if handler is None:
            raise OSError(f"unexpected url: {url}")
        if isinstance(handler, BaseException):
            raise handler
        payload = handler() if callable(handler) else handler
        if isinstance(payload, tuple):
            return payload
        return payload, url

    return fetch, calls


# ---------- 内容识别 ----------
def test_svg_detection_is_strict():
    assert server.looks_like_image(SVG)
    assert server.is_svg_image(b"<?xml version='1.0'?><!-- c --><svg xmlns='x'></svg>")
    assert server.is_svg_image(b"\xef\xbb\xbf  <svg xmlns='x'/>")
    assert server.sniff_mime(SVG) == "image/svg+xml"

    # HTML 里出现内联 <svg 不能算图片（旧版会误判并缓存整页 HTML）
    html_with_svg = b"<!doctype html><html><body>" + b"x" * 500 + b"<svg></svg></body></html>"
    assert not server.looks_like_image(html_with_svg)
    assert server.sniff_mime(html_with_svg) == "application/octet-stream"
    # 截断 / 未闭合的 SVG 也不能算
    assert not server.is_svg_image(b"<svg xmlns=")
    assert not server.is_svg_image(b"<svg xmlns='x'>")


def test_manifest_mime_detection():
    assert server.sniff_mime(SPA_HTML) == "application/octet-stream"
    assert server.sniff_mime(PNG) == "image/png"
    assert server.sniff_mime(ICO) == "image/x-icon"


# ---------- data: URI ----------
def test_decode_data_uri():
    plain = "data:image/svg+xml,%3Csvg%20xmlns%3D%22x%22%3E%3C%2Fsvg%3E"
    assert server.decode_data_uri(plain) == b'<svg xmlns="x"></svg>'
    b64 = "data:image/svg+xml;base64," + base64.b64encode(SVG).decode()
    assert server.decode_data_uri(b64) == SVG
    assert server.decode_data_uri("data:image/svg+xml,<svg xmlns=") == b"<svg xmlns="
    assert server.decode_data_uri("not-a-data-uri") == b""
    assert server.decode_data_uri("") == b""


# ---------- HTML 解析 ----------
def test_parse_icon_links_handles_multiline_data_uri():
    icons, manifests = server.parse_icon_links(SPA_HTML.decode(), "https://example.com/")
    assert len(icons) == 1
    assert icons[0].startswith("data:image/svg+xml,")
    assert icons[0].endswith("</svg>")
    assert manifests == []


def test_parse_icon_links_priority_and_manifest():
    html = (
        '<html><head><base href="/app/">'
        '<link rel="apple-touch-icon" href="apple.png">'
        '<link rel="mask-icon" href="mask.svg">'
        '<link rel="icon" href="favicon.svg">'
        '<link rel="shortcut icon" href="shortcut.ico">'
        '<link rel="manifest" href="/site.webmanifest">'
        "</head></html>"
    )
    icons, manifests = server.parse_icon_links(html, "https://example.com/")
    assert icons == [
        "https://example.com/app/favicon.svg",
        "https://example.com/app/shortcut.ico",
        "https://example.com/app/apple.png",
        "https://example.com/app/mask.svg",
    ]
    assert manifests == ["https://example.com/site.webmanifest"]


# ---------- 缓存兼容 ----------
def test_icon_cache_discards_legacy_html(icon_dir):
    os.makedirs(icon_dir)
    path = icon_dir / "example.com"
    path.write_bytes(SPA_HTML)
    assert server.icon_cache("example.com") is None   # 旧版误缓存的 HTML 自动失效
    path.write_bytes(PNG)
    assert server.icon_cache("example.com") == PNG
    path.write_bytes(b"")
    assert server.icon_cache("example.com") == b""    # 负缓存保持有效


# ---------- 完整解析链路 ----------
def test_resolve_icon_from_inline_data_uri(icon_dir, monkeypatch):
    fetch, calls = fake_fetch({
        "https://example.com/favicon.ico": SPA_HTML,   # SPA fallback：HTML 而非图片
        "https://example.com/": SPA_HTML,
    })
    monkeypatch.setattr(server, "fetch", fetch)

    data = server.resolve_icon("example.com")
    assert data == SVG
    assert calls == ["https://example.com/favicon.ico", "https://example.com/"]
    assert (icon_dir / "example.com").read_bytes() == SVG

    # 第二次命中磁盘缓存，不再发请求
    assert server.resolve_icon("example.com") == SVG
    assert len(calls) == 2


def test_resolve_icon_uses_redirected_base(icon_dir, monkeypatch):
    """站点把 / 重定向到 /app/ 时，./icon.png 要基于最终地址解析（Navidrome 场景）"""
    html = b'<html><head><link rel="icon" href="./icon.png"></head></html>'
    fetch, calls = fake_fetch({
        "https://example.com/favicon.ico": OSError("404"),
        "https://example.com/": (html, "https://example.com/app/"),
        "https://example.com/app/icon.png": PNG,
    })
    monkeypatch.setattr(server, "fetch", fetch)

    assert server.resolve_icon("example.com") == PNG
    assert "https://example.com/app/icon.png" in calls


def test_manifest_icons_use_redirected_base(monkeypatch):
    manifest = json.dumps({"icons": [{"src": "./icon.png", "sizes": "64x64"}]}).encode()
    fetch, _ = fake_fetch({
        "https://example.com/manifest.webmanifest": (
            manifest, "https://example.com/app/manifest.webmanifest",
        ),
    })
    monkeypatch.setattr(server, "fetch", fetch)

    urls = server.manifest_icon_urls("https://example.com/manifest.webmanifest")
    assert urls == ["https://example.com/app/icon.png"]


def test_resolve_icon_from_apple_touch(icon_dir, monkeypatch):
    html = b'<html><head><link rel="apple-touch-icon" href="/apple.png"></head></html>'
    fetch, _ = fake_fetch({
        "https://example.com/favicon.ico": OSError("404"),
        "https://example.com/": html,
        "https://example.com/apple.png": ICO,
    })
    monkeypatch.setattr(server, "fetch", fetch)
    assert server.resolve_icon("example.com") == ICO


def test_resolve_icon_from_manifest(icon_dir, monkeypatch):
    html = b'<html><head><link rel="manifest" href="/manifest.webmanifest"></head></html>'
    manifest = json.dumps({"icons": [
        {"src": "/icon-64.png", "sizes": "64x64"},
        {"src": "/icon-512.png", "sizes": "512x512"},
    ]}).encode()
    fetch, calls = fake_fetch({
        "https://example.com/favicon.ico": OSError("404"),
        "https://example.com/": html,
        "https://example.com/manifest.webmanifest": manifest,
        "https://example.com/icon-512.png": PNG,
        "https://example.com/icon-64.png": PNG_SMALL,
    })
    monkeypatch.setattr(server, "fetch", fetch)

    assert server.resolve_icon("example.com") == PNG
    assert "https://example.com/icon-512.png" in calls
    assert "https://example.com/icon-64.png" not in calls   # 优先选大图，命中即停


def test_reject_non_http_icon_schemes(icon_dir, monkeypatch):
    html = (
        b'<html><head><link rel="icon" href="file:///etc/passwd">'
        b'<link rel="manifest" href="file:///etc/passwd"></head></html>'
    )
    fetch, calls = fake_fetch({
        "https://example.com/favicon.ico": OSError("404"),
        "https://example.com/": html,
    })
    monkeypatch.setattr(server, "fetch", fetch)

    assert server.resolve_icon("example.com") == b""
    assert calls == ["https://example.com/favicon.ico", "https://example.com/"]

    assert server._load_icon("file:///etc/passwd") == b""
    assert server._load_icon("javascript:alert(1)") == b""
    assert server.manifest_icon_urls("file:///etc/passwd") == []


def test_resolve_icon_failure_uses_negative_cache(icon_dir, monkeypatch):
    fetch, calls = fake_fetch({
        "https://example.com/favicon.ico": OSError("404"),
        "https://example.com/": OSError("timeout"),
    })
    monkeypatch.setattr(server, "fetch", fetch)

    assert server.resolve_icon("example.com") == b""
    assert (icon_dir / "example.com").read_bytes() == b""

    before = len(calls)
    assert server.resolve_icon("example.com") == b""   # 负缓存生效，不再重试
    assert len(calls) == before


# ---------- SVG 归一化 ----------
def test_normalize_svg_single_quotes():
    data = b"<svg xmlns='x' width='32' height='32'></svg>"
    out = server.normalize_svg(data)
    assert b'viewBox="0 0 32 32"' in out


# ---------- /api/icon 服务 ----------
def test_api_icon_serves_resolved_svg(icon_dir, tmp_path, monkeypatch):
    data_file = tmp_path / "bookmarks.json"
    data_file.write_text(
        json.dumps({"title": "t", "categories": [{
            "name": "c",
            "links": [{"name": "x", "url": "https://example.com", "desc": "", "icon": ""}],
        }]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "DATA_FILE", str(data_file))
    monkeypatch.setitem(server.DATA_CACHE, "mtime", None)
    monkeypatch.setitem(server.DATA_CACHE, "data", None)
    os.makedirs(icon_dir)
    (icon_dir / "example.com").write_bytes(SVG)

    with server.app.test_client() as client:
        resp = client.get("/api/icon?host=example.com")
        assert resp.status_code == 200
        assert resp.mimetype == "image/svg+xml"
        assert resp.data == SVG
