# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Supervision Zabbix : proxy par organisation, activation par machine,
et crochet de post-installation Linux sur les applications

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS zabbix_server VARCHAR NOT NULL DEFAULT ''"
    ))
    # Supervision activee par defaut, y compris sur les machines deja en base :
    # sans zabbix_server cote organisation, la case reste sans effet.
    bind.execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS supervised BOOLEAN NOT NULL DEFAULT TRUE"
    ))
    bind.execute(sa.text(
        "ALTER TABLE application ADD COLUMN IF NOT EXISTS linux_post_install VARCHAR NOT NULL DEFAULT ''"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE application DROP COLUMN IF EXISTS linux_post_install"))
    bind.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS supervised"))
    bind.execute(sa.text("ALTER TABLE organization DROP COLUMN IF EXISTS zabbix_server"))
