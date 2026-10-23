"""add search extensions and indexes

Revision ID: a6b7c8d9e0f1
Revises: f46e909201a6
"""

from typing import Sequence, Union

from alembic import op


revision: str = "a6b7c8d9e0f1"
down_revision: Union[
    str,
    Sequence[str],
    None,
] = "f46e909201a6"
branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None
depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


def upgrade() -> None:
    op.execute(
        "CREATE EXTENSION IF NOT EXISTS unaccent"
    )
    op.execute(
        "CREATE EXTENSION IF NOT EXISTS pg_trgm"
    )

    op.create_index(
        "ix_extracted_fields_name_trgm",
        "extracted_fields",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={
            "name": "gin_trgm_ops",
        },
    )
    op.create_index(
        "ix_extracted_fields_raw_value_trgm",
        "extracted_fields",
        ["raw_value"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={
            "raw_value": "gin_trgm_ops",
        },
    )
    op.create_index(
        "ix_extracted_fields_normalized_value_trgm",
        "extracted_fields",
        ["normalized_value"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={
            "normalized_value": "gin_trgm_ops",
        },
    )
    op.create_index(
        "ix_extracted_fields_evidence_text_trgm",
        "extracted_fields",
        ["evidence_text"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={
            "evidence_text": "gin_trgm_ops",
        },
    )
    op.create_index(
        "ix_ocr_blocks_text_trgm",
        "ocr_blocks",
        ["text"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={
            "text": "gin_trgm_ops",
        },
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ocr_blocks_text_trgm",
        table_name="ocr_blocks",
    )
    op.drop_index(
        "ix_extracted_fields_evidence_text_trgm",
        table_name="extracted_fields",
    )
    op.drop_index(
        "ix_extracted_fields_normalized_value_trgm",
        table_name="extracted_fields",
    )
    op.drop_index(
        "ix_extracted_fields_raw_value_trgm",
        table_name="extracted_fields",
    )
    op.drop_index(
        "ix_extracted_fields_name_trgm",
        table_name="extracted_fields",
    )

    op.execute(
        "DROP EXTENSION IF EXISTS unaccent"
    )
    op.execute(
        "DROP EXTENSION IF EXISTS pg_trgm"
    )