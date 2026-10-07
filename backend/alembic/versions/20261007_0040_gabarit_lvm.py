# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""gabarit_osiris.lvm + machine.root_gb / machine.swap_gb : découpage LVM des clones

Un gabarit Linux construit avec le groupe LVM « osiris » se clone en UN seul
disque, que le premier démarrage découpe : « / » porté à la taille voulue, swap
et volumes supplémentaires en LV du même groupe. Le gabarit est déclaré LVM à la
main (Infrastructure › Gabarits) ; la fiche garde les tailles demandées, que le
premier démarrage relit — y compris au redéploiement.

NULL sur la fiche = machine hors découpage LVM : « / » n'est pas touché.

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE gabarit_osiris ADD COLUMN IF NOT EXISTS lvm BOOLEAN NOT NULL DEFAULT false"))
    bind.execute(sa.text("ALTER TABLE machine ADD COLUMN IF NOT EXISTS root_gb INTEGER"))
    bind.execute(sa.text("ALTER TABLE machine ADD COLUMN IF NOT EXISTS swap_gb INTEGER"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS swap_gb"))
    bind.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS root_gb"))
    bind.execute(sa.text("ALTER TABLE gabarit_osiris DROP COLUMN IF EXISTS lvm"))
