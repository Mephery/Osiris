# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""hypervisor.zabbix_server : le collecteur du SITE, pas celui du propriétaire

Le collecteur Zabbix n'était déclaré que sur l'organisation. Une organisation dont
les machines vivent sur plusieurs sites ne pouvait donc en désigner qu'un seul :
toutes les VM visaient le même collecteur, où qu'elles tournent.

Ce n'est pas seulement inélégant, cela se paie en règles de pare-feu. Une VM qui
parle à un collecteur distant traverse tous les pare-feux du trajet, et il faut
une autorisation sur chacun — que rien ne journalise si l'un d'eux manque. Alors
que chaque site a déjà son propre relais : visé depuis l'hyperviseur, le
collecteur est presque toujours un voisin du même sous-réseau, et le trafic ne
rencontre aucun filtre.

Le champ de l'organisation reste le défaut — c'est le seul dont dispose une
machine physique, qui n'a pas d'hyperviseur.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE hypervisor ADD COLUMN IF NOT EXISTS "
        "zabbix_server VARCHAR NOT NULL DEFAULT ''"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE hypervisor DROP COLUMN IF EXISTS zabbix_server"
    ))
