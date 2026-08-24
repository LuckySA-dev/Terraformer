from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import NotFoundError
from app.models import (
    ChangePlan,
    ChangePlanSource,
    ChangePlanStatus,
    ChangeRisk,
    ChangeStep,
    ChangeType,
    SafetyLevel,
)


class ChangeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        device_id: UUID,
        safety_level: SafetyLevel,
        risk: ChangeRisk,
        source: ChangePlanSource = ChangePlanSource.MANUAL,
    ) -> ChangePlan:
        plan = ChangePlan(
            device_id=device_id,
            status=ChangePlanStatus.DRAFT,
            safety_level=safety_level,
            risk=risk,
            source=source,
        )
        self._session.add(plan)
        self._session.flush()
        return plan

    def add_step(
        self,
        plan: ChangePlan,
        *,
        change_type: ChangeType,
        target: str,
        previous_value: str | None,
        desired_value: str,
        rendered_commands: str,
        inverse_commands: str,
    ) -> ChangeStep:
        step = ChangeStep(
            change_plan_id=plan.id,
            change_type=change_type,
            target=target,
            previous_value=previous_value,
            desired_value=desired_value,
            rendered_commands=rendered_commands,
            inverse_commands=inverse_commands,
        )
        self._session.add(step)
        self._session.flush()
        return step

    def get(self, plan_id: UUID, *, for_update: bool = False) -> ChangePlan:
        statement = (
            select(ChangePlan)
            .where(ChangePlan.id == plan_id)
            .options(selectinload(ChangePlan.steps))
        )
        if for_update:
            statement = statement.with_for_update()
        plan = self._session.scalars(statement).one_or_none()
        if plan is None:
            raise NotFoundError("The requested change plan was not found")
        return plan

    def list_by_device(self, device_id: UUID, *, limit: int = 50) -> list[ChangePlan]:
        statement = (
            select(ChangePlan)
            .where(ChangePlan.device_id == device_id)
            .options(selectinload(ChangePlan.steps))
            .order_by(ChangePlan.created_at.desc())
            .limit(limit)
        )
        return list(self._session.scalars(statement))

    def set_status(
        self,
        plan: ChangePlan,
        status: ChangePlanStatus,
        *,
        failure_code: str | None = None,
    ) -> None:
        plan.status = status
        if failure_code is not None:
            plan.failure_code = failure_code

    def set_snapshots(
        self,
        plan: ChangePlan,
        *,
        pre_change_snapshot_id: UUID | None = None,
        post_change_snapshot_id: UUID | None = None,
    ) -> None:
        if pre_change_snapshot_id is not None:
            plan.pre_change_snapshot_id = pre_change_snapshot_id
        if post_change_snapshot_id is not None:
            plan.post_change_snapshot_id = post_change_snapshot_id
