# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""machine.ip_constatee + machine.ip_constatee_at : l'IP vue par la machine

Remontée par le premier démarrage avec les tests : seule source de l'adresse
d'une machine en DHCP quand l'hyperviseur ne peut pas la lire.

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS ip_constatee VARCHAR NOT NULL DEFAULT ''"))
    bind.execute(sa.text("ALTER TABLE machine ADD COLUMN IF NOT EXISTS ip_constatee_at TIMESTAMP"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS ip_constatee_at"))
    bind.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS ip_constatee"))
