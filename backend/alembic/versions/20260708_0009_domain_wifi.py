# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Add wifi_ssid/wifi_password to domain_config

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE domain_config ADD COLUMN IF NOT EXISTS wifi_ssid VARCHAR NOT NULL DEFAULT ''"))
    bind.execute(sa.text("ALTER TABLE domain_config ADD COLUMN IF NOT EXISTS wifi_password VARCHAR NOT NULL DEFAULT ''"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE domain_config DROP COLUMN IF EXISTS wifi_password"))
    bind.execute(sa.text("ALTER TABLE domain_config DROP COLUMN IF EXISTS wifi_ssid"))
