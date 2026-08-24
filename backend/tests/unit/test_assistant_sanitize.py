from __future__ import annotations

from app.assistant.sanitize import scrub_secrets


def test_scrub_secrets_removes_credential_shaped_keys() -> None:
    payload = {
        "facts": {"hostname": "r1"},
        "encrypted_secret": "abc",
        "nested": {"api_key": "xyz", "ok": 1},
    }
    assert scrub_secrets(payload) == {"facts": {"hostname": "r1"}, "nested": {"ok": 1}}


def test_scrub_secrets_handles_lists_and_scalars() -> None:
    assert scrub_secrets([{"password": "x", "name": "a"}]) == [{"name": "a"}]
    assert scrub_secrets("plain string") == "plain string"
    assert scrub_secrets(42) == 42


def test_scrub_secrets_is_case_insensitive() -> None:
    assert scrub_secrets({"API_Key": "x", "Token": "y", "ok": 1}) == {"ok": 1}
