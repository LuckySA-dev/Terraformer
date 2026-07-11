from __future__ import annotations

from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from app.core.logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    connection = Redis.from_url(settings.resolved_redis_url())
    queue = Queue(settings.rq_queue_name, connection=connection)
    worker = Worker([queue], connection=connection)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()

