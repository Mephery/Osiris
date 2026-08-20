# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""profile.ntp_servers / apt_mirror / apt_proxy : configurer le temps et les dépôts

Une image cloud arrive avec les réglages du monde ouvert : pools NTP publics et
miroir apt par défaut. Sur un réseau qui n'autorise que certaines destinations,
les deux sont injoignables — et le silence coûte cher.

Pour le temps, il ne s'agit pas de confort : Kerberos refuse une authentification
au-delà de cinq minutes d'écart. Une machine qui dérive perd sa jonction au
domaine, et aucun message ne parle d'horloge. Les contrôleurs de domaine sont la
bonne cible : joignables en interne, et référence de l'AD par construction.

Vide partout = comportement d'origine de la distribution, donc aucun changement
pour les profils existants.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLONNES = ("ntp_servers", "apt_mirror", "apt_proxy")


def upgrade() -> None:
    for colonne in _COLONNES:
        op.get_bind().execute(sa.text(
            f"ALTER TABLE profile ADD COLUMN IF NOT EXISTS "
            f"{colonne} VARCHAR NOT NULL DEFAULT ''"
        ))


def downgrade() -> None:
    for colonne in _COLONNES:
        op.get_bind().execute(sa.text(
            f"ALTER TABLE profile DROP COLUMN IF EXISTS {colonne}"
        ))
