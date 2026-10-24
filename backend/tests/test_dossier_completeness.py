from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.routers import dossiers as dossiers_router
from app.schemas.common import DocumentType
from app.schemas.reconciliation import (
    DossierCompletenessResponse,
)
from app.services import (
    dossier_completeness as completeness_service,
)
from app.services.reconciliation import DocumentSnapshot


def make_document(
    document_type: str,
) -> DocumentSnapshot:
    return DocumentSnapshot(
        id=uuid4(),
        document_type=document_type,
        fields={},
        confidences={},
    )


def mock_documents(
    monkeypatch,
    document_types: list[str],
) -> None:
    documents = [
        make_document(document_type)
        for document_type in document_types
    ]

    monkeypatch.setattr(
        completeness_service,
        "load_dossier_documents",
        lambda **_: documents,
    )


def test_empty_dossier_is_incomplete(
    monkeypatch,
) -> None:
    mock_documents(monkeypatch, [])

    result = (
        completeness_service.get_dossier_completeness(
            session=object(),
            dossier_id=uuid4(),
        )
    )

    assert result.status == "incomplete"
    assert result.can_reconcile is False
    assert result.present_document_types == []
    assert result.missing_document_types == [
        DocumentType.CONTRACT,
        DocumentType.INVOICE,
        DocumentType.PAYMENT_REQUEST,
    ]


def test_complete_dossier_can_reconcile(
    monkeypatch,
) -> None:
    mock_documents(
        monkeypatch,
        [
            "contract",
            "invoice",
            "payment_request",
        ],
    )

    result = (
        completeness_service.get_dossier_completeness(
            session=object(),
            dossier_id=uuid4(),
        )
    )

    assert result.status == "ready"
    assert result.can_reconcile is True
    assert result.missing_document_types == []
    assert result.present_document_types == [
        DocumentType.CONTRACT,
        DocumentType.INVOICE,
        DocumentType.PAYMENT_REQUEST,
    ]


def test_duplicate_and_unknown_types_do_not_complete_dossier(
    monkeypatch,
) -> None:
    mock_documents(
        monkeypatch,
        [
            "invoice",
            "invoice",
            "unknown",
        ],
    )

    result = (
        completeness_service.get_dossier_completeness(
            session=object(),
            dossier_id=uuid4(),
        )
    )

    assert result.status == "incomplete"
    assert result.can_reconcile is False
    assert result.present_document_types == [
        DocumentType.INVOICE,
    ]
    assert result.missing_document_types == [
        DocumentType.CONTRACT,
        DocumentType.PAYMENT_REQUEST,
    ]


def test_reconcile_rejects_incomplete_dossier(
    monkeypatch,
) -> None:
    dossier_id = uuid4()

    class FakeSession:
        def get(self, model, object_id):
            return object()

    completeness = DossierCompletenessResponse(
        dossier_id=dossier_id,
        status="incomplete",
        required_document_types=[
            DocumentType.CONTRACT,
            DocumentType.INVOICE,
            DocumentType.PAYMENT_REQUEST,
        ],
        present_document_types=[
            DocumentType.CONTRACT,
            DocumentType.INVOICE,
        ],
        missing_document_types=[
            DocumentType.PAYMENT_REQUEST,
        ],
        can_reconcile=False,
    )

    monkeypatch.setattr(
        dossiers_router,
        "get_dossier_completeness",
        lambda **_: completeness,
    )

    with pytest.raises(HTTPException) as caught:
        dossiers_router.reconcile_dossier(
            dossier_id=dossier_id,
            session=FakeSession(),
        )

    assert caught.value.status_code == 409
    assert (
        caught.value.detail["code"]
        == "DOSSIER_INCOMPLETE"
    )
    assert caught.value.detail[
        "missing_document_types"
    ] == ["payment_request"]