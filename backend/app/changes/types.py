"""Pure, driver-agnostic value types for the change pipeline.

No I/O, no database session, no vendor knowledge -- keeps the pipeline's
shape testable without a device or a container.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import ChangeType


@dataclass(frozen=True, slots=True)
class ChangeStepIntent:
    """What the operator asked for, before rendering.

    Mirrors ChangeStep's pre-render fields as a plain in-memory value --
    not yet persisted, not yet rendered.
    """

    change_type: ChangeType
    target: str
    desired_value: str


@dataclass(frozen=True, slots=True)
class RenderedChange:
    commands: tuple[str, ...]
    inverse_commands: tuple[str, ...]
