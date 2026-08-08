"""Orchestrates analysis initialisation and completeness reporting.

The API and the worker both go through this class; neither touches the backend
client or the repository directly.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from sqlalchemy.orm import Session

from app.analysis.client import AnalysisBackend, FilterVerdict, TraceResult
from app.analysis.drift import topology_drift_findings
from app.analysis.findings import to_findings
from app.analysis.snapshot_builder import build_analysis_input
from app.core.config import Settings
from app.core.errors import (
    AnalysisNoConfigsError,
    AnalysisSnapshotExpiredError,
    AppError,
    NotFoundError,
)
from app.models import AnalysisSnapshot, AnalysisStatus, ConfigSnapshot, ExclusionReason
from app.repositories.analysis import AnalysisRepository
from app.repositories.devices import DeviceRepository
from app.repositories.events import EventRepository
from app.schemas.analysis import CompletenessView, ExclusionView
from app.services.snapshots import SnapshotService

_QueryResultT = TypeVar("_QueryResultT")


class AnalysisService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        backend: AnalysisBackend,
        snapshots: SnapshotService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._backend = backend
        self._snapshots = snapshots
        self._analysis = AnalysisRepository(session)
        self._devices = DeviceRepository(session)
        self._events = EventRepository(session)

    def initialise_new(self) -> dict[str, object]:
        """Create the snapshot row and parse it.

        The row is created here rather than in the API handler so a request
        rejected by the one-at-a-time guard (JobService.enqueue) cannot leave
        an orphan `pending` row behind.
        """
        snapshot = self._analysis.create()
        self._session.commit()
        return self.initialise(snapshot.id)

    def initialise(self, analysis_snapshot_id: UUID) -> dict[str, object]:
        snapshot = self._analysis.get(analysis_snapshot_id, for_update=True)
        self._analysis.set_status(snapshot, AnalysisStatus.PARSING)
        self._session.commit()

        try:
            result = self._initialise(snapshot)
        except AppError as error:
            self._analysis.set_status(snapshot, AnalysisStatus.FAILED, failure_code=error.code)
            self._session.commit()
            raise
        self._session.commit()
        return result

    def _initialise(self, snapshot: AnalysisSnapshot) -> dict[str, object]:
        devices = self._devices.list()
        latest: dict[UUID, ConfigSnapshot] = {}
        content: dict[UUID, str] = {}
        for device in devices:
            stored = self._snapshots.list(device_id=device.id, limit=1)
            if not stored:
                continue
            latest[device.id] = stored[0]
            _record, sanitized = self._snapshots.get_sanitized_content(stored[0].id)
            content[device.id] = sanitized

        neighbors = [
            neighbor for device in devices for neighbor in self._devices.list_neighbors(device.id)
        ]
        analysis_input = build_analysis_input(
            devices=devices,
            latest_snapshot_for=latest,
            sanitized_content_for=content,
            neighbors=neighbors,
            max_devices=self._settings.analysis_max_devices,
        )
        if not analysis_input.configs:
            raise AnalysisNoConfigsError()

        for config in analysis_input.configs:
            self._analysis.add_member(
                snapshot,
                device_id=config.device_id,
                config_snapshot_id=config.config_snapshot_id,
                batfish_hostname=config.batfish_hostname,
                exclusion_reason=None,
            )
        for excluded in analysis_input.excluded:
            self._analysis.add_member(
                snapshot,
                device_id=excluded.device_id,
                config_snapshot_id=None,
                batfish_hostname=None,
                exclusion_reason=excluded.reason,
            )
        self._analysis.record_scope(
            snapshot,
            device_count=len(analysis_input.configs),
            observed_link_count=len(analysis_input.layer1_edges),
            oldest_config_at=analysis_input.oldest_config_at,
            newest_config_at=analysis_input.newest_config_at,
        )

        self._backend.init_snapshot(
            str(snapshot.id),
            {item.batfish_hostname: item.content for item in analysis_input.configs},
            analysis_input.layer1_edges,
        )
        raw = self._backend.parse_findings(str(snapshot.id))
        raw += topology_drift_findings(
            analysis_input.layer1_edges,
            self._backend.interface_properties(str(snapshot.id)),
        )
        hostname_to_device = {
            item.batfish_hostname: item.device_id for item in analysis_input.configs
        }
        prepared, truncated = to_findings(
            raw,
            hostname_to_device=hostname_to_device,
            max_findings=self._settings.analysis_max_findings,
        )
        self._analysis.add_findings(snapshot, prepared)
        snapshot.findings_truncated = truncated
        self._analysis.set_status(snapshot, AnalysisStatus.READY)

        self._events.record(
            event_type="analysis.completed",
            message="Read-only configuration analysis completed",
            details={
                "analysis_snapshot_id": str(snapshot.id),
                "analysed_device_count": len(analysis_input.configs),
                "excluded_device_count": len(analysis_input.excluded),
                "observed_link_count": len(analysis_input.layer1_edges),
                "finding_count": len(prepared),
                "evidence": "INFERRED",
            },
        )
        self._analysis.prune(keep=self._settings.analysis_retained_snapshots)
        return {
            "analysis_snapshot_id": str(snapshot.id),
            "analysed_device_count": len(analysis_input.configs),
            "finding_count": len(prepared),
        }

    def completeness(self, snapshot: AnalysisSnapshot) -> CompletenessView:
        members = self._analysis.list_members(snapshot.id)
        counts: Counter[ExclusionReason] = Counter(
            member.exclusion_reason for member in members if member.exclusion_reason is not None
        )
        return CompletenessView(
            registered_device_count=len(members),
            analysed_device_count=snapshot.device_count,
            observed_link_count=snapshot.observed_link_count,
            exclusions=[
                ExclusionView(reason=reason, count=count)
                for reason, count in sorted(counts.items())
            ],
            oldest_config_at=snapshot.oldest_config_at,
            newest_config_at=snapshot.newest_config_at,
        )

    def _hostname_for(self, snapshot: AnalysisSnapshot, device_id: UUID) -> str:
        for member in self._analysis.list_members(snapshot.id):
            if member.device_id == device_id and member.batfish_hostname is not None:
                return member.batfish_hostname
        raise NotFoundError("That device is not part of this analysis snapshot")

    def _mark_expired(self, snapshot: AnalysisSnapshot) -> None:
        self._analysis.set_status(snapshot, AnalysisStatus.EXPIRED)
        self._session.commit()

    def path_check(
        self, analysis_snapshot_id: UUID, *, source_device_id: UUID, destination_ip: str
    ) -> tuple[TraceResult, CompletenessView]:
        snapshot = self._analysis.get(analysis_snapshot_id)
        hostname = self._hostname_for(snapshot, source_device_id)
        result = self._query(
            snapshot,
            lambda: self._backend.traceroute(str(snapshot.id), hostname, destination_ip),
            "path_check",
            {"source_device_id": str(source_device_id), "destination_ip": destination_ip},
        )
        return result, self.completeness(snapshot)

    def filter_check(
        self,
        analysis_snapshot_id: UUID,
        *,
        device_id: UUID,
        filter_name: str,
        destination_ip: str,
        protocol: str,
        destination_port: int | None,
    ) -> tuple[FilterVerdict, CompletenessView]:
        snapshot = self._analysis.get(analysis_snapshot_id)
        hostname = self._hostname_for(snapshot, device_id)
        verdict = self._query(
            snapshot,
            lambda: self._backend.test_filter(
                str(snapshot.id),
                hostname,
                filter_name,
                destination_ip,
                protocol,
                destination_port,
            ),
            "filter_check",
            {
                "device_id": str(device_id),
                "filter_name": filter_name,
                "destination_ip": destination_ip,
                "protocol": protocol,
            },
        )
        return verdict, self.completeness(snapshot)

    def _query(
        self,
        snapshot: AnalysisSnapshot,
        run: Callable[[], _QueryResultT],
        query_type: str,
        parameters: dict[str, str],
    ) -> _QueryResultT:
        """Run one interactive query, handling expiry and auditing identically.

        Both query kinds must mark the snapshot expired if Batfish has lost it,
        and must audit only on success, so the ordering lives here once.
        """
        try:
            result = run()
        except AnalysisSnapshotExpiredError:
            self._mark_expired(snapshot)
            raise
        self._audit_query(snapshot, query_type, parameters)
        return result

    def _audit_query(
        self, snapshot: AnalysisSnapshot, query_type: str, parameters: dict[str, str]
    ) -> None:
        """Record that a query was asked, not what it returned.

        Query results are ephemeral by design; auditing the question keeps the
        trail complete without storing analysis output.
        """
        self._events.record(
            event_type="analysis.query",
            message="Read-only analysis query executed",
            details={
                "analysis_snapshot_id": str(snapshot.id),
                "query_type": query_type,
                "evidence": "INFERRED",
                **parameters,
            },
        )
        self._session.commit()
