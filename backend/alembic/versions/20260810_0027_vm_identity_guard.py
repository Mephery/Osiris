# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Garde-fou d'identité des VM : ancre UUID, réservation d'identifiant, pool

Un `proxmox_vm_id` n'est PAS une identité : `cluster/nextid` rend le plus petit
identifiant libre, donc Proxmox recycle ses numéros. Une VM supprimée à la main
sans retirer sa fiche laissait un numéro qui repartait au tourniquet, et la fiche
se mettait à désigner la VM d'un tiers — que toute action destructrice frappait
alors (purge, rollback de snapshot, retour sur le CD WinPE = réinstallation).

Trois objets pour fermer ça :

- `machine.vm_uuid`             : l'ancre non recyclable, comparée avant chaque écriture.
- `ix_machine_vm_reservation`   : deux fiches ne peuvent plus revendiquer le même
                                  numéro sur le même hyperviseur. C'est la
                                  réservation qui manquait à `nextid`, et elle
                                  échoue AVANT tout appel à l'hyperviseur.
- `hypervisor.pool`             : permet de n'attribuer au jeton que des droits sur
                                  `/pool/<pool>` au lieu de `/`, et de faire refuser
                                  par la plateforme elle-même toute action sur une
                                  VM qu'OSIRIS n'a pas créée.

`IF NOT EXISTS` partout : sur une base vierge, la 0001 crée déjà toutes les tables
de models.py, colonnes et index de cette révision compris (cf. la 0006).

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # Vide sur les fiches existantes : la vérification retombe alors sur le nom de
    # la VM, et grave l'UUID relu au premier contrôle réussi. Aucune machine déjà
    # déployée n'a donc besoin d'être retouchée à la main.
    bind.execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS vm_uuid VARCHAR NOT NULL DEFAULT ''"
    ))
    bind.execute(sa.text(
        "ALTER TABLE hypervisor ADD COLUMN IF NOT EXISTS pool VARCHAR NOT NULL DEFAULT ''"
    ))

    # Index PARTIEL : les machines physiques portent toutes `proxmox_vm_id = 0` et
    # doivent rester aussi nombreuses qu'on veut. Sans le `WHERE`, la deuxième
    # machine physique serait refusée.
    bind.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_machine_vm_reservation "
        "ON machine (hypervisor_id, proxmox_vm_id) WHERE proxmox_vm_id > 0"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_machine_vm_reservation"))
    bind.execute(sa.text("ALTER TABLE hypervisor DROP COLUMN IF EXISTS pool"))
    bind.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS vm_uuid"))
