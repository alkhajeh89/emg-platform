"""Version + compatibility tests (FEAT-13-1)."""

from __future__ import annotations

import pytest
from emg_connectors import FRAMEWORK_VERSION, Version, VersionRange
from pydantic import ValidationError


def test_parse_and_str() -> None:
    v = Version.parse("1.2.3")
    assert (v.major, v.minor, v.patch) == (1, 2, 3)
    assert str(v) == "1.2.3"


def test_parse_rejects_bad() -> None:
    for bad in ("1.2", "1.2.3.4", "a.b.c", "1.2.x", "", "v1.0.0", "1.2.-1"):
        with pytest.raises(ValueError):
            Version.parse(bad)


def test_ordering() -> None:
    assert Version.parse("1.0.0") < Version.parse("1.0.1")
    assert Version.parse("1.2.0") <= Version.parse("1.2.0")
    assert Version.parse("2.0.0") > Version.parse("1.9.9")


def test_is_compatible_with() -> None:
    assert Version.parse("1.4.0").is_compatible_with(Version.parse("1.2.0"))
    assert not Version.parse("1.1.0").is_compatible_with(Version.parse("1.2.0"))  # older
    assert not Version.parse("2.0.0").is_compatible_with(Version.parse("1.2.0"))  # major diff


def test_range_contains() -> None:
    r = VersionRange(minimum=Version.parse("1.0.0"), maximum=Version.parse("2.0.0"))
    assert r.contains(Version.parse("1.5.0"))
    assert r.contains(Version.parse("1.0.0"))
    assert r.contains(Version.parse("2.0.0"))
    assert not r.contains(Version.parse("2.0.1"))
    assert not r.contains(Version.parse("0.9.0"))


def test_open_ended_range() -> None:
    r = VersionRange(minimum=Version.parse("1.0.0"))
    assert r.contains(Version.parse("99.0.0"))
    assert not r.contains(Version.parse("0.1.0"))


def test_range_rejects_inverted() -> None:
    with pytest.raises(ValidationError):
        VersionRange(minimum=Version.parse("2.0.0"), maximum=Version.parse("1.0.0"))


def test_version_is_immutable() -> None:
    with pytest.raises(ValidationError):
        FRAMEWORK_VERSION.major = 9
