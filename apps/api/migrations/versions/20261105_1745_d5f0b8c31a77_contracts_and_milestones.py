"""customer billing, project dates, milestone states, contracts

Revision ID: d5f0b8c31a77
Revises: c4d8a1e07b22
Create Date: 2026-11-05 17:45:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5f0b8c31a77"
down_revision: str | Sequence[str] | None = "c4d8a1e07b22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("company_name", sa.String(length=160), nullable=True))
    op.add_column("customers", sa.Column("billing_email", sa.String(length=320), nullable=True))
    op.add_column("customers", sa.Column("billing_address", sa.Text(), nullable=True))
    op.add_column("customers", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("starts_on", sa.Date(), nullable=True))
    op.add_column("projects", sa.Column("ends_on", sa.Date(), nullable=True))
    op.create_check_constraint(
        "project_dates_ordered",
        "projects",
        "ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on",
    )
    op.add_column("milestones", sa.Column("due_on", sa.Date(), nullable=True))
    op.add_column("milestones", sa.Column("acceptance_condition", sa.Text(), nullable=True))
    op.execute("UPDATE milestones SET status = 'draft' WHERE status = 'pending'")
    op.alter_column("milestones", "status", server_default="draft")
    op.create_unique_constraint("uq_invoices_milestone_id", "invoices", ["milestone_id"])
    op.create_table(
        "contracts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="needs_review", nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "sha256", name="uq_contracts_workspace_sha256"),
    )
    op.create_index("ix_contracts_workspace_id", "contracts", ["workspace_id"])
    op.create_table(
        "contract_extractions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_label", sa.String(length=160), nullable=False),
        sa.Column("legally_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("findings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("legally_verified = false", name="extraction_not_legally_verified"),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contract_extractions_contract_id", "contract_extractions", ["contract_id"])
    op.create_index("ix_contract_extractions_workspace_id", "contract_extractions", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_contract_extractions_workspace_id", table_name="contract_extractions")
    op.drop_index("ix_contract_extractions_contract_id", table_name="contract_extractions")
    op.drop_table("contract_extractions")
    op.drop_index("ix_contracts_workspace_id", table_name="contracts")
    op.drop_table("contracts")
    op.drop_constraint("uq_invoices_milestone_id", "invoices", type_="unique")
    op.alter_column("milestones", "status", server_default="pending")
    op.drop_column("milestones", "acceptance_condition")
    op.drop_column("milestones", "due_on")
    op.drop_constraint("project_dates_ordered", "projects", type_="check")
    op.drop_column("projects", "ends_on")
    op.drop_column("projects", "starts_on")
    op.drop_column("customers", "archived_at")
    op.drop_column("customers", "billing_address")
    op.drop_column("customers", "billing_email")
    op.drop_column("customers", "company_name")
