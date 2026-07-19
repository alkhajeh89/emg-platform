"""Shared test setup for emg-persistence.

Under pytest's importlib mode, sibling test modules cannot ``import conftest``;
reusable helpers therefore live in ``_migr_helpers.py``, placed on ``sys.path``
here (uniquely named to avoid collision with other packages' helpers).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
