"""Production does not register schema or documentation routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


_ENV_NAMES = ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV")
_DOC_PATHS = (
    "/openapi.json",
    "/openapi.json/",
    "/docs",
    "/docs/",
    "/docs/oauth2-redirect",
    "/redoc",
    "/redoc/",
)


@pytest.fixture
def create_application(monkeypatch):
    # Import the service in test mode before exercising production settings.
    # TestClient is used without entering the service lifespan: these checks
    # must neither initialize databases nor schedule background workers.
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VAULTAI_ENV", "test")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://docs_test@127.0.0.1:1/docs_test?connect_timeout=1",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "docs-test-unused-api-key")
    monkeypatch.setenv("CORS_ALLOWED_ORIGIN_REGEX", r"^https://app\.svaultai\.com$")
    from main import _create_application

    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return _create_application


@pytest.mark.parametrize("env_name", _ENV_NAMES)
@pytest.mark.parametrize("token", ("prod", "production", "live"))
def test_production_docs_routes_are_absent(
    monkeypatch, create_application, env_name, token,
):
    monkeypatch.setenv(env_name, token)
    app = create_application()

    @app.get("/health")
    def health():
        return {"ok": True}

    client = TestClient(app)
    for path in _DOC_PATHS:
        response = client.get(path + "?probe=docs", follow_redirects=False)
        assert response.status_code == 404, path
    assert client.get("/health").json() == {"ok": True}
    assert app.openapi_url is None
    assert app.docs_url is None
    assert app.redoc_url is None


@pytest.mark.parametrize("token", (None, "dev", "development", "local", "test", "ci"))
def test_development_docs_remain_available(
    monkeypatch, create_application, token,
):
    if token is not None:
        monkeypatch.setenv("VAULTAI_ENV", token)
    app = create_application()
    client = TestClient(app)
    assert client.get("/openapi.json").json()["info"]["title"] == "VaultAI Backend"
    assert client.get("/docs").status_code == 200
    assert client.get("/docs/oauth2-redirect").status_code == 200
    assert client.get("/redoc").status_code == 200
