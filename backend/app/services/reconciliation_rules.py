from dataclasses import dataclass, field
from typing import Any
from uuid import UUID
from collections.abc import Callable
from decimal import Decimal

from app.services.reconciliation import (
    CONTRACT_NUMBER_FIELDS,
    INVOICE_NUMBER_FIELDS,
    DocumentSnapshot,
    normalize_identifier,
    parse_decimal,
)


TAX_ID_FIELDS = (
    "tax_id",
    "tax_code",
    "mst",
    "ma_so_thue",
)

TOTAL_AMOUNT_FIELDS = (
    "total_amount",
    "grand_total",
    "amount",
    "tong_tien",
)

PAYMENT_AMOUNT_FIELDS = (
    "payment_amount",
    "requested_amount",
    "total_amount",
    "amount",
    "so_tien_thanh_toan",
)

CURRENCY_FIELDS = (
    "currency",
    "currency_code",
    "don_vi_tien_te",
)

SUBTOTAL_FIELDS = (
    "subtotal",
    "net_amount",
    "amount_before_tax",
    "tien_truoc_thue",
)

VAT_AMOUNT_FIELDS = (
    "vat_amount",
    "tax_amount",
    "thue_gtgt",
)

VAT_RATE_FIELDS = (
    "vat_rate",
    "tax_rate",
    "thue_suat",
)

AMOUNT_IN_WORDS_FIELDS = (
    "amount_in_words",
    "total_amount_in_words",
    "so_tien_bang_chu",
)

EXPECTED_DOCUMENT_TYPES = (
    "contract",
    "invoice",
    "payment_request",
)

AMOUNT_TOLERANCE = Decimal("0.01")

REQUIRED_FIELDS = {
    "contract": (
        ("contract_number", CONTRACT_NUMBER_FIELDS),
        ("tax_id", TAX_ID_FIELDS),
        ("total_amount", TOTAL_AMOUNT_FIELDS),
    ),
    "invoice": (
        ("invoice_number", INVOICE_NUMBER_FIELDS),
        ("contract_number", CONTRACT_NUMBER_FIELDS),
        ("tax_id", TAX_ID_FIELDS),
        ("total_amount", TOTAL_AMOUNT_FIELDS),
    ),
    "payment_request": (
        ("invoice_number", INVOICE_NUMBER_FIELDS),
        ("payment_amount", PAYMENT_AMOUNT_FIELDS),
    ),
}


@dataclass(frozen=True)
class AlertCandidate:
    rule_code: str
    severity: str
    message: str
    source_document_id: UUID | None = None
    target_document_id: UUID | None = None
    field_name: str | None = None
    expected_value: str | None = None
    actual_value: str | None = None
    details: dict[str, Any] = field(
        default_factory=dict
    )


def find_missing_required_fields(
    documents: list[DocumentSnapshot],
) -> list[AlertCandidate]:
    alerts: list[AlertCandidate] = []

    for document in documents:
        required_fields = REQUIRED_FIELDS.get(
            document.document_type,
            (),
        )

        for canonical_name, aliases in required_fields:
            if document.value(*aliases) is not None:
                continue

            alerts.append(
                AlertCandidate(
                    rule_code="MISSING_REQUIRED_FIELD",
                    severity="warning",
                    message=(
                        "Missing required field "
                        f"'{canonical_name}'"
                    ),
                    source_document_id=document.id,
                    field_name=canonical_name,
                    details={
                        "document_type": (
                            document.document_type
                        ),
                        "accepted_aliases": list(aliases),
                    },
                )
            )

    return alerts

def _comparison_alert(
    *,
    source: DocumentSnapshot,
    target: DocumentSnapshot,
    source_fields: tuple[str, ...],
    target_fields: tuple[str, ...],
    normalizer: Callable[[str | None], object | None],
    rule_code: str,
    field_name: str,
    relation_type: str,
    severity: str = "error",
) -> AlertCandidate | None:
    expected = source.value(*source_fields)
    actual = target.value(*target_fields)

    normalized_expected = normalizer(expected)
    normalized_actual = normalizer(actual)

    if normalized_expected is None or normalized_actual is None:
        return None

    if normalized_expected == normalized_actual:
        return None

    return AlertCandidate(
        rule_code=rule_code,
        severity=severity,
        message=f"{field_name} does not match between documents",
        source_document_id=source.id,
        target_document_id=target.id,
        field_name=field_name,
        expected_value=expected,
        actual_value=actual,
        details={"relation_type": relation_type},
    )


