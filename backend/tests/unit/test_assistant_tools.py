from __future__ import annotations

from typing import ClassVar
from uuid import uuid4

import pytest

from app.assistant.tools import READ_ONLY_TOOLS, ReadOnlyToolError, ToolDispatcher


def test_read_only_tools_never_include_a_write_tool() -> None:
    write_markers = ("apply", "delete", "create", "update", "set", "write", "send")
    for tool in READ_ONLY_TOOLS:
        lowered_name = tool.name.lower()
        assert not any(marker in lowered_name for marker in write_markers), tool.name


def test_dispatch_facts_returns_device_facts() -> None:
    device_id = uuid4()

    class _FakeDevice:
        facts: ClassVar = {"hostname": "edge-01"}
        last_seen_at = None

    class _FakeDevices:
        def get(self, requested_id):
            assert requested_id == device_id
            return _FakeDevice()

        def list_interfaces(self, requested_id):
            raise AssertionError("not called")

        def list_neighbors(self, requested_id):
            raise AssertionError("not called")

    dispatcher = ToolDispatcher(devices=_FakeDevices(), snapshots=None, events=None)  # type: ignore[arg-type]
    result = dispatcher.dispatch("get_device_facts", {"device_id": str(device_id)})

    assert result.name == "get_device_facts"
    assert result.payload["facts"] == {"hostname": "edge-01"}


def test_dispatch_rejects_missing_device_id() -> None:
    dispatcher = ToolDispatcher(devices=None, snapshots=None, events=None)  # type: ignore[arg-type]
    with pytest.raises(ReadOnlyToolError):
        dispatcher.dispatch("get_device_facts", {})


def test_dispatch_unknown_tool_raises() -> None:
    dispatcher = ToolDispatcher(devices=None, snapshots=None, events=None)  # type: ignore[arg-type]
    with pytest.raises(ReadOnlyToolError):
        dispatcher.dispatch("apply_change_plan", {"device_id": str(uuid4())})
