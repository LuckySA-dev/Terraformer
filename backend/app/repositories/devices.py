from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import NotFoundError
from app.drivers.base import DriverCapabilitySet, InterfaceFacts
from app.models import Device, DeviceCapability, Interface


class DeviceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> list[Device]:
        statement = (
            select(Device)
            .options(selectinload(Device.capabilities))
            .order_by(Device.name, Device.management_address)
        )
        return list(self._session.scalars(statement))

    def get(self, device_id: UUID, *, for_update: bool = False) -> Device:
        statement = (
            select(Device)
            .where(Device.id == device_id)
            .options(selectinload(Device.capabilities))
        )
        if for_update:
            statement = statement.with_for_update()
        device = self._session.scalar(statement)
        if device is None:
            raise NotFoundError(
                "Device not found",
                details={"resource": "device", "id": str(device_id)},
            )
        return device

    def find_by_endpoint(self, address: str, port: int) -> Device | None:
        return self._session.scalar(
            select(Device).where(
                Device.management_address == address,
                Device.port == port,
            )
        )

    def add(self, device: Device) -> Device:
        self._session.add(device)
        self._session.flush()
        return device

    def delete(self, device: Device) -> None:
        self._session.delete(device)
        self._session.flush()

    def replace_capabilities(
        self,
        device: Device,
        capabilities: DriverCapabilitySet,
    ) -> None:
        self._session.execute(
            delete(DeviceCapability).where(DeviceCapability.device_id == device.id)
        )
        device.capabilities = [
            DeviceCapability(
                device_id=device.id,
                name=str(record["name"]),
                supported=bool(record["supported"]),
                safety_level=capabilities.safety_level,
            )
            for record in capabilities.records()
        ]
        self._session.flush()

    def list_interfaces(self, device_id: UUID) -> list[Interface]:
        self.get(device_id)
        statement = (
            select(Interface)
            .where(Interface.device_id == device_id)
            .order_by(Interface.name)
        )
        return list(self._session.scalars(statement))

    def replace_interfaces(self, device: Device, interfaces: list[InterfaceFacts]) -> None:
        self._session.execute(delete(Interface).where(Interface.device_id == device.id))
        self._session.add_all(
            [
                Interface(
                    device_id=device.id,
                    name=item.name,
                    description=item.description,
                    admin_up=item.admin_up,
                    oper_up=item.oper_up,
                    mac_address=item.mac_address,
                    ipv4_addresses=list(item.ipv4_addresses),
                    speed_mbps=item.speed_mbps,
                )
                for item in interfaces
            ]
        )
        self._session.flush()