def compare_document_pair(
    source: DocumentSnapshot,
    target: DocumentSnapshot,
    relation_type: str,
) -> list[AlertCandidate]:
    alerts: list[AlertCandidate] = []

    if relation_type == "contract_invoice":
        checks = (
            (
                CONTRACT_NUMBER_FIELDS,
                CONTRACT_NUMBER_FIELDS,
                normalize_identifier,
                "CONTRACT_NUMBER_MISMATCH",
                "contract_number",
                "error",
            ),
            (
                TAX_ID_FIELDS,
                TAX_ID_FIELDS,
                normalize_identifier,
                "TAX_ID_MISMATCH",
                "tax_id",
                "error",
            ),
            (
                TOTAL_AMOUNT_FIELDS,
                TOTAL_AMOUNT_FIELDS,
                parse_decimal,
                "TOTAL_AMOUNT_MISMATCH",
                "total_amount",
                "error",
            ),
            (
                CURRENCY_FIELDS,
                CURRENCY_FIELDS,
                normalize_identifier,
                "CURRENCY_MISMATCH",
                "currency",
                "warning",
            ),
        )
    elif relation_type == "invoice_payment_request":
        checks = (
            (
                INVOICE_NUMBER_FIELDS,
                INVOICE_NUMBER_FIELDS,
                normalize_identifier,
                "INVOICE_NUMBER_MISMATCH",
                "invoice_number",
                "error",
            ),
            (
                TAX_ID_FIELDS,
                TAX_ID_FIELDS,
                normalize_identifier,
                "TAX_ID_MISMATCH",
                "tax_id",
                "error",
            ),
            (
                TOTAL_AMOUNT_FIELDS,
                PAYMENT_AMOUNT_FIELDS,
                parse_decimal,
                "PAYMENT_AMOUNT_MISMATCH",
                "payment_amount",
                "error",
            ),
            (
                CURRENCY_FIELDS,
                CURRENCY_FIELDS,
                normalize_identifier,
                "CURRENCY_MISMATCH",
                "currency",
                "warning",
            ),
        )
    else:
        return alerts

    for (
        source_fields,
        target_fields,
        normalizer,
        rule_code,
        field_name,
        severity,
    ) in checks:
        alert = _comparison_alert(
            source=source,
            target=target,
            source_fields=source_fields,
            target_fields=target_fields,
            normalizer=normalizer,
            rule_code=rule_code,
            field_name=field_name,
            relation_type=relation_type,
            severity=severity,
        )

        if alert is not None:
            alerts.append(alert)

    return alerts

def find_missing_document_types(
    documents: list[DocumentSnapshot],
) -> list[AlertCandidate]:
    existing_types = {
        document.document_type
        for document in documents
    }

    return [
        AlertCandidate(
            rule_code="MISSING_DOCUMENT_TYPE",
            severity="warning",
            message=f"Missing document type '{document_type}'",
            details={"document_type": document_type},
        )
        for document_type in EXPECTED_DOCUMENT_TYPES
        if document_type not in existing_types
    ]


def _amount_fields_for(
    document: DocumentSnapshot,
) -> tuple[str, ...]:
    if document.document_type == "payment_request":
        return PAYMENT_AMOUNT_FIELDS

    return TOTAL_AMOUNT_FIELDS


def validate_document_values(
    documents: list[DocumentSnapshot],
) -> list[AlertCandidate]:
    alerts: list[AlertCandidate] = []

    for document in documents:
        total_text = document.value(
            *_amount_fields_for(document)
        )
        total = parse_decimal(total_text)

        if document.document_type == "invoice":
            subtotal_text = document.value(*SUBTOTAL_FIELDS)
            vat_text = document.value(*VAT_AMOUNT_FIELDS)
            vat_rate_text = document.value(*VAT_RATE_FIELDS)

            subtotal = parse_decimal(subtotal_text)
            vat_amount = parse_decimal(vat_text)
            vat_rate = parse_decimal(vat_rate_text)

            if (
                subtotal is not None
                and vat_amount is not None
                and total is not None
            ):
                calculated_total = subtotal + vat_amount

                if (
                    abs(calculated_total - total)
                    > AMOUNT_TOLERANCE
                ):
                    alerts.append(
                        AlertCandidate(
                            rule_code=(
                                "INVOICE_TOTAL_MISMATCH"
                            ),
                            severity="error",
                            message=(
                                "Invoice subtotal plus VAT "
                                "does not equal total"
                            ),
                            source_document_id=document.id,
                            field_name="total_amount",
                            expected_value=str(calculated_total),
                            actual_value=total_text,
                            details={
                                "subtotal": subtotal_text,
                                "vat_amount": vat_text,
                            },
                        )
                    )

            if (
                subtotal is not None
                and vat_rate is not None
                and vat_amount is not None
            ):
                calculated_vat = (
                    subtotal * vat_rate / Decimal("100")
                )

                if (
                    abs(calculated_vat - vat_amount)
                    > AMOUNT_TOLERANCE
                ):
                    alerts.append(
                        AlertCandidate(
                            rule_code="VAT_AMOUNT_MISMATCH",
                            severity="error",
                            message=(
                                "VAT amount does not match "
                                "subtotal and VAT rate"
                            ),
                            source_document_id=document.id,
                            field_name="vat_amount",
                            expected_value=str(calculated_vat),
                            actual_value=vat_text,
                            details={
                                "subtotal": subtotal_text,
                                "vat_rate": vat_rate_text,
                            },
                        )
                    )

        amount_words_text = document.value(
            *AMOUNT_IN_WORDS_FIELDS
        )

        if amount_words_text is None or total is None:
            continue

        amount_from_words = parse_decimal(amount_words_text)

        if amount_from_words is None:
            alerts.append(
                AlertCandidate(
                    rule_code=(
                        "AMOUNT_IN_WORDS_UNVERIFIABLE"
                    ),
                    severity="warning",
                    message=(
                        "Amount in words has no normalized "
                        "numeric value"
                    ),
                    source_document_id=document.id,
                    field_name="amount_in_words",
                    actual_value=amount_words_text,
                )
            )
        elif (
            abs(amount_from_words - total)
            > AMOUNT_TOLERANCE
        ):
            alerts.append(
                AlertCandidate(
                    rule_code="AMOUNT_IN_WORDS_MISMATCH",
                    severity="error",
                    message=(
                        "Amount in words does not match "
                        "numeric total"
                    ),
                    source_document_id=document.id,
                    field_name="amount_in_words",
                    expected_value=total_text,
                    actual_value=amount_words_text,
                )
            )

    return alerts