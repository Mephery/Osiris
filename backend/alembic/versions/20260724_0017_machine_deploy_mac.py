# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""machine.deploy_mac : MAC de l'adaptateur USB-Ethernet (facultative, transitoire)

Separe l'identite permanente du poste (machine.mac) de l'adaptateur qui a servi a le
deployer (machine.deploy_mac). Le dongle est oublie en fin de deploiement pour pouvoir
etre reutilise sur une autre machine.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # NULLABLE : une machine deployee sans adaptateur n'a tout simplement pas de dongle.
    bind.execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS deploy_mac VARCHAR NULL"
    ))
    # UNIQUE : Postgres autorise plusieurs NULL sur un index unique, donc autant de
    # machines sans dongle qu'on veut ; mais un dongle donne n'est revendique que par
    # une machine a la fois, ce qui evite toute identification ambigue depuis WinPE.
    bind.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_machine_deploy_mac ON machine (deploy_mac)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_machine_deploy_mac"))
    bind.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS deploy_mac"))
