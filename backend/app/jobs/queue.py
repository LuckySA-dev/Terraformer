from __future__ import annotations

from typing import Protocol

from redis import Redis
from rq import Queue, Worker

from app.core.errors import QueueUnavailableError
from app.models import Job


class JobQueue(Protocol):
    def enqueue(self, job: Job) -> str: ...

    def ping(self) -> bool: ...

    def has_workers(self) -> bool: ...


class RQJobQueue:
    def __init__(self, *, redis_url: str, queue_name: str) -> None:
        self._redis: Redis = Redis.from_url(redis_url)
        self._queue = Queue(name=queue_name, connection=self._redis)
        self._queue_name = queue_name

    def enqueue(self, job: Job) -> str:
        try:
            rq_job = self._queue.enqueue(
                "app.jobs.tasks.execute_job",
                str(job.id),
                job_timeout=900,
                result_ttl=86_400,
                failure_ttl=604_800,
            )
        except Exception as exc:
            raise QueueUnavailableError() from exc
        return str(rq_job.id)

    def ping(self) -> bool:
        try:
            return bool(self._redis.ping())
        except Exception:
            return False

    def has_workers(self) -> bool:
        try:
            workers = Worker.all(connection=self._redis)
        except Exception:
            return False
        return any(self._queue_name in worker.queue_names() for worker in workers)

