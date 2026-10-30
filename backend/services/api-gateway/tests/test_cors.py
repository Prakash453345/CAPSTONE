"""Browser access to the API: only the console's own origins, never "*"."""

from __future__ import annotations

from api_gateway.core.config import Settings
from api_gateway.main import create_app
from fastapi.testclient import TestClient


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/v1/commands",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_a_foreign_website_cannot_call_the_api(tmp_path):
    client = TestClient(create_app(Settings(api_key="k", clips_dir=tmp_path)))
    r = _preflight(client, "https://attacker.example")
    assert "access-control-allow-origin" not in r.headers


def test_the_console_dev_server_can(tmp_path):
    client = TestClient(create_app(Settings(api_key="k", clips_dir=tmp_path)))
    r = _preflight(client, "http://localhost:5173")
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_origins_env_overrides_and_blank_keeps_the_default(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://console.example, https://ops.example")
    assert Settings.from_env().cors_origins == ("https://console.example", "https://ops.example")
    monkeypatch.setenv("CORS_ORIGINS", " ")
    assert "http://localhost:5173" in Settings.from_env().cors_origins
