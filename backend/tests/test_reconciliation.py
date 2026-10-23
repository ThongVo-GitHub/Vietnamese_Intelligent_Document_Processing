from uuid import uuid4

from app.services.reconciliation import DocumentSnapshot
from app.services.reconciliation_engine import (
    _build_relation_pairs,
)
from app.services.reconciliation_rules import (
    compare_document_pair,
    find_missing_required_fields,
    validate_document_values,
)


def make_document(
    document_type: str,
    fields: dict[str, str],
) -> DocumentSnapshot:
    return DocumentSnapshot(
        id=uuid4(),
        document_type=document_type,
        fields=fields,
        confidences={
            name: 1.0
            for name in fields
        },
    )


def test_missing_invoice_fields_are_reported() -> None:
    invoice = make_document(
        "invoice",
        {},
    )

    alerts = find_missing_required_fields(
        [invoice]
    )

    assert {
        alert.field_name
        for alert in alerts
    } == {
        "invoice_number",
        "contract_number",
        "tax_id",
        "total_amount",
    }


def test_contract_invoice_mismatches_are_reported() -> None:
    contract = make_document(
        "contract",
        {
            "contract_number": "HD-01",
            "tax_id": "0312345678",
            "total_amount": "1.000.000",
            "currency": "VND",
        },
    )
    invoice = make_document(
        "invoice",
        {
            "contract_number": "HD-02",
            "tax_id": "9999999999",
            "total_amount": "1.200.000",
            "currency": "USD",
        },
    )

    alerts = compare_document_pair(
        contract,
        invoice,
        "contract_invoice",
    )

    assert {
        alert.rule_code
        for alert in alerts
    } == {
        "CONTRACT_NUMBER_MISMATCH",
        "TAX_ID_MISMATCH",
        "TOTAL_AMOUNT_MISMATCH",
        "CURRENCY_MISMATCH",
    }


def test_invoice_arithmetic_is_validated() -> None:
    invoice = make_document(
        "invoice",
        {
            "subtotal": "100",
            "vat_amount": "8",
            "vat_rate": "10",
            "total_amount": "120",
            "amount_in_words": "110",
        },
    )

    alerts = validate_document_values(
        [invoice]
    )

    assert {
        alert.rule_code
        for alert in alerts
    } == {
        "INVOICE_TOTAL_MISMATCH",
        "VAT_AMOUNT_MISMATCH",
        "AMOUNT_IN_WORDS_MISMATCH",
    }


def test_single_documents_use_fallback_pair() -> None:
    contract = make_document(
        "contract",
        {"contract_number": "HD-01"},
    )
    invoice = make_document(
        "invoice",
        {"contract_number": "HD-02"},
    )

    pairs = _build_relation_pairs(
        [contract, invoice],
        [],
    )

    assert len(pairs) == 1
    assert pairs[0] == (
        contract,
        invoice,
        "contract_invoice",
    )