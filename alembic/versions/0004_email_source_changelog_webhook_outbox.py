"""Add email_source column, user_email_changelog and webhook_outbox tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-26
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add email_source column to users
    op.add_column("users", sa.Column("email_source", sa.Text(), nullable=False, server_default=sa.text("'crm'")))

    # Create user_email_changelog table
    op.create_table(
        "user_email_changelog",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_email", sa.Text(), nullable=False),
        sa.Column("new_email", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_user_email_changelog_user_id", "user_email_changelog", ["user_id"])
    op.create_index("ix_user_email_changelog_changed_at", "user_email_changelog", ["changed_at"])

    # Create webhook_outbox table
    op.create_table(
        "webhook_outbox",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_webhook_outbox_pending",
        "webhook_outbox",
        ["status", "next_retry_at"],
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )


def downgrade() -> None:
    op.drop_table("webhook_outbox")
    op.drop_table("user_email_changelog")
    op.drop_column("users", "email_source")
