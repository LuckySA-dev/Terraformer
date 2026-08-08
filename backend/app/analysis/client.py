"""The only module that knows Batfish exists.

`pybatfish` pulls in pandas and numpy, so it is an optional dependency and is
imported at call time rather than at module import. The same pattern is used for
Scrapli in app/drivers/transport.py. When it is absent the application still
starts and analysis endpoints return a typed error.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.analysis.types import Layer1Edge
from app.core.config import Settings
from app.core.errors import (
    AnalysisBackendUnavailableError,
    AnalysisSnapshotExpiredError,
    AnalysisUnavailableError,
)
from app.models import FindingCategory


@dataclass(frozen=True, slots=True)
class RawFinding:
    category: FindingCategory
    hostname: str | None
    structure_type: str | None
    structure_name: str | None
    detail: str
    line_number: int | None


@dataclass(frozen=True, slots=True)
class InterfaceProperty:
    hostname: str
    interface: str
    switchport_mode: str | None
    access_vlan: int | None


@dataclass(frozen=True, slots=True)
class TraceHop:
    hostname: str
    action: str
    detail: str


@dataclass(frozen=True, slots=True)
class TraceResult:
    disposition: str
    hops: tuple[TraceHop, ...]


@dataclass(frozen=True, slots=True)
class FilterVerdict:
    permitted: bool
    matched_line_index: int | None
    matched_line: str | None


class AnalysisBackend(Protocol):
    def init_snapshot(
        self,
        name: str,
        configs: Mapping[str, str],
        layer1_edges: Sequence[Layer1Edge],
    ) -> None: ...

    def snapshot_exists(self, name: str) -> bool: ...

    def parse_findings(self, name: str) -> tuple[RawFinding, ...]: ...

    def interface_properties(self, name: str) -> tuple[InterfaceProperty, ...]: ...

    def traceroute(
        self, name: str, start_hostname: str, destination_ip: str
    ) -> TraceResult: ...

    def test_filter(
        self,
        name: str,
        hostname: str,
        filter_name: str,
        destination_ip: str,
        protocol: str,
        destination_port: int | None,
    ) -> FilterVerdict: ...


def build_backend(settings: Settings) -> AnalysisBackend:
    try:
        # pybatfish is an optional dependency (see pyproject.toml) and ships no
        # type stubs, so this import is unresolved unless it is explicitly
        # installed into the environment. Imported as a module (not
        # `from ... import Session`) so the single ignore comment below is
        # stable against reformatting: reportUnknownMemberType is already off
        # project-wide (pyproject.toml [tool.pyright]), so only the module
        # resolution itself needs suppressing.
        import pybatfish.client.session as _pybatfish_session  # pyright: ignore[reportMissingImports]
    except Exception:
        # Never surface the import error: it names paths and module versions.
        raise AnalysisUnavailableError() from None
    return PyBatfishBackend(_pybatfish_session.Session, settings)


class PyBatfishBackend:
    def __init__(self, session_factory: Any, settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._session: Any | None = None

    def _connect(self) -> Any:
        if self._session is not None:
            return self._session
        try:
            session = self._session_factory(host=self._settings.batfish_host)
            session.port_v2 = self._settings.batfish_port
        except Exception:
            raise AnalysisBackendUnavailableError() from None
        self._session = session
        return session

    def init_snapshot(
        self,
        name: str,
        configs: Mapping[str, str],
        layer1_edges: Sequence[Layer1Edge],
    ) -> None:
        import json
        import tempfile
        from pathlib import Path

        session = self._connect()
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            config_dir = root / "configs"
            config_dir.mkdir()
            for hostname, content in configs.items():
                (config_dir / f"{hostname}.cfg").write_text(content, encoding="utf-8")
            if layer1_edges:
                batfish_dir = root / "batfish"
                batfish_dir.mkdir()
                (batfish_dir / "layer1_topology.json").write_text(
                    json.dumps(
                        [
                            {
                                "node1": {
                                    "hostname": edge.node1_hostname,
                                    "interfaceName": edge.node1_interface,
                                },
                                "node2": {
                                    "hostname": edge.node2_hostname,
                                    "interfaceName": edge.node2_interface,
                                },
                            }
                            for edge in layer1_edges
                        ]
                    ),
                    encoding="utf-8",
                )
            try:
                session.set_network(name)
                session.init_snapshot(str(root), name=name, overwrite=True)
            except Exception:
                raise AnalysisBackendUnavailableError() from None

    def snapshot_exists(self, name: str) -> bool:
        session = self._connect()
        try:
            session.set_network(name)
            return name in set(session.list_snapshots())
        except Exception:
            return False

    def _ask(self, name: str, question: Any) -> list[dict[str, Any]]:
        session = self._connect()
        try:
            session.set_network(name)
            session.set_snapshot(name)
            frame = question.answer().frame()
        except Exception:
            if not self.snapshot_exists(name):
                raise AnalysisSnapshotExpiredError() from None
            raise AnalysisBackendUnavailableError() from None
        return [
            {str(key): value for key, value in record.items()}
            for record in frame.to_dict(orient="records")
        ]

    def parse_findings(self, name: str) -> tuple[RawFinding, ...]:
        session = self._connect()
        questions = session.q
        findings: list[RawFinding] = []
        for row in self._ask(name, questions.initIssues()):
            findings.append(
                RawFinding(
                    category=FindingCategory.PARSE_WARNING,
                    hostname=_text(row.get("Nodes")),
                    structure_type=None,
                    structure_name=None,
                    detail=f"{_text(row.get('Type'))}: {_text(row.get('Details'))}",
                    line_number=_number(row.get("Line_Text")),
                )
            )
        for row in self._ask(name, questions.undefinedReferences()):
            findings.append(
                RawFinding(
                    category=FindingCategory.UNDEFINED_REFERENCE,
                    hostname=_text(row.get("File_Name")),
                    structure_type=_text(row.get("Struct_Type")),
                    structure_name=_text(row.get("Ref_Name")),
                    detail=f"{_text(row.get('Context'))} references an undefined structure",
                    line_number=_number(row.get("Lines")),
                )
            )
        for row in self._ask(name, questions.unusedStructures()):
            findings.append(
                RawFinding(
                    category=FindingCategory.UNUSED_STRUCTURE,
                    hostname=_text(row.get("File_Name")),
                    structure_type=_text(row.get("Struct_Type")),
                    structure_name=_text(row.get("Struct_Name")),
                    detail="Structure is defined but never used",
                    line_number=_number(row.get("Lines")),
                )
            )
        return tuple(findings)

    def interface_properties(self, name: str) -> tuple[InterfaceProperty, ...]:
        session = self._connect()
        rows = self._ask(
            name,
            session.q.interfaceProperties(
                properties="Switchport_Mode|Access_VLAN"
            ),
        )
        results: list[InterfaceProperty] = []
        for row in rows:
            interface = _text(row.get("Interface")) or ""
            hostname, _, port = interface.partition("[")
            results.append(
                InterfaceProperty(
                    hostname=hostname.strip(),
                    interface=port.rstrip("]").strip() or interface,
                    switchport_mode=_text(row.get("Switchport_Mode")),
                    access_vlan=_number(row.get("Access_VLAN")),
                )
            )
        return tuple(results)

    def traceroute(
        self, name: str, start_hostname: str, destination_ip: str
    ) -> TraceResult:
        session = self._connect()
        rows = self._ask(
            name,
            session.q.traceroute(
                startLocation=start_hostname,
                headers={"dstIps": destination_ip},
            ),
        )
        if not rows:
            return TraceResult(disposition="NO_RESULT", hops=())
        traces = rows[0].get("Traces")
        first = _first_trace(traces)
        return TraceResult(
            disposition=_text(getattr(first, "disposition", None)) or "UNKNOWN",
            hops=tuple(
                TraceHop(
                    hostname=_text(getattr(hop, "node", None)) or "",
                    action=_text(getattr(hop, "action", None)) or "",
                    detail=str(hop),
                )
                for hop in getattr(first, "hops", []) or []
            ),
        )

    def test_filter(
        self,
        name: str,
        hostname: str,
        filter_name: str,
        destination_ip: str,
        protocol: str,
        destination_port: int | None,
    ) -> FilterVerdict:
        session = self._connect()
        headers: dict[str, Any] = {"dstIps": destination_ip, "ipProtocols": protocol}
        if destination_port is not None:
            headers["dstPorts"] = str(destination_port)
        rows = self._ask(
            name,
            session.q.testFilters(nodes=hostname, filters=filter_name, headers=headers),
        )
        if not rows:
            return FilterVerdict(permitted=False, matched_line_index=None, matched_line=None)
        row = rows[0]
        return FilterVerdict(
            permitted=_text(row.get("Action")) == "PERMIT",
            matched_line_index=_number(row.get("Line_Index")),
            matched_line=_text(row.get("Line_Content")),
        )


def _first_trace(traces: Any) -> Any:
    # pybatfish ships no type stubs, so isinstance narrowing against `list`
    # here produces list[Unknown] rather than list[Any]; the function's own
    # `Any` return type is the accurate description of what pybatfish returns.
    if isinstance(traces, list | tuple) and traces:
        return traces[0]  # pyright: ignore[reportUnknownVariableType]
    return traces  # pyright: ignore[reportUnknownVariableType]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, list | tuple) and value:
        return _number(value[0])
    try:
        # `and value` above means pyright cannot narrow list/tuple out of the
        # type reaching here for an empty container; value is still `Any` in
        # every case that matters at runtime.
        return int(str(value).strip())  # pyright: ignore[reportUnknownArgumentType]
    except (TypeError, ValueError):
        return None
