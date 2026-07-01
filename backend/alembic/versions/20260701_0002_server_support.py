"""Server support: machine_type and ssh_authorized_keys on profile

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    stmts = [
        "ALTER TABLE profile ADD COLUMN IF NOT EXISTS machine_type VARCHAR NOT NULL DEFAULT 'workstation'",
        "ALTER TABLE profile ADD COLUMN IF NOT EXISTS ssh_authorized_keys TEXT NOT NULL DEFAULT ''",
    ]
    for stmt in stmts:
        bind.execute(sa.text(stmt))


def downgrade() -> None:
    pass
