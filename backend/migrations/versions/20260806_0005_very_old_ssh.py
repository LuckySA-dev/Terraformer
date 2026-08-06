"""Add very_old_ssh compatibility mode and fortinet_fortios vendor.

Revision ID: 20260806_0005
Revises: 20260806_0004
Create Date: 2026-08-06

Changes:
- Extends the ssh_compatibility check constraint to include 'very_old_ssh'.
- Extends the vendor check constraint to include 'fortinet_fortios'.
- No data migration — all existing devices remain unaffected.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0005"
down_revision: str | None = "20260806_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SSH_COMPAT_VALUES = ("modern", "cisco_legacy", "cisco_legacy_group1", "very_old_ssh")
_SSH_COMPAT_VALUES_OLD = ("modern", "cisco_legacy", "cisco_legacy_group1")

_VENDOR_VALUES = ("cisco_iosxe", "fortinet_fortios", "generic")
_VENDOR_VALUES_OLD = ("cisco_iosxe", "generic")


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "sqlite":
        # SQLite does not support ALTER CONSTRAINT; recreate the table.
        with op.batch_alter_table("devices", recreate="always") as batch:
            batch.drop_constraint("ck_devices_ssh_compatibility", type_="check")
            batch.create_check_constraint(
                "ck_devices_ssh_compatibility",
                "ssh_compatibility IN ({})".format(
                    ", ".join(f"'{v}'" for v in _SSH_COMPAT_VALUES)
                ),
            )
        with op.batch_alter_table("devices", recreate="always") as batch:
            batch.drop_constraint("ck_devices_vendor", type_="check")
            batch.create_check_constraint(
                "ck_devices_vendor",
                "vendor IN ({})".format(
                    ", ".join(f"'{v}'" for v in _VENDOR_VALUES)
                ),
            )
    else:
        # PostgreSQL / other: drop the old constraint, create the new one.
        op.drop_constraint("ck_devices_ssh_compatibility", "devices", type_="check")
        op.create_check_constraint(
            "ck_devices_ssh_compatibility",
            "devices",
            sa.text(
                "ssh_compatibility IN ({})".format(
                    ", ".join(f"'{v}'" for v in _SSH_COMPAT_VALUES)
                )
            ),
        )

        # Vendor column: check whether a CHECK constraint already exists before
        # trying to drop it (the initial migration may not have named it).
        try:
            op.drop_constraint("ck_devices_vendor", "devices", type_="check")
        except Exception:  # noqa: BLE001
            pass  # Constraint did not exist under this name — safe to proceed.

        op.create_check_constraint(
            "ck_devices_vendor",
            "devices",
            sa.text(
                "vendor IN ({})".format(
                    ", ".join(f"'{v}'" for v in _VENDOR_VALUES)
                )
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "sqlite":
        with op.batch_alter_table("devices", recreate="always") as batch:
            batch.drop_constraint("ck_devices_ssh_compatibility", type_="check")
            batch.create_check_constraint(
                "ck_devices_ssh_compatibility",
                "ssh_compatibility IN ({})".format(
                    ", ".join(f"'{v}'" for v in _SSH_COMPAT_VALUES_OLD)
                ),
            )
        with op.batch_alter_table("devices", recreate="always") as batch:
            batch.drop_constraint("ck_devices_vendor", type_="check")
            batch.create_check_constraint(
                "ck_devices_vendor",
                "vendor IN ({})".format(
                    ", ".join(f"'{v}'" for v in _VENDOR_VALUES_OLD)
                ),
            )
    else:
        op.drop_constraint("ck_devices_ssh_compatibility", "devices", type_="check")
        op.create_check_constraint(
            "ck_devices_ssh_compatibility",
            "devices",
            sa.text(
                "ssh_compatibility IN ({})".format(
                    ", ".join(f"'{v}'" for v in _SSH_COMPAT_VALUES_OLD)
                )
            ),
        )
        try:
            op.drop_constraint("ck_devices_vendor", "devices", type_="check")
        except Exception:  # noqa: BLE001
            pass
        op.create_check_constraint(
            "ck_devices_vendor",
            "devices",
            sa.text(
                "vendor IN ({})".format(
                    ", ".join(f"'{v}'" for v in _VENDOR_VALUES_OLD)
                )
            ),
        )
