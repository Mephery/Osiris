# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""hypervisor.ca_cert : l'autorité qui signe le certificat de l'hyperviseur

OSIRIS joignait ses hyperviseurs sans vérifier leur certificat, faute d'autorité
connue pour le valider : le jeton d'API circulait donc sur une session que rien
n'authentifiait. Or un cluster Proxmox **crée sa propre autorité** à
l'installation et signe déjà un certificat par nœud — il ne manquait que de la
faire connaître à OSIRIS.

Colonne en clair, et non chiffrée comme `token_secret` : un certificat d'autorité
est public par nature, il ne sert qu'à vérifier des signatures. Le chiffrer
donnerait l'illusion de protéger un secret là où il n'y en a pas.

Vide sur les fiches existantes, et `tls_verify` reste le maître d'œuvre : le
comportement d'une installation en place ne change pas d'un pouce.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE hypervisor ADD COLUMN IF NOT EXISTS ca_cert TEXT NOT NULL DEFAULT ''"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE hypervisor DROP COLUMN IF EXISTS ca_cert"
    ))
