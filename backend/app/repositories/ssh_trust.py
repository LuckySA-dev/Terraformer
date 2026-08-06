from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DriverHostKeyUnknownError
from app.core.time import utc_now
from app.models import DeviceSSHHostKey
from app.services.ssh_trust import ResolvedHostKeyCandidate


class DeviceSSHHostKeyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def require(self, device_id: UUID) -> DeviceSSHHostKey:
        record = self._session.scalar(
            select(DeviceSSHHostKey).where(DeviceSSHHostKey.device_id == device_id)
        )
        if record is None:
            raise DriverHostKeyUnknownError(details={"phase": "host_key_verification"})
        return record

    def add(self, device_id: UUID, candidate: ResolvedHostKeyCandidate) -> DeviceSSHHostKey:
        record = DeviceSSHHostKey(
            device_id=device_id,
            algorithm=candidate.algorithm,
            public_key=candidate.public_key,
            fingerprint=candidate.fingerprint,
            confirmed_at=utc_now(),
            confirmed_by="local-admin",
        )
        self._session.add(record)
        self._session.flush()
        return record

    def replace(self, device_id: UUID, candidate: ResolvedHostKeyCandidate) -> DeviceSSHHostKey:
        record = self.require(device_id)
        record.algorithm = candidate.algorithm
        record.public_key = candidate.public_key
        record.fingerprint = candidate.fingerprint
        record.confirmed_at = utc_now()
        record.confirmed_by = "local-admin"
        self._session.flush()
        return record
