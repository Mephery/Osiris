# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""gabarit_osiris : les modèles qui portent l'agent OSIRIS

Le formulaire de création proposait TOUS les modèles de l'hyperviseur. Un clone
nu d'un modèle sans agent démarre, ne rappelle jamais, et la fiche reste
« pending » sans explication. Le scellement enregistre désormais le gabarit
(UUID SMBIOS + empreinte de l'agent), ce qui permet aussi de repérer un gabarit
dont l'agent gravé est périmé.

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "CREATE TABLE IF NOT EXISTS gabarit_osiris ("
        " id SERIAL PRIMARY KEY,"
        " uuid VARCHAR NOT NULL UNIQUE,"
        " empreinte VARCHAR NOT NULL DEFAULT '',"
        " os VARCHAR NOT NULL DEFAULT '',"
        " nom VARCHAR NOT NULL DEFAULT '',"
        " scelle_le TIMESTAMP NOT NULL DEFAULT now())"
    ))
    op.get_bind().execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_gabarit_osiris_uuid ON gabarit_osiris (uuid)"
    ))


def downgrade() -> None:
    op.drop_table("gabarit_osiris")
