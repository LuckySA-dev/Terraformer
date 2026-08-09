from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from app.core.errors import DriverCommandRejectedError, DriverHostKeyUnknownError
from app.drivers.base import ConnectionParameters, NetworkTransport
from app.drivers.ssh_compatibility import compatibility_policy
from app.drivers.ssh_errors import password_only_openssh_options


class ScrapliTransport:
    """Small adapter that keeps Scrapli outside the service and parser layers."""

    def __init__(self, parameters: ConnectionParameters) -> None:
        self._known_hosts_path, open_cmd = _pinned_open_options(parameters)
        self._closed = False
        try:
            from scrapli import Scrapli

            device: dict[str, Any] = {
                "host": parameters.host,
                "port": parameters.port,
                "auth_username": parameters.username,
                "auth_password": parameters.password,
                "auth_secondary": parameters.enable_password or "",
                "auth_strict_key": True,
                "platform": "cisco_iosxe",
                "transport": "system",
                "timeout_socket": parameters.connect_timeout_seconds,
                "timeout_transport": parameters.connect_timeout_seconds,
                "timeout_ops": parameters.command_timeout_seconds,
                "transport_options": {"open_cmd": open_cmd},
            }
            self._connection = Scrapli(**device)
        except BaseException:
            self._remove_known_hosts()
            raise

    def open(self) -> None:
        try:
            self._connection.open()
        except BaseException:
            self._remove_known_hosts()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._connection.close()
        finally:
            self._remove_known_hosts()

    def _remove_known_hosts(self) -> None:
        path, self._known_hosts_path = self._known_hosts_path, None
        if path is not None:
            Path(path).unlink(missing_ok=True)

    def send_command(self, command: str) -> str:
        response = self._connection.send_command(command)
        if response.failed:
            raise DriverCommandRejectedError()
        return str(response.result)

    def send_config(self, commands: Sequence[str]) -> str:
        # send_configs (not send_command) enters/exits config mode itself and
        # reports per-line failure; stop_on_failed=True halts the batch on
        # the first rejected line rather than pushing the rest of a partial
        # change (confirmed against installed scrapli's IOSXEDriver.send_configs
        # signature: stop_on_failed defaults to False, so this must be explicit).
        response = self._connection.send_configs(list(commands), stop_on_failed=True)
        if response.failed:
            raise DriverCommandRejectedError()
        return str(response.result)


class ScrapliTransportFactory:
    def __call__(self, parameters: ConnectionParameters) -> NetworkTransport:
        return ScrapliTransport(parameters)


class ScrapliGenericTransport:
    """Authenticated SSH transport without a vendor/platform privilege model."""

    def __init__(self, parameters: ConnectionParameters) -> None:
        self._known_hosts_path, open_cmd = _pinned_open_options(parameters)
        self._closed = False
        try:
            from scrapli.driver import GenericDriver

            self._connection = GenericDriver(
                host=parameters.host,
                port=parameters.port,
                auth_username=parameters.username,
                auth_password=parameters.password,
                auth_strict_key=True,
                transport="system",
                timeout_socket=parameters.connect_timeout_seconds,
                timeout_transport=parameters.connect_timeout_seconds,
                timeout_ops=parameters.command_timeout_seconds,
                transport_options={"open_cmd": open_cmd},
            )
        except BaseException:
            self._remove_known_hosts()
            raise

    def open(self) -> None:
        try:
            self._connection.open()
        except BaseException:
            self._remove_known_hosts()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._connection.close()
        finally:
            self._remove_known_hosts()

    def _remove_known_hosts(self) -> None:
        path, self._known_hosts_path = self._known_hosts_path, None
        if path is not None:
            Path(path).unlink(missing_ok=True)

    def send_command(self, command: str) -> str:
        response = self._connection.send_command(command)
        if response.failed:
            raise DriverCommandRejectedError()
        return str(response.result)


class ScrapliGenericTransportFactory:
    def __call__(self, parameters: ConnectionParameters) -> NetworkTransport:
        return ScrapliGenericTransport(parameters)


def _pinned_open_options(parameters: ConnectionParameters) -> tuple[str, list[str]]:
    if not parameters.known_hosts.strip():
        raise DriverHostKeyUnknownError(details={"phase": "host_key_verification"})
    temporary = NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", delete=False)
    try:
        temporary.write(parameters.known_hosts.rstrip("\r\n") + "\n")
        temporary.close()
        os.chmod(temporary.name, 0o600)
    except BaseException:
        temporary.close()
        Path(temporary.name).unlink(missing_ok=True)
        raise
    options = list(
        password_only_openssh_options(compatibility_policy(parameters.ssh_compatibility))
    )
    for value in (
        "StrictHostKeyChecking=yes",
        f"UserKnownHostsFile={temporary.name}",
        "GlobalKnownHostsFile=none",
    ):
        options.extend(("-o", value))
    return temporary.name, options
