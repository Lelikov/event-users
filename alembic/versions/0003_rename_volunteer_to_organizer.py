"""rename volunteer role to organizer.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-13 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op


revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'organizer' WHERE role = 'volunteer'")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'volunteer' WHERE role = 'organizer'")
