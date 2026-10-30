import os

# The module-level `app` in api_gateway.main is built when it is imported, so
# sign-in must be off before any test module imports it. Tests that care about
# sign-in build their own app with `Settings(require_sign_in=True)`.
os.environ.setdefault("API_REQUIRE_SIGN_IN", "false")
