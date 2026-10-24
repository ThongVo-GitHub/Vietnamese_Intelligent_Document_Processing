import re
import unicodedata

from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis_result import AnalysisResultRecord
from app.models.document import Document
from app.models.extracted_field import ExtractedFieldRecord
from app.models.audit_event import AuditEvent
from app.models.document_link import DocumentLink


@dataclass(frozen=True)
class DocumentSnapshot:
    id: UUID
    document_type: str
    fields: dict[str, str | None]
    confidences: dict[str, float]

    def value(
        self,
        *field_names: str,
    ) -> str | None:
        for field_name in field_names:
            value = self.fields.get(
                field_name.strip().lower()
            )

            if value is not None and value.strip():
                return value.strip()

        return None


def load_dossier_documents(
    *,
    session: Session,
    dossier_id: UUID,
) -> list[DocumentSnapshot]:
    document_records = session.scalars(
        select(Document)
        .join(
            AnalysisResultRecord,
            Document.analysis_result_id == AnalysisResultRecord.id,
        )
        .where(
            AnalysisResultRecord.dossier_id == dossier_id
        )
        .order_by(
            AnalysisResultRecord.created_at,
            Document.document_index,
        )
    ).all()

    snapshots: list[DocumentSnapshot] = []

    for document_record in document_records:
        field_records = session.scalars(
            select(ExtractedFieldRecord)
            .where(
                ExtractedFieldRecord.document_id == document_record.id
            )
            .order_by(ExtractedFieldRecord.field_index)
        ).all()

        fields: dict[str, str | None] = {}
        confidences: dict[str, float] = {}

        for field_record in field_records:
            field_name = field_record.name.strip().lower()

            value = (
                field_record.normalized_value
                if field_record.normalized_value is not None
                else field_record.raw_value
            )

            fields.setdefault(field_name, value)
            confidences.setdefault(
                field_name,
                field_record.confidence,
            )

        snapshots.append(
            DocumentSnapshot(
                id=document_record.id,
                document_type=document_record.document_type,
                fields=fields,
                confidences=confidences,
            )
        )

    return snapshots

def normalize_identifier(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    normalized = re.sub(
        r"[^0-9A-Z]",
        "",
        value.upper(),
    )

    return normalized or None


def normalize_text(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    decomposed = unicodedata.normalize(
        "NFD",
        value.casefold().replace("đ", "d"),
    )
    without_accents = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    normalized = re.sub(
        r"[^a-z0-9]+",
        " ",
        without_accents,
    )
    normalized = " ".join(normalized.split())

    return normalized or None


def parse_decimal(
    value: str | None,
) -> Decimal | None:
    if value is None:
        return None

    compact = re.sub(r"[^\d,.\-]", "", value)

    if compact in {"", "-", ".", ","}:
        return None

    if "," in compact and "." in compact:
        if compact.rfind(",") > compact.rfind("."):
            compact = compact.replace(".", "")
            compact = compact.replace(",", ".")
        else:
            compact = compact.replace(",", "")
    elif "," in compact:
        parts = compact.split(",")

        if len(parts) > 2 or len(parts[-1]) == 3:
            compact = "".join(parts)
        else:
            compact = ".".join(parts)
    elif "." in compact:
        parts = compact.split(".")

        if len(parts) > 2 or len(parts[-1]) == 3:
            compact = "".join(parts)

    try:
        return Decimal(compact)
    except InvalidOperation:
        return None

CONTRACT_NUMBER_FIELDS = (
    "contract_number",
    "contract_no",
    "contract_reference",
    "so_hop_dong",
)

INVOICE_NUMBER_FIELDS = (
    "invoice_number",
    "invoice_no",
    "invoice_reference",
    "so_hoa_don",
)


@dataclass(frozen=True)
class LinkCandidate:
    source_document_id: UUID
    target_document_id: UUID
    relation_type: str
    confidence: float
    matched_by: str


def _has_matching_reference(
    source: DocumentSnapshot,
    target: DocumentSnapshot,
    field_names: tuple[str, ...],
) -> bool:
    source_value = normalize_identifier(
        source.value(*field_names)
    )
    target_value = normalize_identifier(
        target.value(*field_names)
    )

    return (
        source_value is not None
        and target_value is not None
        and source_value == target_value
    )


def build_link_candidates(
    documents: list[DocumentSnapshot],
) -> list[LinkCandidate]:
    contracts = [
        document
        for document in documents
        if document.document_type == "contract"
    ]
    invoices = [
        document
        for document in documents
        if document.document_type == "invoice"
    ]
    payment_requests = [
        document
        for document in documents
        if document.document_type == "payment_request"
    ]

    candidates: list[LinkCandidate] = []

    for contract in contracts:
        for invoice in invoices:
            if _has_matching_reference(
                contract,
                invoice,
                CONTRACT_NUMBER_FIELDS,
            ):
                candidates.append(
                    LinkCandidate(
                        source_document_id=contract.id,
                        target_document_id=invoice.id,
                        relation_type="contract_invoice",
                        confidence=1.0,
                        matched_by="contract_number",
                    )
                )

    for invoice in invoices:
        for payment_request in payment_requests:
            if _has_matching_reference(
                invoice,
                payment_request,
                INVOICE_NUMBER_FIELDS,
            ):
                candidates.append(
                    LinkCandidate(
                        source_document_id=invoice.id,
                        target_document_id=payment_request.id,
                        relation_type=(
                            "invoice_payment_request"
                        ),
                        confidence=1.0,
                        matched_by="invoice_number",
                    )
                )

    return candidates

def save_document_links(
    *,
    session: Session,
    dossier_id: UUID,
    candidates: list[LinkCandidate],
) -> list[DocumentLink]:
    links: list[DocumentLink] = []

    for candidate in candidates:
        existing_link = session.scalar(
            select(DocumentLink).where(
                DocumentLink.source_document_id
                == candidate.source_document_id,
                DocumentLink.target_document_id
                == candidate.target_document_id,
                DocumentLink.relation_type
                == candidate.relation_type,
            )
        )

        if existing_link is not None:
            links.append(existing_link)
            continue

        link = DocumentLink(
            dossier_id=dossier_id,
            source_document_id=(
                candidate.source_document_id
            ),
            target_document_id=(
                candidate.target_document_id
            ),
            relation_type=candidate.relation_type,
            confidence=candidate.confidence,
            matched_by=candidate.matched_by,
        )
        session.add(link)
        session.flush()

        session.add(
            AuditEvent(
                dossier_id=dossier_id,
                event_type="document_link_created",
                entity_type="document_link",
                entity_id=link.id,
                actor="system",
                details={
                    "relation_type": link.relation_type,
                    "source_document_id": str(
                        link.source_document_id
                    ),
                    "target_document_id": str(
                        link.target_document_id
                    ),
                    "matched_by": link.matched_by,
                },
            )
        )

        links.append(link)

    session.flush()
    return links


def create_dossier_links(
    *,
    session: Session,
    dossier_id: UUID,
) -> list[DocumentLink]:
    documents = load_dossier_documents(
        session=session,
        dossier_id=dossier_id,
    )
    candidates = build_link_candidates(documents)

    return save_document_links(
        session=session,
        dossier_id=dossier_id,
        candidates=candidates,
    )