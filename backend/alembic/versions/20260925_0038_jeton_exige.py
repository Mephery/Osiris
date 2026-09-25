# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""jeton_exige : renouvellement du jeton et exigence par machine

`jeton_renouveler` : un redéploiement marque le jeton à renouveler au lieu de
l'effacer — l'effacer permettait à quiconque de se faire remettre le suivant.
`jeton_exige` : les VM clonées d'un gabarit portant l'agent actuel doivent
toujours présenter leur jeton, sans attendre le mode obligatoire global.

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS jeton_renouveler BOOLEAN NOT NULL DEFAULT false"))
    op.get_bind().execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS jeton_exige BOOLEAN NOT NULL DEFAULT false"))


def downgrade() -> None:
    op.get_bind().execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS jeton_exige"))
    op.get_bind().execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS jeton_renouveler"))
