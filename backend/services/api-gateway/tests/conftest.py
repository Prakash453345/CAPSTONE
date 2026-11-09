import os

# The module-level `app` in api_gateway.main is built when it is imported, so
# sign-in must be off before any test module imports it. Tests that care about
# sign-in build their own app with `Settings(require_sign_in=True)`.
os.environ.setdefault("API_REQUIRE_SIGN_IN", "false")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_reset_allowance():
    """The per-account reset-code allowance is process-wide; every test starts
    with a full one so the order tests run in can't matter."""
    from api_gateway.services import auth

    auth._reset_sends.clear()
    yield
    auth._reset_sends.clear()
