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
from app.core.errors import (
    AppError,
    ChangePlanNotDraftError,
    ChangeValidationError,
    ChangeVendorUnsupportedError,
    NotFoundError,
)
from app.core.logging import sanitize_text
from app.core.time import utc_now
from app.drivers import DeviceDriver, DriverRegistry
from app.drivers.base import ChangeContext
from app.models import (
    ChangePlan,
    ChangePlanSource,
    ChangePlanStatus,
    ChangeStep,
    ChangeType,
    Device,
    SSHCompatibility,
    Vendor,
)
from app.repositories.changes import ChangeRepository
from app.repositories.devices import DeviceRepository
from app.services.connection_gate import ConnectionOperation
from app.services.devices import DeviceService
from app.services.snapshots import SnapshotService

_SUPPORTED_VENDORS = frozenset({Vendor.CISCO_IOSXE})

_VLAN_AWARE_CHANGES = frozenset({ChangeType.VLAN_NAME, ChangeType.INTERFACE_ACCESS_VLAN})


def _needs_vlans(change_type: ChangeType) -> bool:
    return change_type in _VLAN_AWARE_CHANGES


def _post_check_ok(step: ChangeStep, context: ChangeContext) -> bool:
    """Re-reads the device and confirms the change is actually in place.

    A command the device accepted is not the same as a change that took --
    a rejected sub-command, a VLAN that stayed inactive, or a port that never
    left dynamic mode all return a clean prompt. Failing here is what drives
    the rollback.
    """
    if step.change_type is ChangeType.VLAN_NAME:
        vlan = context.vlan(int(step.target))
        return vlan is not None and vlan.name == step.desired_value
    if step.change_type is ChangeType.INTERFACE_ACCESS_VLAN:
        assigned = context.access_vlan_of(step.target)
        return assigned is not None and assigned.vlan_id == int(step.desired_value)
    interface = context.interface
    if interface is None:
        return False
    if step.change_type is ChangeType.INTERFACE_DESCRIPTION:
        return interface.description == step.desired_value
    return interface.admin_up == (step.desired_value == "up")


def _previous_value(change_type: ChangeType, target: str, context: ChangeContext) -> str | None:
    """What the device held before this change -- shown as the diff's left side."""
    if change_type is ChangeType.VLAN_NAME:
        existing = context.vlan(int(target))
        return existing.name if existing is not None else None
    if change_type is ChangeType.INTERFACE_ACCESS_VLAN:
        previous = context.access_vlan_of(target)
        return str(previous.vlan_id) if previous is not None else None
    interface = context.interface
    if interface is None:
        return None
    if change_type is ChangeType.INTERFACE_DESCRIPTION:
        return interface.description
    return "up" if interface.admin_up else "down"


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
        self,
        *,
        device_id: UUID,
        change_type: ChangeType,
        target: str,
        desired_value: str,
        source: ChangePlanSource = ChangePlanSource.MANUAL,
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
            # Only read the VLAN database when a VLAN change needs it: it is
            # an extra command on the device, and an interface description
            # has no use for it.
            vlans = tuple(driver.get_vlans(parameters)) if _needs_vlans(change_type) else ()

        # A VLAN rename targets the VLAN database, not a port, so there is no
        # interface to look up and its absence is not an error.
        current = next((iface for iface in interfaces if iface.name == target), None)
        if current is None and change_type is not ChangeType.VLAN_NAME:
            raise NotFoundError(f"Interface {target} was not found on this device")

        context = ChangeContext(interface=current, vlans=vlans)
        step = ChangeStepIntent(change_type=change_type, target=target, desired_value=desired_value)
        rendered = driver.render_change(step, context)
        issues = driver.validate_change(step, context)
        if issues:
            # 422, not the bare AppError's 500: these are all rejections of
            # what the operator typed, not a server fault.
            raise ChangeValidationError(details={"issues": issues})

        pre_snapshot = self._snapshots.capture(device.id)

        previous_value = _previous_value(change_type, target, context)
        risk = classify_risk(
            change_type,
            current_admin_up=current.admin_up if current else None,
            current_oper_up=current.oper_up if current else None,
            desired_value=desired_value,
        )

        plan = self._changes.create(
            device_id=device.id,
            safety_level=driver.capabilities.safety_level,
            risk=risk,
            source=source,
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

    def apply(self, plan_id: UUID) -> dict[str, object]:
        plan = self._changes.get(plan_id, for_update=True)
        if plan.status is not ChangePlanStatus.DRAFT:
            raise ChangePlanNotDraftError()
        self._changes.set_status(plan, ChangePlanStatus.APPLYING)
        self._session.commit()

        device = self._devices.get(plan.device_id)
        driver = self._drivers.get(device.vendor)
        step = plan.steps[0]
        rendered_commands = step.rendered_commands.splitlines()
        inverse_commands = step.inverse_commands.splitlines()

        try:
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
                operation=ConnectionOperation.STRUCTURED_WRITE,
            ) as parameters:
                driver.apply_configuration(parameters, rendered_commands)
                interfaces = driver.get_interfaces(parameters)
                vlans = (
                    tuple(driver.get_vlans(parameters))
                    if _needs_vlans(step.change_type)
                    else ()
                )
            current = next((iface for iface in interfaces if iface.name == step.target), None)
            if not _post_check_ok(step, ChangeContext(interface=current, vlans=vlans)):
                raise AppError("Post-check did not confirm the applied change")
        except AppError as error:
            return self._attempt_rollback(plan, device, driver, inverse_commands, error.code)

        post_snapshot = self._snapshots.capture(device.id)
        self._changes.set_snapshots(plan, post_change_snapshot_id=post_snapshot.id)
        self._changes.set_status(plan, ChangePlanStatus.APPLIED)
        plan.applied_at = utc_now()
        self._session.commit()
        return {"change_plan_id": str(plan.id), "status": plan.status.value}

    def _attempt_rollback(
        self,
        plan: ChangePlan,
        device: Device,
        driver: DeviceDriver,
        inverse_commands: list[str],
        failure_code: str,
    ) -> dict[str, object]:
        try:
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
                operation=ConnectionOperation.STRUCTURED_WRITE,
            ) as parameters:
                driver.rollback(parameters, inverse_commands)
            self._changes.set_status(plan, ChangePlanStatus.ROLLED_BACK, failure_code=failure_code)
        except Exception:
            self._changes.set_status(
                plan, ChangePlanStatus.ROLLBACK_FAILED, failure_code=failure_code
            )
        self._session.commit()
        return {"change_plan_id": str(plan.id), "status": plan.status.value}
