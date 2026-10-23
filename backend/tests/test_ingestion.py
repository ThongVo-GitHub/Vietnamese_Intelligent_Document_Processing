from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db_session
from app.main import app
from app.models.base import Base


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, Path]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    testing_session_local = sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db_session() -> Iterator[Session]:
        with testing_session_local() as session:
            yield session

    upload_dir = tmp_path / "uploads"

    monkeypatch.setattr(
        "app.routers.dossiers.get_settings",
        lambda: SimpleNamespace(
            upload_dir=upload_dir,
            max_upload_size_bytes=1024,
        ),
    )
    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        with TestClient(app) as test_client:
            yield test_client, upload_dir
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_upload_file_creates_job_and_stores_file(
    client: tuple[TestClient, Path],
) -> None:
    test_client, upload_dir = client
    content = b"%PDF-1.7 test"

    dossier_response = test_client.post(
        "/dossiers",
        json={"name": "Test dossier"},
    )
    assert dossier_response.status_code == 201

    dossier_id = dossier_response.json()["id"]
    upload_response = test_client.post(
        f"/dossiers/{dossier_id}/files",
        files={
            "file": (
                "sample.pdf",
                content,
                "application/pdf",
            ),
        },
    )

    assert upload_response.status_code == 201

    body = upload_response.json()
    assert body["dossier_id"] == dossier_id
    assert body["original_name"] == "sample.pdf"
    assert body["media_type"] == "application/pdf"
    assert body["size_bytes"] == len(content)
    assert body["job_status"] == "queued"
    assert len(body["sha256"]) == 64

    stored_files = list(upload_dir.rglob("*.pdf"))
    assert len(stored_files) == 1
    assert stored_files[0].read_bytes() == content

    job_response = test_client.get(f"/jobs/{body['job_id']}")

    assert job_response.status_code == 200
    assert job_response.json()["status"] == "queued"
    assert job_response.json()["progress"] == 0
    result_response = test_client.get(
        f"/jobs/{body['job_id']}/result"
    )

    assert result_response.status_code == 404
    assert result_response.json() == {
        "detail": (
            "Analysis result not found for the specified job"
        )
    }


def test_upload_rejects_unsupported_file(
    client: tuple[TestClient, Path],
) -> None:
    test_client, upload_dir = client

    dossier_response = test_client.post(
        "/dossiers",
        json={"name": "Invalid file test"},
    )
    dossier_id = dossier_response.json()["id"]

    response = test_client.post(
        f"/dossiers/{dossier_id}/files",
        files={
            "file": (
                "malware.exe",
                b"not a supported document",
                "application/octet-stream",
            ),
        },
    )

    assert response.status_code == 415
    assert response.json() == {
        "detail": "Unsupported or invalid file",
    }
    assert not list(upload_dir.rglob("*"))


def test_upload_rejects_oversized_file(
    client: tuple[TestClient, Path],
) -> None:
    test_client, upload_dir = client

    dossier_response = test_client.post(
        "/dossiers",
        json={"name": "Large file test"},
    )
    dossier_id = dossier_response.json()["id"]

    response = test_client.post(
        f"/dossiers/{dossier_id}/files",
        files={
            "file": (
                "large.pdf",
                b"%PDF-" + b"x" * 1024,
                "application/pdf",
            ),
        },
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": "File exceeds the 10 MB limit",
    }
    assert not list(upload_dir.rglob("*"))


def test_upload_to_missing_dossier_returns_404(
    client: tuple[TestClient, Path],
) -> None:
    test_client, _ = client

    response = test_client.post(
        f"/dossiers/{uuid4()}/files",
        files={
            "file": (
                "sample.pdf",
                b"%PDF-1.7 test",
                "application/pdf",
            ),
        },
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Dossier not found",
    }


def test_get_missing_job_returns_404(
    client: tuple[TestClient, Path],
) -> None:
    test_client, _ = client

    response = test_client.get(f"/jobs/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Processing job not found",
    }
