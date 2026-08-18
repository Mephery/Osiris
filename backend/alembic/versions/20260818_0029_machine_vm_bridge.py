# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""machine.vm_bridge : le réseau sur lequel la VM est raccordée

Le formulaire de création demandait l'adressage IP en entier — adresse,
passerelle, DNS — sans jamais rien proposer. Or ces trois valeurs sont des
propriétés du RÉSEAU, pas de la machine : les retaper à chaque déploiement, de
mémoire, est une invitation à la faute de frappe, et une passerelle erronée ne
fait échouer aucun appel — la VM démarre, ne route nulle part et reste « en
attente » sans un mot d'explication.

L'hyperviseur ne peut répondre que pour une minorité de réseaux : un bridge n'a
d'adresse que si le nœud lui-même est sur ce VLAN, ce qui est l'exception. Pour
tous les autres, la seule source de vérité disponible est ce qui a déjà été
déployé là. Encore faut-il savoir où : d'où cette colonne.

Vide sur les fiches existantes, et le reste sans conséquence — une absence de
proposition, jamais une proposition fausse.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS vm_bridge VARCHAR NOT NULL DEFAULT ''"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE machine DROP COLUMN IF EXISTS vm_bridge"
    ))
