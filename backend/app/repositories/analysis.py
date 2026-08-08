from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis.findings import PreparedFinding
from app.core.errors import NotFoundError
from app.models import (
    AnalysisFinding,
    AnalysisSnapshot,
    AnalysisSnapshotMember,
    AnalysisStatus,
    ExclusionReason,
    FindingCategory,
)


class AnalysisRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self) -> AnalysisSnapshot:
        snapshot = AnalysisSnapshot(status=AnalysisStatus.PENDING)
        self._session.add(snapshot)
        self._session.flush()
        return snapshot

    def get(self, snapshot_id: UUID, *, for_update: bool = False) -> AnalysisSnapshot:
        statement = select(AnalysisSnapshot).where(AnalysisSnapshot.id == snapshot_id)
        if for_update:
            statement = statement.with_for_update()
        snapshot = self._session.scalars(statement).one_or_none()
        if snapshot is None:
            raise NotFoundError("The requested analysis snapshot was not found")
        return snapshot

    def latest(self) -> AnalysisSnapshot | None:
        return self._session.scalars(
            select(AnalysisSnapshot).order_by(AnalysisSnapshot.created_at.desc()).limit(1)
        ).one_or_none()

    def list(self, *, limit: int = 20) -> list[AnalysisSnapshot]:
        return list(
            self._session.scalars(
                select(AnalysisSnapshot)
                .order_by(AnalysisSnapshot.created_at.desc())
                .limit(limit)
            )
        )

    def set_status(
        self,
        snapshot: AnalysisSnapshot,
        status: AnalysisStatus,
        *,
        failure_code: str | None = None,
    ) -> None:
        snapshot.status = status
        snapshot.failure_code = failure_code

    def record_scope(
        self,
        snapshot: AnalysisSnapshot,
        *,
        device_count: int,
        observed_link_count: int,
        oldest_config_at: datetime | None,
        newest_config_at: datetime | None,
    ) -> None:
        snapshot.device_count = device_count
        snapshot.observed_link_count = observed_link_count
        snapshot.oldest_config_at = oldest_config_at
        snapshot.newest_config_at = newest_config_at

    def add_member(
        self,
        snapshot: AnalysisSnapshot,
        *,
        device_id: UUID,
        config_snapshot_id: UUID | None,
        batfish_hostname: str | None,
        exclusion_reason: ExclusionReason | None,
    ) -> None:
        self._session.add(
            AnalysisSnapshotMember(
                analysis_snapshot_id=snapshot.id,
                device_id=device_id,
                config_snapshot_id=config_snapshot_id,
                batfish_hostname=batfish_hostname,
                exclusion_reason=exclusion_reason,
            )
        )

    def list_members(self, snapshot_id: UUID) -> list[AnalysisSnapshotMember]:
        return list(
            self._session.scalars(
                select(AnalysisSnapshotMember).where(
                    AnalysisSnapshotMember.analysis_snapshot_id == snapshot_id
                )
            )
        )

    def add_findings(
        self, snapshot: AnalysisSnapshot, findings: Sequence[PreparedFinding]
    ) -> None:
        for finding in findings:
            self._session.add(
                AnalysisFinding(
                    analysis_snapshot_id=snapshot.id,
                    category=finding.category,
                    severity=finding.severity,
                    device_id=finding.device_id,
                    structure_type=finding.structure_type,
                    structure_name=finding.structure_name,
                    detail=finding.detail,
                    line_number=finding.line_number,
                )
            )
        snapshot.parse_warning_count = sum(
            1 for item in findings if item.category is FindingCategory.PARSE_WARNING
        )

    def list_findings(
        self,
        snapshot_id: UUID,
        *,
        category: FindingCategory | None = None,
        device_id: UUID | None = None,
    ) -> list[AnalysisFinding]:
        statement = select(AnalysisFinding).where(
            AnalysisFinding.analysis_snapshot_id == snapshot_id
        )
        if category is not None:
            statement = statement.where(AnalysisFinding.category == category)
        if device_id is not None:
            statement = statement.where(AnalysisFinding.device_id == device_id)
        return list(self._session.scalars(statement))

    def prune(self, *, keep: int) -> int:
        """Delete all but the newest `keep` snapshots; findings cascade."""
        keep_ids = list(
            self._session.scalars(
                select(AnalysisSnapshot.id)
                .order_by(AnalysisSnapshot.created_at.desc())
                .limit(keep)
            )
        )
        if not keep_ids:
            return 0
        result = self._session.execute(
            delete(AnalysisSnapshot).where(AnalysisSnapshot.id.notin_(keep_ids))
        )
        return int(result.rowcount or 0)
