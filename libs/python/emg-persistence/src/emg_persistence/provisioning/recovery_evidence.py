"""ADR-043 Amendment 1 A9.3 database-session fence and CNI egress-enforcement
qualification evidence contracts.

Round-2 remediation: both were previously either prose-only (A9.3's "the
specific command is an implementation detail" was read, incorrectly, as
"no positive-evidence mechanism is required") or comment-only (the CNI
egress-enforcement prerequisite). Neither had an executable, checkable
positive-evidence mechanism. This module adds both, without inventing a new
platform component: the database-session fence reuses the existing governed
database-bootstrap-administrator credential (already established by ADR-041,
D-8) rather than granting the constrained `emg_identity_migrator`/
`emg_identity_app` roles any new privilege or role membership that would
violate D-2's NOSUPERUSER/no-membership contract; the CNI qualification
contract is a schema-and-freshness evidence file only -- it does not, and
cannot, perform a live packet-level enforcement test from this repository.

Round-3 remediation: A11 requires Stage-50, during a recovery qualification,
to confirm that A9 evidence records "exist and are attributable to the fence
owner for the recovery being validated." Neither evidence type compared its
required, non-empty `verified_by` field against anything -- any non-empty
value passed. Both :func:`validate_session_fence_evidence` and
:func:`validate_cni_egress_qualification_evidence` now accept an optional
`expected_owner`; when supplied (Stage-50 recovery qualification always
supplies it, using the same single expected owner for every A9 evidence type
in one recovery -- this repository defines no distinct "CNI verifier" role
separate from the fence owner: the writer scripts for all three evidence
types already take the same `EMG_IDENTITY_RECOVERY_FENCE_ACTOR`/
`EMG_RECOVERY_FENCE_ACTOR` input), a blank expected value or a mismatch is
denied. Database-session and CNI-qualification evidence carry no Kubernetes
namespace (a PostgreSQL session and a cluster-wide CNI enforcement property
are not namespace-scoped), so no namespace check is added here -- see
`recovery_fence.py` for the one evidence type that does carry one.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import GOVERNED_DATABASE_ROLES

#: pg_terminate_backend only sends SIGTERM; the signaled backend exits
#: asynchronously. Poll for up to 5 seconds (50 x 100ms) before concluding a
#: survivor is genuinely un-terminatable, rather than racing a single
#: immediate re-query against normal backend teardown latency.
_SESSION_TERMINATION_POLL_ATTEMPTS = 50
_SESSION_TERMINATION_POLL_INTERVAL_SECONDS = 0.1


class SessionFenceEvidenceDenied(Exception):
    """A9.3 database-session-fence evidence is missing, malformed,
    wrong-target, stale, or the live check proved surviving sessions."""


class CniQualificationEvidenceDenied(Exception):
    """CNI egress-enforcement qualification evidence is missing, malformed,
    wrong-target, or stale."""


def _parse_timestamp(value: object, denied: type[Exception]) -> datetime:
    if not isinstance(value, str) or not value:
        raise denied("evidence verified_at is missing or malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise denied("evidence verified_at is not valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise denied("evidence verified_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _require_nonempty_str(payload: dict[str, Any], field: str, denied: type[Exception]) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise denied(f"evidence is missing required field: {field}")
    return value


def _check_freshness(
    verified_at: datetime,
    *,
    max_age_seconds: float,
    now: datetime | None,
    denied: type[Exception],
) -> None:
    current_time = now if now is not None else datetime.now(timezone.utc)
    if verified_at > current_time:
        raise denied("evidence verified_at is in the future")
    age = (current_time - verified_at).total_seconds()
    if age > max_age_seconds:
        raise denied(f"evidence is stale ({age:.0f}s old, max {max_age_seconds:.0f}s)")


# --------------------------------------------------------------------------
# A9.3 database-session fence
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionFenceEvidence:
    """Positive evidence that zero PostgreSQL sessions authenticated as
    `emg_identity_app` survive against the recovery target (A9.3)."""

    target_environment: str
    database_host: str
    database_port: str
    database_name: str
    verified_by: str
    verified_at: datetime
    terminated_count: int
    zero_runtime_sessions: bool


def terminate_and_prove_identity_app_sessions_excluded(
    admin_dsn: str,
    *,
    target_environment: str,
    verified_by: str,
    evidence_output: Path,
) -> SessionFenceEvidence:  # pragma: no cover - live PostgreSQL
    """A9.3: identify every PostgreSQL session authenticated as
    `emg_identity_app` against the recovery target, terminate it, re-query to
    prove none survive, and only then write non-secret positive evidence.

    Uses the governed database-bootstrap-administrator credential (D-8) --
    never `emg_identity_app`, and never `emg_identity_migrator` either:
    `pg_terminate_backend` requires superuser or `pg_signal_backend`
    membership (or backend self-ownership) in real PostgreSQL, and granting
    either to `emg_identity_migrator` would violate D-2's NOSUPERUSER/
    no-membership contract and would itself fail the already-passing
    Stage-50 role-membership check in ``database.py``. The administrator
    credential is not one of the two governed, privilege-constrained roles,
    so no existing invariant is weakened.

    A session opened by the reconciliation coordinator itself never appears
    in this result: the filter is on ``usename = 'emg_identity_app'``, and
    the administrator/migrator connections authenticate under different
    role names entirely, so the coordinator's own session is excluded
    structurally, not by an exception list.

    Fails closed (raises without writing evidence) if: the DSN authenticates
    as any of the seven governed runtime/migration roles; any termination
    attempt returns a non-true result; or the post-termination re-query still
    reports a nonzero count. Evidence is written only after every check
    passes.
    """

    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    values = conninfo_to_dict(admin_dsn)
    username = values.get("user", "")
    password = values.get("password", "")
    if not username or username in GOVERNED_DATABASE_ROLES:
        raise SessionFenceEvidenceDenied(
            "database-session fence requires the governed database-bootstrap "
            "administrator credential, not emg_identity_app, "
            "emg_identity_migrator, or any other runtime/migration role"
        )
    if not isinstance(password, str) or not password:
        raise SessionFenceEvidenceDenied("database-session fence DSN must contain a credential")

    # autocommit=True is deliberate, not merely a style choice: the terminate
    # signal and the subsequent poll-until-absent re-queries are sequential,
    # independently-observed reads of live server state (never one atomic
    # unit the way A6 reconciliation is), and each must see the server's
    # current reality rather than whatever a still-open transaction captured
    # at its own start.
    with psycopg.connect(admin_dsn, autocommit=True) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        current_user_row = cursor.fetchone()
        if current_user_row is None or current_user_row[0] in GOVERNED_DATABASE_ROLES:
            raise SessionFenceEvidenceDenied(
                "database-session fence connected as a prohibited governed role"
            )
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE usename = 'emg_identity_app'"
        )
        results = [row[0] for row in cursor.fetchall()]
        if results and not all(results):
            raise SessionFenceEvidenceDenied(
                "one or more emg_identity_app sessions could not be terminated"
            )
        # pg_terminate_backend only sends SIGTERM; it does not block until the
        # signaled backend has actually exited. A single immediate re-query
        # can race a session that is still tearing down. Poll for a bounded
        # window before concluding a survivor is genuinely un-terminatable --
        # still fail closed if the window elapses with a nonzero count.
        remaining_count = None
        for _ in range(_SESSION_TERMINATION_POLL_ATTEMPTS):
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE usename = 'emg_identity_app'"
            )
            remaining_row = cursor.fetchone()
            remaining_count = remaining_row[0] if remaining_row is not None else None
            if remaining_count == 0:
                break
            time.sleep(_SESSION_TERMINATION_POLL_INTERVAL_SECONDS)
        if remaining_count != 0:
            raise SessionFenceEvidenceDenied(
                "emg_identity_app sessions survive after termination; "
                "database-session fence cannot be established"
            )

    verified_at = datetime.now(timezone.utc)
    database_host = str(values.get("host") or "")
    database_port = str(values.get("port") or "")
    database_name = str(values.get("dbname") or "")
    terminated_count = len(results)
    evidence_payload = {
        "target_environment": target_environment,
        "database_host": database_host,
        "database_port": database_port,
        "database_name": database_name,
        "verified_by": verified_by,
        "verified_at": verified_at.isoformat(),
        "terminated_count": terminated_count,
        "zero_runtime_sessions": True,
    }
    evidence_output.write_text(
        json.dumps(evidence_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return SessionFenceEvidence(
        target_environment=target_environment,
        database_host=database_host,
        database_port=database_port,
        database_name=database_name,
        verified_by=verified_by,
        verified_at=verified_at,
        terminated_count=terminated_count,
        zero_runtime_sessions=True,
    )


def load_session_fence_evidence(path: Path) -> SessionFenceEvidence:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SessionFenceEvidenceDenied(f"session-fence evidence file unreadable: {exc}") from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise SessionFenceEvidenceDenied("session-fence evidence file is malformed") from exc
    if not isinstance(payload, dict):
        raise SessionFenceEvidenceDenied("session-fence evidence file is malformed")

    target_environment = _require_nonempty_str(
        payload, "target_environment", SessionFenceEvidenceDenied
    )
    database_host = _require_nonempty_str(payload, "database_host", SessionFenceEvidenceDenied)
    database_port = _require_nonempty_str(payload, "database_port", SessionFenceEvidenceDenied)
    database_name = _require_nonempty_str(payload, "database_name", SessionFenceEvidenceDenied)
    verified_by = _require_nonempty_str(payload, "verified_by", SessionFenceEvidenceDenied)
    verified_at = _parse_timestamp(payload.get("verified_at"), SessionFenceEvidenceDenied)

    zero_runtime_sessions = payload.get("zero_runtime_sessions")
    if zero_runtime_sessions is not True:
        raise SessionFenceEvidenceDenied(
            "session-fence evidence does not prove zero surviving emg_identity_app sessions"
        )
    terminated_count = payload.get("terminated_count")
    if (
        not isinstance(terminated_count, int)
        or isinstance(terminated_count, bool)
        or terminated_count < 0
    ):
        raise SessionFenceEvidenceDenied("session-fence evidence terminated_count is malformed")

    return SessionFenceEvidence(
        target_environment=target_environment,
        database_host=database_host,
        database_port=database_port,
        database_name=database_name,
        verified_by=verified_by,
        verified_at=verified_at,
        terminated_count=terminated_count,
        zero_runtime_sessions=True,
    )


def validate_session_fence_evidence(
    path: Path,
    *,
    expected_target_environment: str,
    expected_owner: str | None = None,
    max_age_seconds: float = 900.0,
    now: datetime | None = None,
) -> SessionFenceEvidence:
    """A9.3 fail-closed gate: raises unless the evidence file proves, as of
    ``now``, zero surviving `emg_identity_app` sessions for the exact
    expected environment, captured no longer ago than ``max_age_seconds``.

    ``expected_owner`` is optional and ``None`` by default. When supplied
    (Stage-50 recovery qualification -- A11 -- always does), it must be a
    non-empty string and must exactly equal the evidence's ``verified_by``;
    otherwise the evidence is denied even though it is otherwise well-formed,
    fresh, and target-matched.
    """

    evidence = load_session_fence_evidence(path)
    if evidence.target_environment != expected_target_environment:
        raise SessionFenceEvidenceDenied(
            "session-fence evidence target_environment does not match the "
            "environment being recovered"
        )
    if expected_owner is not None:
        if not expected_owner:
            raise SessionFenceEvidenceDenied("expected fence owner must not be blank")
        if evidence.verified_by != expected_owner:
            raise SessionFenceEvidenceDenied(
                "session-fence evidence verified_by does not match the expected governed "
                "fence owner for this recovery (A11 attribution check)"
            )
    _check_freshness(
        evidence.verified_at,
        max_age_seconds=max_age_seconds,
        now=now,
        denied=SessionFenceEvidenceDenied,
    )
    return evidence


# --------------------------------------------------------------------------
# CNI egress-enforcement qualification contract
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CniEgressQualificationEvidence:
    """Attestation that the target cluster/network implementation enforces
    Kubernetes `NetworkPolicy` `Egress` semantics, recorded by the
    environment/recovery coordinator (this repository cannot perform a live
    packet-level test of this itself)."""

    target_environment: str
    cluster_identifier: str
    qualification_method: str
    verified_by: str
    verified_at: datetime


def load_cni_egress_qualification_evidence(path: Path) -> CniEgressQualificationEvidence:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CniQualificationEvidenceDenied(
            f"CNI qualification evidence file unreadable: {exc}"
        ) from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise CniQualificationEvidenceDenied(
            "CNI qualification evidence file is malformed"
        ) from exc
    if not isinstance(payload, dict):
        raise CniQualificationEvidenceDenied("CNI qualification evidence file is malformed")

    target_environment = _require_nonempty_str(
        payload, "target_environment", CniQualificationEvidenceDenied
    )
    cluster_identifier = _require_nonempty_str(
        payload, "cluster_identifier", CniQualificationEvidenceDenied
    )
    qualification_method = _require_nonempty_str(
        payload, "qualification_method", CniQualificationEvidenceDenied
    )
    verified_by = _require_nonempty_str(payload, "verified_by", CniQualificationEvidenceDenied)
    verified_at = _parse_timestamp(payload.get("verified_at"), CniQualificationEvidenceDenied)

    return CniEgressQualificationEvidence(
        target_environment=target_environment,
        cluster_identifier=cluster_identifier,
        qualification_method=qualification_method,
        verified_by=verified_by,
        verified_at=verified_at,
    )


def validate_cni_egress_qualification_evidence(
    path: Path,
    *,
    expected_target_environment: str,
    expected_cluster_identifier: str,
    expected_owner: str | None = None,
    max_age_seconds: float = 7_776_000.0,  # 90 days, matching this repository's
    # existing disaster-recovery rehearsal cadence (postgresql-backup-recovery.md).
    now: datetime | None = None,
) -> CniEgressQualificationEvidence:
    """Fail-closed gate: raises unless a CNI egress-enforcement qualification
    record exists for the exact expected environment and cluster, captured
    no longer ago than ``max_age_seconds``. This function validates the
    repository-owned evidence *schema and freshness contract* only -- it
    never claims to have performed, or to prove, actual live packet-level
    enforcement. Whether the recorded qualification is trustworthy is an
    operational/audit concern outside this repository's ability to verify.

    ``expected_owner`` is optional and ``None`` by default. When supplied
    (Stage-50 recovery qualification -- A11 -- always does, using the same
    expected owner as the network- and session-fence checks -- this
    repository does not define a CNI-qualification verifier role distinct
    from the fence owner), it must be a non-empty string and must exactly
    equal the evidence's ``verified_by``.
    """

    evidence = load_cni_egress_qualification_evidence(path)
    if evidence.target_environment != expected_target_environment:
        raise CniQualificationEvidenceDenied(
            "CNI qualification evidence target_environment does not match "
            "the environment being recovered"
        )
    if evidence.cluster_identifier != expected_cluster_identifier:
        raise CniQualificationEvidenceDenied(
            "CNI qualification evidence cluster_identifier does not match " "the target cluster"
        )
    if expected_owner is not None:
        if not expected_owner:
            raise CniQualificationEvidenceDenied("expected fence owner must not be blank")
        if evidence.verified_by != expected_owner:
            raise CniQualificationEvidenceDenied(
                "CNI qualification evidence verified_by does not match the expected "
                "governed fence owner for this recovery (A11 attribution check)"
            )
    _check_freshness(
        evidence.verified_at,
        max_age_seconds=max_age_seconds,
        now=now,
        denied=CniQualificationEvidenceDenied,
    )
    return evidence
