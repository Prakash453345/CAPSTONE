"""The layering, enforced: routes map URLs to controllers and nothing else.

A new endpoint written as a decorated function in a routes module, or a
state-changing review endpoint registered without the API key, fails here.
"""

from __future__ import annotations

import pytest
from api_gateway.core.config import Settings
from api_gateway.core.security import require_api_key
from api_gateway.main import create_app
from fastapi.routing import APIRoute, APIWebSocketRoute, iter_route_contexts

EXPECTED = {
    ("GET", "/health"),
    ("POST", "/v1/commands"),
    ("WS", "/v1/stream"),
    ("GET", "/v1/incidents"),
    ("GET", "/v1/incidents/{incident_id}"),
    ("POST", "/v1/incidents/{incident_id}/confirm"),
    ("POST", "/v1/incidents/{incident_id}/reject"),
    ("POST", "/v1/clips"),
    ("GET", "/v1/clips"),
    ("GET", "/v1/clips/{clip_id}"),
    ("GET", "/v1/clips/{clip_id}/video"),
    ("GET", "/v1/clips/{clip_id}/snapshot"),
    ("POST", "/v1/clips/{clip_id}/confirm"),
    ("POST", "/v1/clips/{clip_id}/reject"),
}


@pytest.fixture(scope="module")
def routes(tmp_path_factory):
    """Every API route with its full path, flattened through included routers
    (FastAPI keeps them nested), leaving out the built-in docs pages."""
    app = create_app(Settings(api_key="k", clips_dir=tmp_path_factory.mktemp("clips")))
    found = [c for c in iter_route_contexts(app.routes)
             if isinstance(c.route, (APIRoute, APIWebSocketRoute))]
    assert found, "no API routes found -- the walk over the app's routers is broken"
    return found


# The route context carries path and endpoint for HTTP routes only; for a
# WebSocket they are on the effective route itself.
def _path(ctx) -> str:
    return ctx.path or ctx.route.path


def _endpoint(ctx):
    return ctx.endpoint or ctx.route.endpoint


def _key(ctx) -> set[tuple[str, str]]:
    if isinstance(ctx.route, APIWebSocketRoute):
        return {("WS", _path(ctx))}
    return {(m, _path(ctx)) for m in ctx.methods}


def test_the_route_table_is_exactly_the_documented_api(routes):
    assert set().union(*(_key(c) for c in routes)) == EXPECTED


def test_every_endpoint_is_a_controller_function(routes):
    for c in routes:
        fn = _endpoint(c)
        assert fn.__module__.startswith("api_gateway.controllers."), (
            f"{_path(c)} is handled by {fn.__module__}.{fn.__name__}; "
            "request handling belongs in controllers/, routes/ only maps URLs")


def test_every_review_endpoint_requires_the_api_key(routes):
    review = [c for c in routes if _path(c).endswith(("/confirm", "/reject"))]
    assert len(review) == 4
    for c in review:
        assert any(d.dependency is require_api_key for d in c.dependencies), c.path
