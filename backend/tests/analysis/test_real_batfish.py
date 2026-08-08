"""Opt-in test against a real Batfish container.

Run with the analysis profile up:

    docker compose --env-file .env -f deploy/compose.yml \
      -f deploy/compose.analysis.yml --profile analysis up --detach --wait

    RUN_ANALYSIS_TESTS=1 BATFISH_HOST=127.0.0.1 BATFISH_PORT=9996 \
      .venv/Scripts/python.exe -m pytest tests/analysis -v --basetemp=<scratch>

This is the evidence that Batfish parses configuration captured by this
application. Fixture-based tests cannot establish that.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.analysis.client import build_backend
from app.analysis.snapshot_builder import batfish_hostname
from app.core.config import Settings

pytestmark = pytest.mark.analysis

_ENABLED = os.environ.get("RUN_ANALYSIS_TESTS") == "1"


@pytest.mark.skipif(not _ENABLED, reason="Set RUN_ANALYSIS_TESTS=1 to enable")
def test_batfish_parses_a_snapshot_captured_by_this_application(settings: Settings) -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "cisco_iosxe" / "running_config.txt"
    config = fixture.read_text(encoding="utf-8")
    hostname = batfish_hostname(config, fallback="fixture-device")
    backend = build_backend(settings)

    backend.init_snapshot("terraformer-optin", {hostname: config}, [])

    assert backend.snapshot_exists("terraformer-optin")
    findings = backend.parse_findings("terraformer-optin")
    unparsed = [
        item
        for item in findings
        if item.category.value == "parse_warning" and "cannot" in item.detail.lower()
    ]
    assert not unparsed, f"Batfish could not parse the configuration: {unparsed[:3]}"

    properties = backend.interface_properties("terraformer-optin")
    assert properties, "Batfish parsed no interfaces from the configuration"
