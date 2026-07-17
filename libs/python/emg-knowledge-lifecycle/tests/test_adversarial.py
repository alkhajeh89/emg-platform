"""Adversarial tests (FEAT-05-5): identifier/label hardening, bounds, immutability,
malformed-model rejection, decision-forgery boundary, and determinism."""

from __future__ import annotations

from datetime import datetime, timezone

import emg_knowledge_lifecycle as kl
import pytest
from emg_knowledge_lifecycle import (
    ArchiveDecision,
    ChainIssueKind,
    KnowledgeVersion,
    LifecyclePolicy,
    LifecycleValidator,
    RetentionPolicy,
    VersionIdentifier,
    VersionMetadata,
    VersionState,
)
from emg_knowledge_lifecycle.limits import (
    MAX_CHAIN_SIZE,
    MAX_RETENTION_DAYS,
    MAX_VERSION_NUMBER,
)
from pydantic import ValidationError

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
META = VersionMetadata(created_at=T0, author="svc")

_UNSAFE = {
    "NUL": "a\x00b",
    "control": "a\x01b",
    "newline": "a\nb",
    "carriage-return": "a\rb",
    "bidi-RLO": "a‮b",
    "bidi-LRI": "a⁦b",
    "whitespace-only": "   ",
    "empty": "",
}


# --- identifier / label validation ------------------------------------------


@pytest.mark.parametrize("bad", list(_UNSAFE.values()), ids=list(_UNSAFE))
def test_entity_id_rejects_unsafe(bad: str) -> None:
    with pytest.raises(ValidationError):
        VersionIdentifier(entity_id=bad, version=1)


@pytest.mark.parametrize("bad", list(_UNSAFE.values()), ids=list(_UNSAFE))
def test_metadata_author_rejects_unsafe(bad: str) -> None:
    with pytest.raises(ValidationError):
        VersionMetadata(created_at=T0, author=bad)


def test_metadata_note_rejects_control() -> None:
    with pytest.raises(ValidationError):
        VersionMetadata(created_at=T0, author="svc", note="bad\x00note")


def test_legit_unicode_labels_preserved() -> None:
    for label in ("مؤسسة", "Café", "组织", "ent-Zürich_1"):
        assert VersionIdentifier(entity_id=label, version=1).entity_id == label


def test_ensure_safe_label_exported() -> None:
    assert kl.ensure_safe_label("ok-1") == "ok-1"
    with pytest.raises(ValueError):
        kl.ensure_safe_label("x\x00")


# --- numeric bounds ---------------------------------------------------------


def test_extreme_version_number_rejected() -> None:
    with pytest.raises(ValidationError):
        VersionIdentifier(entity_id="ent-a", version=MAX_VERSION_NUMBER + 1)
    with pytest.raises(ValidationError):
        VersionIdentifier(entity_id="ent-a", version=10**18)


def test_retention_policy_rejects_extreme_days() -> None:
    with pytest.raises(ValidationError):
        RetentionPolicy(retain_superseded_days=MAX_RETENTION_DAYS + 1)
    with pytest.raises(ValidationError):
        RetentionPolicy(archive_after_days=-1)


def test_chain_too_large_reported() -> None:
    # Build a lightweight oversized set via model_construct (fast; validate_chain
    # iterates directly) and confirm the size bound is reported.
    versions = tuple(
        KnowledgeVersion.model_construct(
            identifier=VersionIdentifier(entity_id="ent-a", version=i + 1),
            state=VersionState.PROPOSED,
            metadata=META,
            parent=None,
            effective_from=T0,
            effective_to=None,
        )
        for i in range(MAX_CHAIN_SIZE + 1)
    )
    kinds = {i.kind for i in LifecycleValidator.validate_chain(versions).issues}
    assert ChainIssueKind.TOO_LARGE in kinds


# --- immutability -----------------------------------------------------------


def test_decision_models_are_frozen() -> None:
    d = ArchiveDecision(
        version=VersionIdentifier(entity_id="ent-a", version=1), eligible=True, reason="x"
    )
    with pytest.raises(ValidationError):
        d.eligible = False


def test_policy_models_are_frozen() -> None:
    with pytest.raises(ValidationError):
        LifecyclePolicy().allow_restore = False
    with pytest.raises(ValidationError):
        RetentionPolicy().archive_after_days = 5


def test_report_and_issue_are_frozen() -> None:
    report = LifecycleValidator.validate_chain(())
    with pytest.raises(ValidationError):
        report.valid = True


# --- malformed-model rejection + unknown fields -----------------------------


def test_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        VersionIdentifier(entity_id="ent-a", version=1, rogue="x")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        VersionMetadata(created_at=T0, author="svc", rogue="x")  # type: ignore[call-arg]


# --- determinism ------------------------------------------------------------


def test_chain_report_is_deterministic() -> None:
    v1 = KnowledgeVersion(
        identifier=VersionIdentifier(entity_id="ent-a", version=1),
        state=VersionState.ACTIVE,
        metadata=META,
        effective_from=T0,
    )
    r1 = LifecycleValidator.validate_chain((v1,))
    r2 = LifecycleValidator.validate_chain((v1,))
    assert r1.model_dump() == r2.model_dump()
