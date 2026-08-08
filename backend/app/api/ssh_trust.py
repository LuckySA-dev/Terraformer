from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.core.errors import UnsupportedCapabilityError
from app.models import SSHCompatibility, Vendor
from app.repositories.ssh_trust import DeviceSSHHostKeyRepository
from app.schemas.ssh_trust import (
    DeviceSSHHostKeyView,
    HostKeyCandidateRequest,
    HostKeyCandidateView,
)
from app.services.devices import (
    LegacyGroup1DisabledByPolicyError,
    LegacyModeDisabledByPolicyError,
    LegacyVeryOldDisabledByPolicyError,
)

router = APIRouter(tags=["ssh-trust"])

# Vendors that support each compatibility tier.
_CISCO_ONLY_MODES = {SSHCompatibility.CISCO_LEGACY, SSHCompatibility.CISCO_LEGACY_GROUP1}
_VERY_OLD_VENDORS = {Vendor.CISCO_IOSXE, Vendor.FORTINET_FORTIOS}


@router.post(
    "/ssh-host-key-candidates",
    response_model=HostKeyCandidateView,
    status_code=status.HTTP_201_CREATED,
)
async def collect_host_key_candidate(
    request: HostKeyCandidateRequest,
    _auth: Authenticated,
    container: ContainerDependency,
) -> HostKeyCandidateView:
    # Vendor/mode compatibility guard — evaluated before any network attempt.
    if request.ssh_compatibility in _CISCO_ONLY_MODES and request.vendor not in {
        Vendor.CISCO_IOSXE
    }:
        raise UnsupportedCapabilityError(
            "Cisco legacy SSH compatibility is only available for Cisco IOS/IOS-XE devices"
        )
    if (
        request.ssh_compatibility is SSHCompatibility.VERY_OLD_SSH
        and request.vendor not in _VERY_OLD_VENDORS
    ):
        raise UnsupportedCapabilityError(
            "Very old SSHv2 compatibility is only available for Cisco IOS/IOS-XE"
            " and Fortinet FortiOS devices"
        )

    # Kill-switch checks — evaluated before any network attempt.
    if request.ssh_compatibility is not SSHCompatibility.MODERN:
        if not container.settings.ssh_legacy_enabled:
            raise LegacyModeDisabledByPolicyError()
        if request.ssh_compatibility is SSHCompatibility.CISCO_LEGACY_GROUP1 and (
            not container.settings.ssh_group1_enabled or not request.group1_risk_acknowledged
        ):
            raise LegacyGroup1DisabledByPolicyError()
        if request.ssh_compatibility is SSHCompatibility.VERY_OLD_SSH and (
            not container.settings.ssh_group1_enabled
            or not container.settings.ssh_very_old_enabled
            or not request.very_old_risk_acknowledged
        ):
            raise LegacyVeryOldDisabledByPolicyError()

    return await container.host_key_trust.collect_candidate(request)


@router.get("/devices/{device_id}/ssh-host-key", response_model=DeviceSSHHostKeyView)
def get_device_host_key(
    device_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
) -> DeviceSSHHostKeyView:
    record = DeviceSSHHostKeyRepository(session).require(device_id)
    return DeviceSSHHostKeyView.model_validate(record)
