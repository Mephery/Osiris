# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""machine.created_at : depuis quand une fiche attend

Une fiche restée « pending » était indétectable. Un clone dont l'agent ne
rappelle jamais ne produit aucun évènement de déploiement, aucune ligne de
journal et aucune erreur : la fiche reste exactement dans l'état où la création
l'a laissée. Rien ne distinguait donc une fiche créée il y a trente secondes
d'une fiche abandonnée depuis trois semaines — et c'est ce qui a rendu la panne
du 25/08 invisible des deux côtés.

`deployed_at` ne pouvait pas servir de repère : il n'est renseigné qu'au
déploiement réussi, c'est-à-dire précisément le cas qui n'arrive pas.

Les lignes déjà présentes prennent la date de la migration : leur ancienneté
réelle est perdue, faute de l'avoir jamais écrite. Sans conséquence — elles sont
déployées, donc hors du périmètre de la sonde — sauf pour les fiches « pending »
héritées, qui seront signalées un délai après la migration au lieu de l'être
depuis leur vraie création.

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS "
        "created_at TIMESTAMP NOT NULL DEFAULT now()"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE machine DROP COLUMN IF EXISTS created_at"
    ))
