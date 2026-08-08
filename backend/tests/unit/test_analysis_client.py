from __future__ import annotations

import sys

import pytest

from app.analysis.client import build_backend
from app.core.config import Settings
from app.core.errors import AnalysisUnavailableError


def test_missing_pybatfish_fails_closed_with_a_typed_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Analysis becomes unavailable; the application must still run."""
    monkeypatch.setitem(sys.modules, "pybatfish", None)
    monkeypatch.setitem(sys.modules, "pybatfish.client.session", None)

    with pytest.raises(AnalysisUnavailableError) as raised:
        build_backend(settings)

    assert raised.value.code == "analysis_unavailable"
    assert "pybatfish" not in raised.value.message.lower()
