# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""disques : les disques supplémentaires d'une VM, enregistrés sur sa fiche

Le premier démarrage lisait la taille du disque de données dans le PROFIL, pas
dans la demande : un disque ajouté au formulaire était créé, jamais formaté. La
liste (taille, point de montage, libellé, LVM, système de fichiers) vit
désormais sur la fiche. Vide = fiche antérieure, le profil fait encore foi.

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS disques TEXT NOT NULL DEFAULT ''"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS disques"))
