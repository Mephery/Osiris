# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Gabarit materiel des VM porte par le profil (vCPU / RAM / disques)
et mot de passe root de secours sur les serveurs Linux

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLUMNS = [
    ("vm_vcpus", "INTEGER NOT NULL DEFAULT 2"),
    ("vm_ram_mb", "INTEGER NOT NULL DEFAULT 2048"),
    ("vm_disk_gb", "INTEGER NOT NULL DEFAULT 20"),
    ("vm_data_disk_gb", "INTEGER NOT NULL DEFAULT 0"),
    ("set_root_password", "BOOLEAN NOT NULL DEFAULT FALSE"),
]


def upgrade() -> None:
    bind = op.get_bind()
    for name, ddl in _COLUMNS:
        bind.execute(sa.text(f"ALTER TABLE profile ADD COLUMN IF NOT EXISTS {name} {ddl}"))


def downgrade() -> None:
    bind = op.get_bind()
    for name, _ in reversed(_COLUMNS):
        bind.execute(sa.text(f"ALTER TABLE profile DROP COLUMN IF EXISTS {name}"))
