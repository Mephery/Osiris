# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""profile.withsecure_profile_id : politique WithSecure propre au profil

Un meme client peut avoir plusieurs politiques WithSecure (postes de bureau,
direction...). La cle reste celle de l'organisation ; le profil de
deploiement peut seulement choisir une autre politique. Vide = celle de
l'organisation.

Revision ID: 0047
Revises: 0046
Create Date: 2026-10-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0047"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE profile ADD COLUMN IF NOT EXISTS withsecure_profile_id VARCHAR NOT NULL DEFAULT ''"))


def downgrade() -> None:
    op.get_bind().execute(sa.text("ALTER TABLE profile DROP COLUMN IF EXISTS withsecure_profile_id"))
