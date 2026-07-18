"""Bound constants for emg-platform-core value types.

Mirrors the per-package limits convention used across the EMG libraries
(``emg_memory_graph.limits`` etc.). Bounds keep identifier/label inputs finite
so validation is cheap and denial-of-service via unbounded strings is not
possible.
"""

from __future__ import annotations

MAX_LABEL_LENGTH = 512
MAX_TEXT_LENGTH = 8192
