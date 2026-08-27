import warnings
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from starlette.websockets import WebSocketDisconnect

from app.api import routes


class JournalStorage:
    async def list_payloads(self, table: str, limit: int = 100) -> list[dict[str, object]]:
        assert table == "logs"
        return [
            {
                "message": "AI signal confidence updated",
                "payload": {"confidence": 0.91},
                "level": "INFO",
                "created_at": "2026-08-27T02:00:00+00:00",
            },
            {
                "message": "Portfolio risk limit reached for order",
                "payload": {},
                "level": "WARNING",
                "created_at": "2026-08-27T01:00:00+00:00",
            },
        ]


@pytest.fixture
def api_app() -> FastAPI:
    app = FastAPI()
    app.include_router(routes.auth_router)
    app.include_router(routes.router)
    return app


@pytest.mark.asyncio
async def test_production_api_requires_valid_bearer_token(monkeypatch, api_app: FastAPI) -> None:
    monkeypatch.setattr(
        routes,
        "state",
        SimpleNamespace(
            settings=SimpleNamespace(app_env="production", api_auth_token="operator-secret"),
            storage=JournalStorage(),
        ),
    )
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/api/journal")
        wrong = await client.get(
            "/api/journal", headers={"Authorization": "Bearer wrong-secret"}
        )
        accepted = await client.get(
            "/api/journal", headers={"Authorization": "Bearer operator-secret"}
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert accepted.status_code == 200


@pytest.mark.asyncio
async def test_journal_prioritizes_ai_and_risk_categories(monkeypatch, api_app: FastAPI) -> None:
    monkeypatch.setattr(
        routes,
        "state",
        SimpleNamespace(
            settings=SimpleNamespace(app_env="local", api_auth_token=""),
            storage=JournalStorage(),
        ),
    )
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ai_response = await client.get("/api/journal", params={"category": "AI"})
        risk_response = await client.get("/api/journal", params={"category": "RISK"})

    assert [item["category"] for item in ai_response.json()["items"]] == ["AI"]
    assert [item["category"] for item in risk_response.json()["items"]] == ["RISK"]
    assert ai_response.json()["items"][0]["details"] == '{"confidence": 0.91}'


def test_websocket_requires_token_and_accepts_valid_bearer(monkeypatch, api_app: FastAPI) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient

    class Realtime:
        async def subscribe(self, channel: str):
            import asyncio

            queue = asyncio.Queue()
            await queue.put({"channel": channel, "data": {"ok": True}})
            return queue

        async def unsubscribe(self, channel: str, queue) -> None:
            return None

    monkeypatch.setattr(
        routes,
        "state",
        SimpleNamespace(
            settings=SimpleNamespace(app_env="production", api_auth_token="operator-secret"),
            realtime=Realtime(),
        ),
    )
    client = TestClient(api_app)

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/ws/status"):
        pass

    with client.websocket_connect(
        "/api/ws/status", headers={"Authorization": "Bearer operator-secret"}
    ) as websocket:
        assert websocket.receive_json() == {
            "channel": "status",
            "data": {"ok": True},
        }


@pytest.mark.asyncio
async def test_login_issues_httponly_cookie_that_authenticates_api(
    monkeypatch, api_app: FastAPI
) -> None:
    monkeypatch.setattr(
        routes,
        "state",
        SimpleNamespace(
            settings=SimpleNamespace(
                app_env="production",
                api_auth_token="signing-secret",
                operator_password="memorable-password",
                auth_session_ttl_seconds=3600,
            ),
            storage=JournalStorage(),
        ),
    )
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
        rejected = await client.post("/api/auth/login", json={"password": "wrong"})
        accepted = await client.post(
            "/api/auth/login", json={"password": "memorable-password"}
        )
        journal = await client.get("/api/journal")

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    cookie = accepted.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie
    assert journal.status_code == 200


@pytest.mark.asyncio
async def test_device_session_rotates_and_revokes_refresh_token(
    monkeypatch, api_app: FastAPI
) -> None:
    class DeviceStorage:
        def __init__(self) -> None:
            self.active: set[str] = set()

        async def create_device_session(self, *, token_hash, device_name, expires_at) -> None:
            assert device_name == "iPhone kiểm thử"
            self.active.add(token_hash)

        async def rotate_device_session(
            self, *, old_token_hash, new_token_hash, expires_at
        ) -> bool:
            if old_token_hash not in self.active:
                return False
            self.active.remove(old_token_hash)
            self.active.add(new_token_hash)
            return True

        async def revoke_device_session(self, token_hash: str) -> None:
            self.active.discard(token_hash)

    storage = DeviceStorage()
    monkeypatch.setattr(
        routes,
        "state",
        SimpleNamespace(
            settings=SimpleNamespace(
                app_env="production",
                api_auth_token="signing-secret",
                operator_password="memorable-password",
                auth_session_ttl_seconds=3600,
                auth_device_ttl_seconds=2_592_000,
            ),
            storage=storage,
        ),
    )
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
        logged_in = await client.post(
            "/api/auth/device-login",
            json={"password": "memorable-password", "device_name": "iPhone kiểm thử"},
        )
        first = logged_in.json()["refresh_token"]
        refreshed = await client.post("/api/auth/refresh", json={"refresh_token": first})
        second = refreshed.json()["refresh_token"]
        replayed = await client.post("/api/auth/refresh", json={"refresh_token": first})
        logged_out = await client.post(
            "/api/auth/device-logout", json={"refresh_token": second}
        )
        after_logout = await client.post(
            "/api/auth/refresh", json={"refresh_token": second}
        )

    assert logged_in.status_code == 200
    assert refreshed.status_code == 200
    assert first != second
    assert replayed.status_code == 401
    assert logged_out.status_code == 200
    assert after_logout.status_code == 401


def test_websocket_accepts_authenticated_cookie(monkeypatch, api_app: FastAPI) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient

    class Realtime:
        async def subscribe(self, channel: str):
            import asyncio

            queue = asyncio.Queue()
            await queue.put({"channel": channel, "data": {"ok": True}})
            return queue

        async def unsubscribe(self, channel: str, queue) -> None:
            return None

    monkeypatch.setattr(
        routes,
        "state",
        SimpleNamespace(
            settings=SimpleNamespace(
                app_env="local",
                api_auth_token="signing-secret",
                operator_password="memorable-password",
                auth_session_ttl_seconds=3600,
            ),
            realtime=Realtime(),
        ),
    )
    client = TestClient(api_app)
    assert client.post(
        "/api/auth/login", json={"password": "memorable-password"}
    ).status_code == 200
    with client.websocket_connect("/api/ws/status") as websocket:
        assert websocket.receive_json()["data"] == {"ok": True}
