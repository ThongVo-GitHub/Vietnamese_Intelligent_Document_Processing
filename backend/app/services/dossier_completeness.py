from uuid import UUID

from sqlalchemy.orm import Session

from app.schemas.common import DocumentType
from app.schemas.reconciliation import (
    DossierCompletenessResponse,
)
from app.services.reconciliation import (
    load_dossier_documents,
)


REQUIRED_DOCUMENT_TYPES = (
    DocumentType.CONTRACT,
    DocumentType.INVOICE,
    DocumentType.PAYMENT_REQUEST,
)


def get_dossier_completeness(
    *,
    session: Session,
    dossier_id: UUID,
) -> DossierCompletenessResponse:
    documents = load_dossier_documents(
        session=session,
        dossier_id=dossier_id,
    )

    existing_types = {
        document.document_type
        for document in documents
    }

    present_types = [
        document_type
        for document_type in REQUIRED_DOCUMENT_TYPES
        if document_type.value in existing_types
    ]

    missing_types = [
        document_type
        for document_type in REQUIRED_DOCUMENT_TYPES
        if document_type.value not in existing_types
    ]

    can_reconcile = not missing_types

    return DossierCompletenessResponse(
        dossier_id=dossier_id,
        status=(
            "ready"
            if can_reconcile
            else "incomplete"
        ),
        required_document_types=list(
            REQUIRED_DOCUMENT_TYPES
        ),
        present_document_types=present_types,
        missing_document_types=missing_types,
        can_reconcile=can_reconcile,
    )