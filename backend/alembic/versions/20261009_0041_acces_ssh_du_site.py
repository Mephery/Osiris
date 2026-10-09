# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""hypervisor.ssh_root_keys + hypervisor.ssh_password_login : accès SSH du site

Chaque site a ses propres portes d'entrée (serveur PXE, bastion) qui doivent
ouvrir toutes les VM Linux qui y tournent, quel que soit le profil : des clés
posées chez root (clé uniquement), et au besoin un mot de passe pour le compte
d'administration du profil.

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE hypervisor ADD COLUMN IF NOT EXISTS ssh_root_keys VARCHAR NOT NULL DEFAULT ''"))
    bind.execute(sa.text(
        "ALTER TABLE hypervisor ADD COLUMN IF NOT EXISTS ssh_password_login BOOLEAN NOT NULL DEFAULT false"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE hypervisor DROP COLUMN IF EXISTS ssh_password_login"))
    bind.execute(sa.text("ALTER TABLE hypervisor DROP COLUMN IF EXISTS ssh_root_keys"))
