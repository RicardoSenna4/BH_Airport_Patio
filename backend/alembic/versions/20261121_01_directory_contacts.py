"""directory contacts

Revision ID: 20261121_01
Revises: 20260918_01
Create Date: 2026-11-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261121_01"
down_revision: Union[str, Sequence[str], None] = "20260918_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "directory_contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_name", sa.String(length=160), nullable=False),
        sa.Column("contact_name", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=80), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("tags", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_directory_contacts_business_name"),
        "directory_contacts",
        ["business_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_directory_contacts_business_name"), table_name="directory_contacts")
    op.drop_table("directory_contacts")
