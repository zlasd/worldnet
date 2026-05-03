from fastapi.testclient import TestClient

from app.api.main import app
from app.core.config import settings


def test_api_routes_allow_requests_when_access_key_is_unset(monkeypatch):
    monkeypatch.setattr(settings, "api_access_key", None)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_api_routes_require_access_key_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "api_access_key", "secret-key")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 401


def test_api_routes_accept_header_access_key(monkeypatch):
    monkeypatch.setattr(settings, "api_access_key", "secret-key")

    with TestClient(app) as client:
        response = client.get("/health", headers={"X-API-Key": "secret-key"})

    assert response.status_code == 200


def test_api_routes_accept_query_access_key(monkeypatch):
    monkeypatch.setattr(settings, "api_access_key", "secret-key")

    with TestClient(app) as client:
        response = client.get("/health?key=secret-key")

    assert response.status_code == 200
