from __future__ import annotations

from app.jobs import queue as queue_module
from app.jobs.queue import RQJobQueue


def test_worker_health_uses_queue_specific_registry(monkeypatch) -> None:
    redis = object()
    queue = object()
    job_queue = object.__new__(RQJobQueue)
    job_queue._redis = redis
    job_queue._queue = queue
    calls: list[dict[str, object]] = []

    def workers(**kwargs: object) -> list[object]:
        calls.append(kwargs)
        return [object()]

    monkeypatch.setattr(queue_module.Worker, "all", workers)

    assert job_queue.has_workers() is True
    assert calls == [{"connection": redis, "queue": queue}]


def test_worker_health_fails_closed_when_registry_is_unavailable(monkeypatch) -> None:
    job_queue = object.__new__(RQJobQueue)
    job_queue._redis = object()
    job_queue._queue = object()

    def unavailable(**_kwargs: object) -> list[object]:
        raise ConnectionError

    monkeypatch.setattr(queue_module.Worker, "all", unavailable)

    assert job_queue.has_workers() is False


def test_rq_payload_contains_only_the_opaque_job_id() -> None:
    class QueueSpy:
        def __init__(self) -> None:
            self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def enqueue(self, *args: object, **kwargs: object):
            self.calls.append((args, kwargs))
            return type("RQJob", (), {"id": "rq-opaque"})()

    queue = QueueSpy()
    job_queue = object.__new__(RQJobQueue)
    job_queue._redis = object()
    job_queue._queue = queue
    job = type("Job", (), {"id": "2ad0db14-5a87-4147-a4e7-c98f88322464"})()

    assert job_queue.enqueue(job) == "rq-opaque"
    assert queue.calls == [
        (
            (
                "app.jobs.tasks.execute_job",
                "2ad0db14-5a87-4147-a4e7-c98f88322464",
            ),
            {"job_timeout": 900, "result_ttl": 86_400, "failure_ttl": 604_800},
        )
    ]
