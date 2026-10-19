"""Web 接口测试：登录 / 鉴权 / 数据读写 / 图标代理权限

这些测试使用 Flask test client，并把数据目录指向 tmp_path，
不会读写仓库里的 data/ 目录。
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "DATA_FILE", str(tmp_path / "bookmarks.json"))
    monkeypatch.setattr(server, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(server, "ICON_DIR", str(tmp_path / "icons"))
    monkeypatch.setitem(server.DATA_CACHE, "mtime", None)
    monkeypatch.setitem(server.DATA_CACHE, "data", None)
    monkeypatch.setitem(server.app.config, "TESTING", True)
    with server.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def fast_login(monkeypatch):
    """失败登录会 sleep 0.5s 防暴力破解，测试里跳过等待"""
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)


def login(client, user="admin", password=None):
    return client.post(
        "/api/login",
        json={"user": user, "pass": password if password is not None else server.PASS},
    )


# ---------- 页面 ----------
def test_pages_render(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "Lodestar" in index.get_data(as_text=True)

    admin = client.get("/admin")
    assert admin.status_code == 200
    assert "Lodestar" in admin.get_data(as_text=True)


def test_manifest(client):
    resp = client.get("/manifest.webmanifest")
    assert resp.status_code == 200
    assert resp.get_json()["short_name"] == "Lodestar"


# ---------- 鉴权 ----------
def test_data_is_public(client):
    resp = client.get("/api/data")
    assert resp.status_code == 200
    assert "categories" in resp.get_json()
    # 首次读取会用默认数据落盘
    assert os.path.exists(server.DATA_FILE)


def test_save_requires_login(client):
    resp = client.post("/api/data", json={"categories": []})
    assert resp.status_code == 401
    assert resp.get_json()["ok"] is False


def test_login_success_and_logout(client, fast_login):
    assert client.get("/api/auth").status_code == 401

    resp = login(client)
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert client.get("/api/auth").status_code == 200

    client.post("/api/logout")
    assert client.get("/api/auth").status_code == 401


def test_login_failure(client, fast_login):
    resp = login(client, password="wrong-password")
    assert resp.status_code == 401
    assert resp.get_json()["ok"] is False
    assert client.get("/api/auth").status_code == 401


def test_login_wrong_user(client, fast_login):
    resp = login(client, user="nobody")
    assert resp.status_code == 401


# ---------- 数据读写 ----------
def test_save_and_read_back(client, fast_login):
    login(client)
    payload = {
        "title": "我的导航",
        "name": "张三",
        "categories": [{
            "name": "常用",
            "icon": "🔥",
            "links": [{
                "name": "示例",
                "url": "https://example.com",
                "desc": "",
                "icon": "",
            }],
        }],
    }
    assert client.post("/api/data", json=payload).status_code == 200

    with open(server.DATA_FILE, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["title"] == "我的导航"

    data = client.get("/api/data").get_json()
    assert data["categories"][0]["links"][0]["url"] == "https://example.com"


def test_save_rejects_invalid_url(client, fast_login):
    login(client)
    payload = {"categories": [{
        "name": "常用",
        "links": [{"name": "坏链接", "url": "ftp://example.com"}],
    }]}
    resp = client.post("/api/data", json=payload)
    assert resp.status_code == 400
    assert "http(s)" in resp.get_json()["msg"]


def test_save_rejects_malformed_json(client, fast_login):
    login(client)
    resp = client.post("/api/data", data="not json", content_type="application/json")
    assert resp.status_code == 400


# ---------- 图标代理 ----------
def test_icon_rejects_unknown_host(client):
    assert client.get("/api/icon?host=evil.example").status_code == 403
    assert client.get("/api/icon").status_code == 403
