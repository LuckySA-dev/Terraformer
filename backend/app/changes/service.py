"""Orchestrates the change pipeline's preview stage.

Apply (Task 6) lives in this same class -- preview and apply share the
repository and device-read plumbing, so splitting them into separate
classes would just be two constructors doing the same setup.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.changes.risk import classify_risk
from app.changes.types import ChangeStepIntent, expand_vlan_list, prefix_parts
from app.core.config import Settings
from app.core.errors import (
    AppError,
    ChangeApplyFailedError,
    ChangePlanNotDraftError,
    ChangePostCheckFailedError,
    ChangeValidationError,
    ChangeVendorUnsupportedError,
    NotFoundError,
    UnsupportedCapabilityError,
)
from app.core.time import utc_now
from app.drivers import DeviceDriver, DriverRegistry
from app.drivers.base import ChangeContext, DriverCapability
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
# Only a trunk change needs the layer-2 view of every port, and it is an extra
# command on the device, so nothing else pays for it.
_SWITCHPORT_AWARE_CHANGES = frozenset({ChangeType.INTERFACE_TRUNK_VLANS})


def _needs_vlans(change_type: ChangeType) -> bool:
    return change_type in _VLAN_AWARE_CHANGES


def _needs_switchports(change_type: ChangeType) -> bool:
    return change_type in _SWITCHPORT_AWARE_CHANGES


def _needs_static_routes(change_type: ChangeType) -> bool:
    return change_type is ChangeType.STATIC_ROUTE


# Which change types name a port in `target`. The rest address the VLAN
# database, a destination prefix, or the device itself, so reading every
# interface for them would be an extra command on the device for nothing --
# and looking one up under a target that is not an interface name at all would
# fail the preview outright.
_INTERFACE_TARGETED_CHANGES = frozenset(
    {
        ChangeType.INTERFACE_DESCRIPTION,
        ChangeType.INTERFACE_ADMIN_STATE,
        ChangeType.INTERFACE_ACCESS_VLAN,
        ChangeType.INTERFACE_TRUNK_VLANS,
    }
)


def _targets_interface(change_type: ChangeType) -> bool:
    return change_type in _INTERFACE_TARGETED_CHANGES


def _post_check_ok(step: ChangeStep, context: ChangeContext) -> bool:
    """Re-reads the device and confirms the change is actually in place.

    A command the device accepted is not the same as a change that took --
    a rejected sub-command, a VLAN that stayed inactive, or a port that never
    left dynamic mode all return a clean prompt. Failing here is what drives
    the rollback.
    """
    if step.change_type is ChangeType.HOSTNAME:
        return context.hostname == step.desired_value
    if step.change_type is ChangeType.VLAN_NAME:
        vlan = context.vlan(int(step.target))
        return vlan is not None and vlan.name == step.desired_value
    if step.change_type is ChangeType.INTERFACE_ACCESS_VLAN:
        assigned = context.access_vlan_of(step.target)
        return assigned is not None and assigned.vlan_id == int(step.desired_value)
    if step.change_type is ChangeType.INTERFACE_TRUNK_VLANS:
        port = context.switchport_of(step.target)
        # Compared as sets: IOS reorders and re-ranges what it is given, so
        # "20,10" reads back as "10,20" and a string comparison would call a
        # change that worked a failure and roll it back.
        return (
            port is not None
            and port.is_trunk()
            and expand_vlan_list(port.trunk_allowed or "")
            == expand_vlan_list(step.desired_value)
        )
    if step.change_type is ChangeType.STATIC_ROUTE:
        destination, mask = prefix_parts(step.target)
        route = context.static_route(destination, mask)
        return route is not None and route.next_hop == step.desired_value.strip()
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
    if change_type is ChangeType.INTERFACE_TRUNK_VLANS:
        port = context.switchport_of(target)
        # A trunk with no explicit list carries every VLAN, and the diff has to
        # say so -- "(none)" would read as the opposite of what is there.
        return (port.trunk_allowed or "ALL") if port is not None else None
    if change_type is ChangeType.STATIC_ROUTE:
        destination, mask = prefix_parts(target)
        existing = context.static_route(destination, mask)
        return existing.next_hop if existing is not None else None
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

    def save_running_config(self, device_id: UUID) -> dict[str, object]:
        """Persist running-config to startup-config on one device.

        Deliberately not a ChangeType. A Change Plan's safety story is that
        every step carries the commands that undo it, and this has no inverse:
        once startup-config is overwritten the previous one is gone. It also
        alters no running state -- what it changes is whether the current
        state survives a reload, which is exactly the recovery path an
        operator would otherwise still have. So it is its own explicit
        operation, confirmed on its own, rather than a step that could ride
        along inside a plan.

        Verification is the device's own acknowledgement of the command, not
        an independent read-back of startup-config: IOS prints "[OK]" and
        reports failures with "%". That is weaker than the post-check a
        Change Plan gets, and is why this is reported rather than rolled back.
        """
        device = self._devices.get(device_id)
        if device.vendor not in _SUPPORTED_VENDORS:
            raise ChangeVendorUnsupportedError()
        driver = self._drivers.get(device.vendor)
        if not driver.capabilities.supports(DriverCapability.SAVE_CONFIG):
            raise UnsupportedCapabilityError(
                "This driver cannot save the running configuration",
                details={"vendor": device.vendor.value},
            )
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
            try:
                driver.save_configuration(parameters)
            except ValueError as error:
                # The device's own words are not echoed back: they can quote
                # configuration text. Only the fact of the failure travels.
                raise AppError("The device did not confirm the save") from error

        return {"device_id": str(device.id), "saved": True}

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
            interfaces = (
                driver.get_interfaces(parameters) if _targets_interface(change_type) else []
            )
            current_hostname = (
                driver.get_facts(parameters).hostname
                if change_type is ChangeType.HOSTNAME
                else None
            )
            # Only read the VLAN database when a VLAN change needs it: it is
            # an extra command on the device, and an interface description
            # has no use for it.
            vlans = tuple(driver.get_vlans(parameters)) if _needs_vlans(change_type) else ()
            switchports = (
                tuple(driver.get_switchports(parameters))
                if _needs_switchports(change_type)
                else ()
            )
            static_routes = (
                tuple(driver.get_static_routes(parameters))
                if _needs_static_routes(change_type)
                else ()
            )

        current = next((iface for iface in interfaces if iface.name == target), None)
        if current is None and _targets_interface(change_type):
            raise NotFoundError(f"Interface {target} was not found on this device")

        context = ChangeContext(
            interface=current,
            vlans=vlans,
            switchports=switchports,
            static_routes=static_routes,
            hostname=current_hostname,
        )
        step = ChangeStepIntent(change_type=change_type, target=target, desired_value=desired_value)
        # Validation runs first. Renderers are entitled to assume a validated
        # step -- several of them parse the target as an integer or a prefix --
        # so rendering an unvalidated one raised a bare ValueError out of the
        # request, which reached the operator as a 500 instead of the list of
        # things actually wrong with what they typed.
        issues = driver.validate_change(step, context)
        if issues:
            # 422, not the bare AppError's 500: these are all rejections of
            # what the operator typed, not a server fault.
            raise ChangeValidationError(details={"issues": issues})
        rendered = driver.render_change(step, context)

        pre_snapshot = self._snapshots.capture(device.id)

        previous_value = _previous_value(change_type, target, context)
        risk = classify_risk(
            change_type,
            current_admin_up=current.admin_up if current else None,
            current_oper_up=current.oper_up if current else None,
            desired_value=desired_value,
            target=target,
            previous_value=previous_value,
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
            previous_value=previous_value,
            desired_value=desired_value,
            # Stored verbatim, deliberately. These strings are the same text
            # the operator reviews at preview, the worker sends to the device,
            # and the rollback sends to put it back; if any of them differed the
            # preview would be a lie. Running them through the log sanitizer did
            # differ: it rewrites the token after "password", "secret", "token",
            # "community" or "api key", so a description like "link to community
            # switch" was stored -- and would have been configured on the device
            # -- as "link to community [REDACTED]". docs/safety-model.md scopes
            # that sanitizer to logs and events and calls it defense in depth; a
            # Change Plan's commands are the executable artifact, not a log line.
            rendered_commands="\n".join(rendered.commands),
            inverse_commands="\n".join(rendered.inverse_commands),
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
        # One plan is one change -- what preview() builds, and what the whole
        # preview/apply/rollback story assumes. Reading steps[0] out of a plan
        # that somehow held more would apply part of it and roll back part of
        # it, so it refuses rather than guess which part.
        if len(plan.steps) != 1:
            self._changes.set_status(
                plan, ChangePlanStatus.FAILED, failure_code=ChangeApplyFailedError.code
            )
            self._session.commit()
            raise ChangeApplyFailedError("A change plan must carry exactly one step")
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
                interfaces = (
                    driver.get_interfaces(parameters)
                    if _targets_interface(step.change_type)
                    else []
                )
                post_hostname = (
                    driver.get_facts(parameters).hostname
                    if step.change_type is ChangeType.HOSTNAME
                    else None
                )
                vlans = (
                    tuple(driver.get_vlans(parameters))
                    if _needs_vlans(step.change_type)
                    else ()
                )
                switchports = (
                    tuple(driver.get_switchports(parameters))
                    if _needs_switchports(step.change_type)
                    else ()
                )
                static_routes = (
                    tuple(driver.get_static_routes(parameters))
                    if _needs_static_routes(step.change_type)
                    else ()
                )
            current = next((iface for iface in interfaces if iface.name == step.target), None)
            if not _post_check_ok(
                step,
                ChangeContext(
                    interface=current,
                    vlans=vlans,
                    switchports=switchports,
                    static_routes=static_routes,
                    hostname=post_hostname,
                ),
            ):
                raise ChangePostCheckFailedError()
        except AppError as error:
            return self._attempt_rollback(plan, device, driver, inverse_commands, error.code)
        except Exception:
            # Anything that is not a typed AppError is a fault in this service
            # rather than a device refusing the change. It must still end the
            # plan: leaving it APPLYING means the operator's window polls a
            # status that will never arrive, and the change can never be
            # applied or rolled back again. Rollback is attempted for the same
            # reason -- what reached the device is unknown, and the inverse is
            # the only thing that can put it back.
            return self._attempt_rollback(
                plan, device, driver, inverse_commands, ChangeApplyFailedError.code
            )

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
