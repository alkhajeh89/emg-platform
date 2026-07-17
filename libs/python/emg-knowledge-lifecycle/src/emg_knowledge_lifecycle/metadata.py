"""Version metadata (FEAT-05-5).

`VersionMetadata` is the immutable descriptive envelope attached to a version:
when it was created, who authored it, and an optional human-readable note. It
carries no trust value and no persistence handle — it is pure data. `created_at`
is an explicit timestamp (never a wall-clock read), so lifecycle evaluation is
reproducible.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .labels import SafeLabel, SafeText


class VersionMetadata(BaseModel):
    """Immutable descriptive metadata for a knowledge version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    created_at: datetime
    author: SafeLabel
    note: SafeText | None = None
