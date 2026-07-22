from __future__ import annotations

from typing import Any

from app.core.errors import DriverCommandRejectedError
from app.drivers.base import ConnectionParameters, NetworkTransport
from app.drivers.ssh_compatibility import compatibility_policy
from app.drivers.ssh_errors import password_only_openssh_options


class ScrapliTransport:
    """Small adapter that keeps Scrapli outside the service and parser layers."""

    def __init__(self, parameters: ConnectionParameters, *, strict_host_key: bool) -> None:
        from scrapli import Scrapli

        device: dict[str, Any] = {
            "host": parameters.host,
            "port": parameters.port,
            "auth_username": parameters.username,
            "auth_password": parameters.password,
            "auth_secondary": parameters.enable_password or "",
            "auth_strict_key": strict_host_key,
            "platform": "cisco_iosxe",
            "transport": "system",
            "timeout_socket": parameters.connect_timeout_seconds,
            "timeout_transport": parameters.connect_timeout_seconds,
            "timeout_ops": parameters.command_timeout_seconds,
            "transport_options": {
                "open_cmd": list(
                    password_only_openssh_options(
                        compatibility_policy(parameters.ssh_compatibility)
                    )
                )
            },
        }
        self._connection = Scrapli(**device)

    def open(self) -> None:
        self._connection.open()

    def close(self) -> None:
        self._connection.close()

    def send_command(self, command: str) -> str:
        response = self._connection.send_command(command)
        if response.failed:
            raise DriverCommandRejectedError()
        return str(response.result)


class ScrapliTransportFactory:
    def __init__(self, *, strict_host_key: bool = True) -> None:
        self._strict_host_key = strict_host_key

    def __call__(self, parameters: ConnectionParameters) -> NetworkTransport:
        return ScrapliTransport(parameters, strict_host_key=self._strict_host_key)


class ScrapliGenericTransport:
    """Authenticated SSH transport without a vendor/platform privilege model."""

    def __init__(self, parameters: ConnectionParameters, *, strict_host_key: bool) -> None:
        from scrapli.driver import GenericDriver

        self._connection = GenericDriver(
            host=parameters.host,
            port=parameters.port,
            auth_username=parameters.username,
            auth_password=parameters.password,
            auth_strict_key=strict_host_key,
            transport="system",
            timeout_socket=parameters.connect_timeout_seconds,
            timeout_transport=parameters.connect_timeout_seconds,
            timeout_ops=parameters.command_timeout_seconds,
            transport_options={
                "open_cmd": list(
                    password_only_openssh_options(
                        compatibility_policy(parameters.ssh_compatibility)
                    )
                )
            },
        )

    def open(self) -> None:
        self._connection.open()

    def close(self) -> None:
        self._connection.close()

    def send_command(self, command: str) -> str:
        response = self._connection.send_command(command)
        if response.failed:
            raise DriverCommandRejectedError()
        return str(response.result)


class ScrapliGenericTransportFactory:
    def __init__(self, *, strict_host_key: bool = True) -> None:
        self._strict_host_key = strict_host_key

    def __call__(self, parameters: ConnectionParameters) -> NetworkTransport:
        return ScrapliGenericTransport(parameters, strict_host_key=self._strict_host_key)
