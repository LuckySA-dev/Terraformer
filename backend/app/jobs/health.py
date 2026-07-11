from __future__ import annotations

from app.container import get_default_container


def main() -> None:
    queue = get_default_container().queue
    if not queue.ping() or not queue.has_workers():
        raise SystemExit(1)


if __name__ == "__main__":
    main()

