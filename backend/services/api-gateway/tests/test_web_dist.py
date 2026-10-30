"""With WEB_DIST set the gateway serves the built site and `/api` on one address."""

from __future__ import annotations

from api_gateway.core.config import Settings
from api_gateway.main import SECURITY_HEADERS, create_app
from fastapi.testclient import TestClient


def _client(tmp_path):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html>app</html>")
    (web / "assets" / "app-abc123.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("not for the web")
    settings = Settings(clips_dir=tmp_path, require_sign_in=False, web_dist=str(web))
    return TestClient(create_app(settings))


def test_the_built_site_is_served_with_security_headers(tmp_path):
    client = _client(tmp_path)
    page = client.get("/console/anything")  # an app route falls back to index.html
    assert page.status_code == 200 and "app" in page.text
    assert page.headers["cache-control"] == "no-cache"
    for name, value in SECURITY_HEADERS.items():
        assert page.headers[name] == value
    asset = client.get("/assets/app-abc123.js")
    assert "immutable" in asset.headers["cache-control"]


def test_api_calls_work_under_the_api_prefix(tmp_path):
    client = _client(tmp_path)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.headers["x-frame-options"] == "DENY"


def test_a_path_outside_the_site_is_not_served(tmp_path):
    client = _client(tmp_path)
    res = client.get("/..%2Fsecret.txt")
    assert "not for the web" not in res.text
