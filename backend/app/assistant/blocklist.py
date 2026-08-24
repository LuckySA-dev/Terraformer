from __future__ import annotations

import re

# Unconditional floor, not mode-gated -- spec
# docs/superpowers/specs/2026-08-24-phase-4-ai-assistant-design.md §2.4,
# mirroring docs/network-automation-final-plan.md §7's "Wizard/AI block
# คำสั่ง erase, reload, format และ factory reset" with no Auto-mode
# exception. Applies only to AI-suggested commands staged through this
# module -- it does not and cannot restrict what a human freely types into
# an already-open Direct Mode terminal on their own initiative.
_BLOCKED_PATTERNS = (
    re.compile(r"\berase\b", re.IGNORECASE),
    re.compile(r"\breload\b", re.IGNORECASE),
    re.compile(r"\bformat\b", re.IGNORECASE),
    re.compile(r"\bfactory[\s-]?reset\b", re.IGNORECASE),
)


def contains_blocked_command(text: str) -> bool:
    return any(pattern.search(text) for pattern in _BLOCKED_PATTERNS)
