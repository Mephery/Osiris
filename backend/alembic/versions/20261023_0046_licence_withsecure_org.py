# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""organization.withsecure_voucher / withsecure_profile_id : licence par client

La cle d'abonnement etait ecrite dans les arguments d'une application par
client, choisie par le profil : un profil copie depuis un autre client
enregistrait les postes sur la licence de cet autre client. Elle vit
desormais sur l'organisation (cle chiffree Fernet, identifiant en clair).

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS withsecure_voucher VARCHAR NOT NULL DEFAULT ''"))
    bind.execute(sa.text(
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS withsecure_profile_id VARCHAR NOT NULL DEFAULT ''"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE organization DROP COLUMN IF EXISTS withsecure_profile_id"))
    bind.execute(sa.text("ALTER TABLE organization DROP COLUMN IF EXISTS withsecure_voucher"))
