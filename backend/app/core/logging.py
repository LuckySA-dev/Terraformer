from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any, cast

import structlog

_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:authorization|cookie|credential|pass(?:word)?|secret|token|api_?key|"
    r"private_?key|enable_?password|community|snmp_?community)(?:$|_)",
    re.IGNORECASE,
)
_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)(\b(?:password|secret|community|auth-token|token|api[-_ ]?key)\s+"
        r"(?:\d+\s+)?)(\S+)"
    ),
    re.compile(r"(?i)(\b(?:authorization\s*:\s*bearer)\s+)(\S+)"),
    re.compile(r"(?i)(https?://[^\s:/]+:)([^@\s]+)(@)"),
)
_REDACTED = "[REDACTED]"


def sanitize_text(value: str) -> str:
    sanitized = value
    for pattern in _TEXT_PATTERNS:
        if pattern.groups == 3:
            sanitized = pattern.sub(rf"\1{_REDACTED}\3", sanitized)
        else:
            sanitized = pattern.sub(rf"\1{_REDACTED}", sanitized)
    return sanitized


def redact_value(value: Any, *, key: str | None = None) -> Any:
    if key is not None and _SENSITIVE_KEY.search(key):
        return _REDACTED
    if isinstance(value, BaseException):
        return _REDACTED
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            str(item_key): redact_value(item, key=str(item_key))
            for item_key, item in mapping.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        sequence = cast(Sequence[object], value)
        return [redact_value(item) for item in sequence]
    return value


def redaction_processor(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    return {key: redact_value(value, key=key) for key, value in event_dict.items()}


def _sanitize_exception_info(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    has_exception = bool(event_dict.pop("exc_info", None))
    if has_exception or "exception" in event_dict:
        event_dict["exception"] = _REDACTED
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric_level, force=True)
    scrapli_logger = logging.getLogger("scrapli")
    scrapli_logger.handlers.clear()
    scrapli_logger.addHandler(logging.NullHandler())
    scrapli_logger.propagate = False
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    structlog.configure(
        processors=[
            *shared_processors,
            _sanitize_exception_info,
            structlog.processors.format_exc_info,
            redaction_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
