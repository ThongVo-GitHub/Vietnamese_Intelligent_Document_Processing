from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from app.main import app
client = TestClient(app)
def test_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to DocFlow VN API"}

def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "backend",
        "environment": "development",
    }

def test_readiness_when_database_is_unavailable(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.main.database_is_ready",
        lambda: False,
    )

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "service": "backend",
        "database": "unavailable",
    }

def test_readiness_when_database_is_available(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.main.database_is_ready",
        lambda: True,
    )

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "backend",
        "database": "connected",
    }