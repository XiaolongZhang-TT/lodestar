"""服务在线状态探测测试"""

import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402


class FakeResponse:
    status = 204

    def read(self, _n=-1):
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_probe_host_online(monkeypatch):
    monkeypatch.setattr(server.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    result = server.probe_host("example.com")
    assert result["ok"] is True
    assert result["code"] == 204
    assert result["ms"] >= 0
    assert result["at"] > 0


def test_probe_host_http_error_counts_as_online(monkeypatch):
    def raise_http(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://example.com/", 401, "unauthorized", {}, None)

    monkeypatch.setattr(server.urllib.request, "urlopen", raise_http)
    result = server.probe_host("example.com")
    assert result["ok"] is True       # 401 也说明服务活着
    assert result["code"] == 401


def test_probe_host_offline(monkeypatch):
    def raise_os(*_args, **_kwargs):
        raise OSError("unreachable")

    monkeypatch.setattr(server.urllib.request, "urlopen", raise_os)
    result = server.probe_host("example.com")
    assert result["ok"] is False
    assert result["code"] is None
