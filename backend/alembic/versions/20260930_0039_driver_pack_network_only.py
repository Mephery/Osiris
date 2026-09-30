# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""driver_pack.network_only : injection hors-ligne réduite à la carte réseau

Le pack constructeur complet injecté hors-ligne (DISM /Add-Driver) dans une image
Windows 11 récente (24H2/25H2) peut figer la passe PnP de sysprep : « SYSPRP
SPPNP … Waiting for device installation to start, Total = 0 » en boucle, puis
« l'ordinateur a redémarré de manière inattendue », le déploiement ne finit
jamais (constaté sur HP EliteBook 840 G9 + pack HP 22H2, le 29/09/2026).

Un pack marqué `network_only` ne fait injecter hors-ligne que ses pilotes réseau
(Class=Net, sans co-installeur) : assez pour que le firstboot atteigne OSIRIS et
joigne le domaine. Les autres pilotes arrivent ensuite en ligne (Windows Update).
Par défaut `false` : les packs qui marchent (Dell, Lenovo…) restent inchangés.

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE driver_pack ADD COLUMN IF NOT EXISTS network_only BOOLEAN NOT NULL DEFAULT false"))


def downgrade() -> None:
    op.get_bind().execute(sa.text("ALTER TABLE driver_pack DROP COLUMN IF EXISTS network_only"))
