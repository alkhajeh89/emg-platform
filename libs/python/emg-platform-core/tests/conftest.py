"""Shared test setup for emg-platform-core.

Under pytest's importlib mode, sibling test modules cannot ``import conftest``;
reusable graph constructors therefore live in ``_pc_helpers.py``, placed on
``sys.path`` here (uniquely named to avoid collision with other packages'
``_helpers``/``_mg_helpers`` modules).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
