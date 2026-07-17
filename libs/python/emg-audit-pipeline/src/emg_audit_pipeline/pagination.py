"""Opaque keyset-pagination cursors for the audit + custody query surfaces
(FEAT-04-4, Sprint 8).

A cursor encodes the position of the last row a caller has already seen, keyed
on the store's server-assigned monotonic sequence (`sequence_number` for audit
events, `chain_sequence` for custody events). The next page returns only rows
strictly after that sequence, ordered ascending. Because the sequence is unique
and monotonically increasing, this keyset (not offset) approach guarantees a
stable ordering across pages with **no duplicates and no skipped records**, even
as new rows are appended between page reads.

The token is deliberately opaque (base64url of a versioned string) so callers
treat it as a handle and do not construct or depend on its internal form. A
malformed token is rejected as a `ValidationError` (`CURSOR_INVALID`) rather
than silently ignored — an ignored cursor would risk re-scanning from the start
and returning duplicates.
"""

from __future__ import annotations

import base64
import binascii

from emg_errors import ValidationError

# Versioned prefix so the token format can evolve without ambiguity.
_CURSOR_SCHEME = "seq:v1:"


def encode_cursor(sequence: int) -> str:
    """Encode a monotonic sequence position into an opaque pagination token."""
    raw = f"{_CURSOR_SCHEME}{int(sequence)}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(token: str) -> int:
    """Decode an opaque pagination token back to its sequence position.

    Raises `ValidationError(CURSOR_INVALID)` for any token that was not produced
    by `encode_cursor` (bad base64, wrong scheme, or a non-integer / negative
    position), so a bad cursor becomes an HTTP 400 rather than a silent
    full-table re-scan or a 500.
    """
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, UnicodeEncodeError, ValueError) as exc:
        raise ValidationError(
            "pagination cursor is malformed", error_code="CURSOR_INVALID"
        ) from exc
    if not decoded.startswith(_CURSOR_SCHEME):
        raise ValidationError("pagination cursor is malformed", error_code="CURSOR_INVALID")
    position = decoded[len(_CURSOR_SCHEME) :]
    if not position.isdigit():
        raise ValidationError("pagination cursor is malformed", error_code="CURSOR_INVALID")
    return int(position)
