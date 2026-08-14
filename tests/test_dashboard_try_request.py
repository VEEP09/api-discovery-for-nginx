import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import src.dashboard.app as dashboard_app
from src.dashboard.reader import OutputReader


def _write_inventory(tmp_path):
    (tmp_path / "api_inventory_20260427_000000.json").write_text(
        """[
          {
            "method": "GET",
            "endpoint": "/api/v1/users/{id}",
            "domains": ["api.example.com"],
            "call_count": 10,
            "has_auth": true
          }
        ]""",
        encoding="utf-8",
    )
    dashboard_app.init_reader(str(tmp_path))


def test_try_request_rejects_non_inventory_path(tmp_path):
    _write_inventory(tmp_path)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dashboard_app.test_request({
            "method": "GET",
            "scheme": "https",
            "domain": "api.example.com",
            "endpoint": "/api/v1/users/{id}",
            "path": "/api/v1/admin",
        }))

    assert exc.value.status_code == 400
    assert "inventory" in exc.value.detail


def test_try_request_sends_discovered_endpoint(monkeypatch, tmp_path):
    _write_inventory(tmp_path)
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            return SimpleNamespace(
                status_code=200,
                reason_phrase="OK",
                content=b'{"ok": true}',
                encoding="utf-8",
                headers={"content-type": "application/json"},
                request=SimpleNamespace(url=f"{url}?active=true"),
            )

    monkeypatch.setattr(dashboard_app.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(dashboard_app.test_request({
        "method": "GET",
        "scheme": "https",
        "domain": "api.example.com",
        "endpoint": "/api/v1/users/{id}",
        "path": "/api/v1/users/42",
        "query": {"active": "true"},
        "headers": {"Authorization": "Bearer token"},
    }))

    assert result["ok"] is True
    assert result["status_code"] == 200
    assert calls == [{
        "method": "GET",
        "url": "https://api.example.com/api/v1/users/42",
        "params": {"active": "true"},
        "headers": {"Authorization": "Bearer token"},
        "content": None,
    }]


def test_inventory_includes_successful_observed_sample(tmp_path):
    _write_inventory(tmp_path)
    db_path = tmp_path / "api_logs.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE api_logs (
                id INTEGER PRIMARY KEY,
                time TEXT,
                method TEXT,
                uri TEXT,
                normalized_uri TEXT,
                query_string TEXT,
                status INTEGER,
                host TEXT,
                http_authorization TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO api_logs
                (id, time, method, uri, normalized_uri, query_string, status, host, http_authorization)
            VALUES
                (1, '2026-04-27T09:00:00+09:00', 'GET', '/api/v1/users/42', '/api/v1/users/{id}', 'active=true', 200, 'api.example.com', 'Bearer token'),
                (2, '2026-04-27T10:00:00+09:00', 'GET', '/api/v1/users/9999', '/api/v1/users/{id}', '', 404, 'api.example.com', '-')
            """
        )

    inventory = OutputReader(str(tmp_path)).get_inventory(attach_samples=True)

    assert inventory[0]["sample_request"] == {
        "path": "/api/v1/users/42",
        "query": {"active": "true"},
        "status": 200,
        "last_seen": "2026-04-27T09:00:00+09:00",
        "has_authorization": True,
    }
