"""Classification labels shared across every module.

Referenced by NOTICE.md and every module's classification/need-to-know
enforcement (Module 7 §21, Module 8 §10, Module 9 §16, Module 10 §15). This
enum defines the label vocabulary only — enforcement logic belongs to
Module 5 (Authorization) and is implemented starting EPIC-03.
"""

from enum import Enum


class Classification(str, Enum):
    """Government-style classification labels used platform-wide."""

    UNCLASSIFIED = "UNCLASSIFIED"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    SECRET = "SECRET"
