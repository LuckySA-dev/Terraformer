from __future__ import annotations

from typing import cast

_SECRET_KEY_MARKERS = ("password", "secret", "api_key", "apikey", "token", "encrypted_")


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
