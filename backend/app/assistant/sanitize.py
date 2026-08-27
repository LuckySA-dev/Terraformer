from __future__ import annotations

import re
from typing import cast

_SECRET_KEY_MARKERS = ("password", "secret", "api_key", "apikey", "token", "encrypted_")

# Provider SDKs put the failing request into their exception text, so an error
# surfaced to the operator can carry the key that caused it. Matches the
# common vendor prefixes (sk-, sk-ant-, sk-or-v1-, gsk_, xai-, AIza...) plus
# any long opaque run that follows an auth-ish label.
_SECRET_TEXT_PATTERNS = (
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_\-]{8,}", re.IGNORECASE),
    re.compile(r"\bgsk_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bxai-[A-Za-z0-9_\-]{8,}", re.IGNORECASE),
    re.compile(r"\bAIza[A-Za-z0-9_\-]{10,}"),
    re.compile(
        r"(?i)\b(?:api[-_ ]?key|authorization|bearer|x-api-key)\b\s*[:=]?\s*['\"]?"
        r"([A-Za-z0-9_\-\.]{12,})"
    ),
)

_REDACTED = "[redacted]"


def scrub_secret_text(text: str) -> str:
    """Redacts anything key-shaped from free text before it is shown or logged.

    Used on provider error messages: they are the one place a caller-supplied
    credential can come back out of the SDK and land in front of the operator
    (or in a chat transcript stored on disk).
    """
    for pattern in _SECRET_TEXT_PATTERNS:
        text = pattern.sub(
            lambda match: match.group(0).replace(match.group(1), _REDACTED)
            if match.groups()
            else _REDACTED,
            text,
        )
    return text


def scrub_secrets(payload: object) -> object:
    """Recursively strips any dict key that looks credential-shaped before
    a tool result is serialized into AI context. Defense in depth: every
    read-only tool in app/assistant/tools.py already builds its payload
    from the same APIModel view schemas already served over the public
    REST API (never raw ORM rows or vault-decrypted material), so this
    should never actually find anything on the tools shipped today -- it
    exists to catch a future tool added without that discipline."""
    if isinstance(payload, dict):
        items = cast("dict[str, object]", payload).items()
        return {
            key: scrub_secrets(value) for key, value in items if not _looks_like_secret_key(key)
        }
    if isinstance(payload, list):
        return [scrub_secrets(item) for item in cast("list[object]", payload)]
    return payload


def _looks_like_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)
