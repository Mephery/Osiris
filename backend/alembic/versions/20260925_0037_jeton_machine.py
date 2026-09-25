# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""jeton_machine : l'empreinte du jeton qui authentifie les appels d'une machine

Jusqu'ici, connaître une MAC suffisait pour obtenir les scripts d'une machine et
parler en son nom. Le jeton, remis dans le premier script servi et renouvelé à
chaque redéploiement, prouve que l'appel vient bien d'elle. Seule l'empreinte
est conservée.

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS jeton_hash VARCHAR NOT NULL DEFAULT ''"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS jeton_hash"))
