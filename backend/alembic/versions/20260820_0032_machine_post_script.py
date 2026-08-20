# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""machine.post_script : un script propre à UNE machine, pas à tout un profil

Le profil portait déjà un script de post-installation, mais il est partagé par
toutes les machines qui l'utilisent. Personnaliser une seule VM obligeait donc à
dupliquer un profil entier pour trois lignes — et à maintenir ensuite deux
profils qui divergent lentement.

Ce champ porte ce qui ne vaut que pour cette machine. Il s'exécute APRÈS celui du
profil : socle commun d'abord, spécificité ensuite. Les deux se cumulent.

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS "
        "post_script VARCHAR NOT NULL DEFAULT ''"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE machine DROP COLUMN IF EXISTS post_script"
    ))
