"""Establish the empty PDOS migration history.

Revision ID: 0000_scaffold
Revises:
Create Date: 2026-08-10
"""

from collections.abc import Sequence

revision: str = "0000_scaffold"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
