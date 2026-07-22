import logging

import structlog
from scrapli.exceptions import ScrapliAuthenticationFailed

from app.core.logging import configure_logging, redact_value, sanitize_text


def test_structured_redaction_covers_nested_credentials_and_community() -> None:
    value = {
        "username": "visible-metadata",
        "password": "secret-password",
        "nested": {
            "authorization": "Bearer token-value",
            "snmp_community": "public",
            "community": "private",
        },
    }

    redacted = redact_value(value)

    assert redacted["username"] == "visible-metadata"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["nested"]["authorization"] == "[REDACTED]"
    assert redacted["nested"]["snmp_community"] == "[REDACTED]"
    assert redacted["nested"]["community"] == "[REDACTED]"


def test_text_redaction_covers_cisco_secrets_and_url_passwords() -> None:
    text = (
        "enable secret 9 HASHVALUE\n"
        "snmp-server community public RO\n"
        "https://admin:password@example.invalid/path"
    )
    sanitized = sanitize_text(text)

    assert "HASHVALUE" not in sanitized
    assert "public" not in sanitized
    assert "password" not in sanitized
    assert sanitized.count("[REDACTED]") == 3


def test_exception_traceback_is_redacted_after_rendering(capsys) -> None:
    configure_logging("INFO")
    logger = structlog.get_logger("redaction-test")
    try:
        raise RuntimeError("password hunter2 token abc123 community public")
    except RuntimeError:
        logger.exception("fixture_failure", api_key="key-value")

    output = capsys.readouterr().out
    assert "hunter2" not in output
    assert "abc123" not in output
    assert "public" not in output
    assert "key-value" not in output
    assert output.count("[REDACTED]") >= 4


def test_scrapli_raw_messages_do_not_reach_application_logs(capsys) -> None:
    logging.getLogger("scrapli").handlers.clear()
    configure_logging("INFO")

    logging.getLogger("scrapli.channel").critical("Permission denied raw-scrapli-marker")

    captured = capsys.readouterr()
    assert "raw-scrapli-marker" not in captured.out
    assert "raw-scrapli-marker" not in captured.err


def test_structured_exception_values_are_replaced_before_rendering(capsys) -> None:
    configure_logging("INFO")
    structlog.get_logger("ssh-error-test").error(
        "ssh_failure",
        error=ScrapliAuthenticationFailed(
            "raw-log-marker edge-rtr-01.example.test fixture-password peer-offered-ssh-rsa"
        ),
    )

    output = capsys.readouterr().out
    for prohibited in (
        "raw-log-marker",
        "edge-rtr-01.example.test",
        "fixture-password",
        "peer-offered-ssh-rsa",
        "ScrapliAuthenticationFailed",
    ):
        assert prohibited not in output
