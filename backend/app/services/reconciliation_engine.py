from collections import Counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.audit_event import AuditEvent
from app.models.document_link import DocumentLink
from app.services.reconciliation import (
    DocumentSnapshot,
    create_dossier_links,
    load_dossier_documents,
)
from app.services.reconciliation_rules import (
    AlertCandidate,
    compare_document_pair,
    find_missing_document_types,
    find_missing_required_fields,
    validate_document_values,
)


def _build_relation_pairs(
    documents: list[DocumentSnapshot],
    links: list[DocumentLink],
) -> list[
    tuple[DocumentSnapshot, DocumentSnapshot, str]
]:
    document_by_id = {
        document.id: document
        for document in documents
    }
    pairs: list[
        tuple[DocumentSnapshot, DocumentSnapshot, str]
    ] = []
    seen: set[tuple[UUID, UUID, str]] = set()

    for link in links:
        source = document_by_id.get(
            link.source_document_id
        )
        target = document_by_id.get(
            link.target_document_id
        )

        if source is None or target is None:
            continue

        key = (
            source.id,
            target.id,
            link.relation_type,
        )
        seen.add(key)
        pairs.append(
            (source, target, link.relation_type)
        )

    fallback_relations = (
        (
            "contract",
            "invoice",
            "contract_invoice",
        ),
        (
            "invoice",
            "payment_request",
            "invoice_payment_request",
        ),
    )

    for (
        source_type,
        target_type,
        relation_type,
    ) in fallback_relations:
        if any(
            pair_relation == relation_type
            for _, _, pair_relation in pairs
        ):
            continue

        sources = [
            document
            for document in documents
            if document.document_type == source_type
        ]
        targets = [
            document
            for document in documents
            if document.document_type == target_type
        ]

        if len(sources) != 1 or len(targets) != 1:
            continue

        source = sources[0]
        target = targets[0]
        key = (
            source.id,
            target.id,
            relation_type,
        )

        if key not in seen:
            pairs.append(
                (source, target, relation_type)
            )
            seen.add(key)

    return pairs


def generate_reconciliation_alerts(
    *,
    session: Session,
    dossier_id: UUID,
) -> list[AlertCandidate]:
    documents = load_dossier_documents(
        session=session,
        dossier_id=dossier_id,
    )
    links = create_dossier_links(
        session=session,
        dossier_id=dossier_id,
    )

    candidates = [
        *find_missing_document_types(documents),
        *find_missing_required_fields(documents),
        *validate_document_values(documents),
    ]

    for source, target, relation_type in (
        _build_relation_pairs(documents, links)
    ):
        candidates.extend(
            compare_document_pair(
                source,
                target,
                relation_type,
            )
        )

    return candidates


def replace_open_reconciliation_alerts(
    *,
    session: Session,
    dossier_id: UUID,
    candidates: list[AlertCandidate],
) -> list[Alert]:
    existing_alerts = session.scalars(
        select(Alert).where(
            Alert.dossier_id == dossier_id,
            Alert.status == "open",
        )
    ).all()

    for existing_alert in existing_alerts:
        if (
            existing_alert.details.get("generated_by")
            == "reconciliation_engine"
        ):
            session.delete(existing_alert)

    session.flush()

    alerts: list[Alert] = []

    for candidate in candidates:
        details = {
            **candidate.details,
            "generated_by": "reconciliation_engine",
        }
        alert = Alert(
            dossier_id=dossier_id,
            rule_code=candidate.rule_code,
            severity=candidate.severity,
            status="open",
            message=candidate.message,
            source_document_id=(
                candidate.source_document_id
            ),
            target_document_id=(
                candidate.target_document_id
            ),
            field_name=candidate.field_name,
            expected_value=candidate.expected_value,
            actual_value=candidate.actual_value,
            details=details,
        )
        session.add(alert)
        alerts.append(alert)

    session.flush()

    rule_counts = Counter(
        alert.rule_code
        for alert in alerts
    )
    session.add(
        AuditEvent(
            dossier_id=dossier_id,
            event_type="reconciliation_completed",
            entity_type="dossier",
            entity_id=dossier_id,
            actor="system",
            details={
                "alert_count": len(alerts),
                "rule_counts": dict(rule_counts),
            },
        )
    )

    session.flush()
    return alerts


def run_reconciliation(
    *,
    session: Session,
    dossier_id: UUID,
) -> list[Alert]:
    candidates = generate_reconciliation_alerts(
        session=session,
        dossier_id=dossier_id,
    )

    return replace_open_reconciliation_alerts(
        session=session,
        dossier_id=dossier_id,
        candidates=candidates,
    )