"""Orchestrates the change pipeline's preview stage.

Apply (Task 6) lives in this same class -- preview and apply share the
repository and device-read plumbing, so splitting them into separate
classes would just be two constructors doing the same setup.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.changes.risk import classify_risk
from app.changes.types import ChangeStepIntent
from app.core.config import Settings
from app.core.errors import AppError, ChangeVendorUnsupportedError, NotFoundError
from app.core.logging import sanitize_text
from app.drivers import DriverRegistry
from app.models import ChangePlan, ChangeType, SSHCompatibility, Vendor
from app.repositories.changes import ChangeRepository
from app.repositories.devices import DeviceRepository
from app.services.connection_gate import ConnectionOperation
from app.services.devices import DeviceService
from app.services.snapshots import SnapshotService

_SUPPORTED_VENDORS = frozenset({Vendor.CISCO_IOSXE})


class ChangeService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        drivers: DriverRegistry,
        devices: DeviceService,
        snapshots: SnapshotService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._drivers = drivers
        self._device_service = devices
        self._snapshots = snapshots
        self._changes = ChangeRepository(session)
        self._devices = DeviceRepository(session)

    def preview(
        self, *, device_id: UUID, change_type: ChangeType, target: str, desired_value: str
    ) -> ChangePlan:
        device = self._devices.get(device_id)
        if device.vendor not in _SUPPORTED_VENDORS:
            raise ChangeVendorUnsupportedError()

        driver = self._drivers.get(device.vendor)
        with self._device_service.admitted_connection(
            device_id=device.id,
            host=device.management_address,
            port=device.port,
            profile_id=device.credential_profile_id,
            vendor=device.vendor,
            compatibility=device.ssh_compatibility,
            group1_risk_acknowledged=(
                device.ssh_compatibility is SSHCompatibility.CISCO_LEGACY_GROUP1
            ),
            operation=ConnectionOperation.STRUCTURED_READ,
        ) as parameters:
            interfaces = driver.get_interfaces(parameters)
        current = next((iface for iface in interfaces if iface.name == target), None)
        if current is None:
            raise NotFoundError(f"Interface {target} was not found on this device")

        step = ChangeStepIntent(change_type=change_type, target=target, desired_value=desired_value)
        rendered = driver.render_change(step, current)
        issues = driver.validate_change(step, current)
        if issues:
            raise AppError("The rendered change failed validation", details={"issues": issues})

        pre_snapshot = self._snapshots.capture(device.id)

        previous_value = (
            current.description
            if change_type is ChangeType.INTERFACE_DESCRIPTION
            else ("up" if current.admin_up else "down")
        )
        risk = classify_risk(
            change_type,
            current_admin_up=current.admin_up,
            current_oper_up=current.oper_up,
            desired_value=desired_value,
        )

        plan = self._changes.create(
            device_id=device.id,
            safety_level=driver.capabilities.safety_level,
            risk=risk,
        )
        self._changes.set_snapshots(plan, pre_change_snapshot_id=pre_snapshot.id)
        self._changes.add_step(
            plan,
            change_type=change_type,
            target=target,
            previous_value=sanitize_text(previous_value) if previous_value else previous_value,
            desired_value=desired_value,
            rendered_commands=sanitize_text("\n".join(rendered.commands)),
            inverse_commands=sanitize_text("\n".join(rendered.inverse_commands)),
        )
        self._session.commit()
        return self._changes.get(plan.id)

    def get(self, plan_id: UUID) -> ChangePlan:
        return self._changes.get(plan_id)

    def list_for_device(self, device_id: UUID) -> list[ChangePlan]:
        return self._changes.list_by_device(device_id)
