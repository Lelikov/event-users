"""Add message_id to user_email_changelog for consumer idempotency.

RabbitMQ delivery is at-least-once: redelivered user.email.change_requested
messages must not duplicate changelog entries or CRM webhooks. The CloudEvent
ce-id is persisted with the changelog entry under a unique index; a conflict
means the message was already processed.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-11
"""

import sqlalchemy as sa

from alembic import op


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_email_changelog", sa.Column("message_id", sa.Text(), nullable=True))
    op.create_index(
        "uq_user_email_changelog_message_id",
        "user_email_changelog",
        ["message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_user_email_changelog_message_id", table_name="user_email_changelog")
    op.drop_column("user_email_changelog", "message_id")
