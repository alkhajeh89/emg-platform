"""ADR-043 Amendment 1 A9.4/A9.6 network-fence evidence contract.

The PostgreSQL egress control itself is environment-owned (README.md's
"Network boundary" section; standard Kubernetes NetworkPolicy cannot restrict
arbitrary external FQDNs, and the actual ipBlock/port is environment-resolved,
never guessed or hardcoded here). This module does not mutate network state;
it defines the non-secret, target-specific, phase-specific, freshness-bounded,
hash-bound evidence contract that `tools/backup/identity-recovery-fence.sh`
writes after applying and read-back-verifying a phase-scoped NetworkPolicy,
and that Stage-50 recovery-qualification validation (A11) and the recovery
coordinator's A9.6 gate consult before proceeding to the next step. Fail
closed on anything missing, malformed, wrong-phase, wrong-target, stale, or
hash-mismatched -- never "assume fencing" from the passage of time or from a
prior command's exit code alone.

Round-2 remediation (independent review found the round-1 evidence contract
insufficient in two ways):

1. ``spec_sha256`` was captured but never independently recomputed or
   compared, so the field was decorative. The evidence file now embeds the
   canonicalized, security-relevant NetworkPolicy spec itself
   (``policy_spec_canonical``); the validator independently recomputes its
   SHA-256 and rejects any mismatch (:func:`validate_recovery_fence_evidence`),
   then independently re-derives the pod-selector labels and validates the
   embedded egress rules from that same canonical content -- never from a
   flat, separately-asserted label list the writer could have gotten wrong
   without it showing in the hash.
2. Nothing detected a second, broader NetworkPolicy additively granting the
   same PostgreSQL reachability to an Identity-labeled pod (round-1's
   "external-egress.example.yaml" carried a comment-only, unsatisfiable
   instruction, since Audit/Knowledge Graph share Identity's exact network
   target per D-1). :func:`detect_additive_identity_bypass` is now a live
   check the recovery-fence script runs against every other NetworkPolicy in
   the namespace before it will write evidence.

Round-3 remediation (independent review found the round-2 evidence contract
still insufficient in two further, narrower ways -- A11's actual text): A11
requires Stage-50, during a recovery qualification, to confirm the A9
evidence records "exist and are attributable to the fence owner for the
recovery being validated." ``verified_by`` was structurally required to be a
non-empty string, but nothing ever compared it against the actual governed
fence owner for the recovery in progress, so any non-empty value (including
an unrelated or fabricated one) passed. Separately, ``namespace`` was
required by schema but never compared against the namespace actually being
recovered. :func:`validate_recovery_fence_evidence` now accepts optional
``expected_owner``/``expected_namespace`` parameters; when the caller
supplies them (Stage-50 recovery qualification always does -- see
``__main__.py``), a mismatch, or a blank expected value, is rejected exactly
like any other fail-closed evidence defect. The standalone
``validate-recovery-fence`` command (the A9.4/A9.6 per-phase-transition gate
the recovery coordinator consults directly, distinct from A11's Stage-50
gate) is unaffected: it does not pass these parameters and its existing
behavior is unchanged.
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NETWORK_POLICY_NAME = "emg-identity-db-egress"

#: The exact, code-defined pod-selector label set each phase's NetworkPolicy
#: template is required to carry (see the identity-db-egress.*.example.yaml
#: files). Evidence is validated against these constants, never against a
#: caller-supplied or file-supplied label list -- an evidence file cannot
#: self-assert its own correctness.
PHASE_POD_SELECTOR_LABELS: dict[str, tuple[str, ...]] = {
    "normal": ("emg-identity", "emg-identity-migration"),
    "phase1": ("emg-identity-migration", "emg-identity-recovery-reconcile"),
    "phase2": ("emg-identity-recovery-qualify",),
}

#: Every Identity-owned workload label across all three phases. Used by the
#: additive-bypass detector to recognize any NetworkPolicy that touches an
#: Identity pod, regardless of which phase (if any) it claims to implement.
IDENTITY_WORKLOAD_LABELS: frozenset[str] = frozenset(
    label for labels in PHASE_POD_SELECTOR_LABELS.values() for label in labels
)


class RecoveryFenceEvidenceDenied(Exception):
    """Fence evidence is missing, malformed, wrong-phase, wrong-target, stale,
    hash-mismatched, or the live policy state it describes is unsafe."""


@dataclass(frozen=True, slots=True)
class RecoveryFenceEvidence:
    """One verified fence-transition record (A9.4 positive evidence)."""

    phase: str
    network_policy_name: str
    namespace: str
    target_environment: str
    policy_spec_canonical: str
    spec_sha256: str
    pod_selector_labels: tuple[str, ...]
    verified_at: datetime
    verified_by: str


def canonicalize_network_policy_spec(spec: dict[str, Any]) -> str:
    """Deterministic JSON canonicalization of the security-relevant fields of
    a NetworkPolicy ``spec`` (podSelector, policyTypes, egress) -- sorted
    keys, no incidental whitespace, so the same live object always produces
    the same canonical string regardless of key order returned by the API
    server."""

    relevant = {
        "podSelector": spec.get("podSelector") or {},
        "policyTypes": sorted(spec.get("policyTypes") or []),
        "egress": spec.get("egress") or [],
    }
    return json.dumps(relevant, sort_keys=True, separators=(",", ":"))


def sha256_hex(canonical: str) -> str:
    import hashlib

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def pod_selector_labels_from_spec(spec: dict[str, Any]) -> set[str]:
    """Extract the set of ``app.kubernetes.io/name`` values a NetworkPolicy's
    podSelector matches, from both ``matchLabels`` and an ``In`` expression on
    that key -- the only two shapes this repository's own identity-db-egress
    templates use. This is a *governance* helper (are the three templates
    exactly labeled the way A9.4 requires?), not a general selector
    evaluator -- see :func:`selector_matches_labels` for that, which the
    additive-bypass detector uses instead precisely because a hostile or
    careless *other* policy is not obliged to use this shape (e.g. it might
    select purely on ``app.kubernetes.io/part-of``, matching Identity pods
    without ever naming them)."""

    selector = spec.get("podSelector") or {}
    labels = {v for v in (selector.get("matchLabels") or {}).values()}
    for expr in selector.get("matchExpressions") or []:
        if expr.get("key") == "app.kubernetes.io/name" and expr.get("operator") == "In":
            labels.update(expr.get("values") or [])
    return labels


#: The full label set every Identity-owned pod actually carries in this
#: repository's manifests (see infra/kubernetes/base/identity.yaml,
#: identity-recovery.yaml, identity-migration.yaml): both
#: ``app.kubernetes.io/name`` and the shared ``app.kubernetes.io/part-of``.
#: The additive-bypass detector evaluates every other policy's selector
#: against each of these full label sets -- not merely against the `name`
#: label -- because a selector scoped only to ``part-of`` (exactly the shape
#: of the round-1 defect) matches these pods too and must not be missed.
IDENTITY_POD_LABEL_SETS: tuple[dict[str, str], ...] = tuple(
    {"app.kubernetes.io/name": name, "app.kubernetes.io/part-of": "emg-platform"}
    for name in sorted(IDENTITY_WORKLOAD_LABELS)
)


def selector_matches_labels(selector: dict[str, Any], labels: dict[str, str]) -> bool:
    """Evaluate a Kubernetes ``LabelSelector`` (``matchLabels`` +
    ``matchExpressions``) against a concrete label set, using standard
    Kubernetes selector semantics: every clause must hold (AND), an empty
    selector matches every pod, and an unrecognized ``matchExpressions``
    operator fails closed (treated as matching, since the operator's actual
    behavior at the API server cannot be verified offline)."""

    for key, value in (selector.get("matchLabels") or {}).items():
        if labels.get(key) != value:
            return False
    for expr in selector.get("matchExpressions") or []:
        key = expr.get("key")
        operator = expr.get("operator")
        values = expr.get("values") or []
        if operator == "In":
            if labels.get(key) not in values:
                return False
        elif operator == "NotIn":
            if labels.get(key) in values:
                return False
        elif operator == "Exists":
            if key not in labels:
                return False
        elif operator == "DoesNotExist":
            if key in labels:
                return False
        else:
            return True  # fail closed: unrecognized operator, assume it could match
    return True


def policy_selects_any_identity_pod(spec: dict[str, Any]) -> bool:
    """Whether a NetworkPolicy's podSelector would match any Identity-owned
    pod's *full* label set (not merely its ``app.kubernetes.io/name``)."""

    selector = spec.get("podSelector") or {}
    return any(selector_matches_labels(selector, labels) for labels in IDENTITY_POD_LABEL_SETS)


def validate_db_egress_rules(egress: list[Any]) -> None:
    """Reject an empty, unresolved-placeholder, missing-port, or unsafely
    broad (default-route) database egress rule set.

    This is intentionally strict about *shape* (explicit port, explicit
    ipBlock) without knowing or guessing the real environment CIDR: a
    checked-in ``.example.yaml`` template's empty ``egress: []`` fails this
    check, which is correct -- it is not a deployable object, only a
    filled-in copy applied by the recovery coordinator is.
    """

    if not egress:
        raise RecoveryFenceEvidenceDenied(
            "NetworkPolicy egress rule is empty or unresolved -- fill in the "
            "environment-specific ipBlock/port before applying"
        )
    for rule in egress:
        ports = rule.get("ports")
        if not ports:
            raise RecoveryFenceEvidenceDenied(
                "NetworkPolicy egress rule has no explicit port; a blanket "
                "all-ports rule is not authorized as a database target"
            )
        for port_entry in ports:
            port = port_entry.get("port")
            if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
                raise RecoveryFenceEvidenceDenied(
                    "NetworkPolicy egress rule has a missing or invalid port"
                )
        destinations = rule.get("to")
        if not destinations:
            raise RecoveryFenceEvidenceDenied("NetworkPolicy egress rule has no destination")
        for destination in destinations:
            ip_block = destination.get("ipBlock")
            cidr = ip_block.get("cidr") if isinstance(ip_block, dict) else None
            if not cidr:
                raise RecoveryFenceEvidenceDenied(
                    "NetworkPolicy egress rule destination must be an ipBlock "
                    "naming the environment-resolved PostgreSQL address"
                )
            try:
                network = ipaddress.ip_network(cidr, strict=False)
            except ValueError as exc:
                raise RecoveryFenceEvidenceDenied(
                    f"NetworkPolicy egress ipBlock CIDR is invalid or unresolved: {cidr!r}"
                ) from exc
            if network.prefixlen == 0:
                raise RecoveryFenceEvidenceDenied(
                    f"NetworkPolicy egress ipBlock CIDR {cidr!r} is a default route "
                    "(0.0.0.0/0 or ::/0); this is not authorized as a database "
                    "target by any accepted ADR-043 architecture"
                )


def _networks_from_egress(
    egress: list[Any],
) -> list[tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, int | None]]:
    """Best-effort extraction of (network, port) pairs from an *arbitrary*
    (possibly unrelated) NetworkPolicy's egress rules, for bypass detection
    only. Unlike :func:`validate_db_egress_rules`, this silently skips
    anything that is not a well-formed ipBlock rule (e.g. a podSelector- or
    namespaceSelector-based rule, or a DNS-only rule) rather than raising --
    those are legitimate, unrelated egress grants and must not trigger a
    false additive-bypass finding."""

    results: list[tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, int | None]] = []
    for rule in egress or []:
        ports = rule.get("ports") or []
        port_numbers: list[int | None] = [
            p.get("port") for p in ports if isinstance(p.get("port"), int)
        ] or [None]
        for destination in rule.get("to") or []:
            ip_block = destination.get("ipBlock")
            cidr = ip_block.get("cidr") if isinstance(ip_block, dict) else None
            if not cidr:
                continue
            try:
                network = ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                continue
            for port_number in port_numbers:
                results.append((network, port_number))
    return results


def detect_additive_identity_bypass(
    all_policies: list[dict[str, Any]],
    *,
    protected_egress: list[Any],
    own_policy_name: str = NETWORK_POLICY_NAME,
) -> None:
    """A9.4: raise :class:`RecoveryFenceEvidenceDenied` if any NetworkPolicy
    *other than* ``own_policy_name`` selects any Identity-owned pod
    (:func:`policy_selects_any_identity_pod`, evaluated against each pod's
    *full* label set -- not merely its ``app.kubernetes.io/name`` -- so a
    selector scoped only to ``app.kubernetes.io/part-of: emg-platform``,
    exactly the shape of the round-1 defect, is caught) and grants egress
    overlapping the same destination network/port as ``protected_egress``
    (the governed ``emg-identity-db-egress`` policy's own, just-applied
    egress rules).

    This is the live counterpart to the comment-only convention that proved
    insufficient in round 1: it inspects every NetworkPolicy object actually
    present in the namespace, not just the one this tooling manages, so a
    stray or overly broad policy created by any means is caught.
    """

    protected = _networks_from_egress(protected_egress)
    if not protected:
        return
    for policy in all_policies:
        name = policy.get("metadata", {}).get("name")
        if name == own_policy_name:
            continue
        spec = policy.get("spec") or {}
        if "Egress" not in (spec.get("policyTypes") or []):
            continue
        if not policy_selects_any_identity_pod(spec):
            continue
        candidates = _networks_from_egress(spec.get("egress") or [])
        for candidate_network, candidate_port in candidates:
            for protected_network, protected_port in protected:
                if (
                    candidate_port is not None
                    and protected_port is not None
                    and candidate_port != protected_port
                ):
                    continue
                if candidate_network.overlaps(protected_network):
                    raise RecoveryFenceEvidenceDenied(
                        f"NetworkPolicy {name!r} selector matches one or more "
                        "Identity-owned pods and grants egress overlapping the "
                        "governed PostgreSQL target -- additive policy bypass "
                        "detected; refusing to produce fence evidence"
                    )


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise RecoveryFenceEvidenceDenied("fence evidence verified_at is missing or malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryFenceEvidenceDenied(
            "fence evidence verified_at is not valid ISO-8601"
        ) from exc
    if parsed.tzinfo is None:
        raise RecoveryFenceEvidenceDenied("fence evidence verified_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _require_nonempty_str(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise RecoveryFenceEvidenceDenied(f"fence evidence is missing required field: {field}")
    return value


def load_recovery_fence_evidence(path: Path) -> RecoveryFenceEvidence:
    """Parse and structurally/hash validate a fence-evidence file. Does not
    check phase/target/freshness against caller expectations -- see
    :func:`validate_recovery_fence_evidence` for the fail-closed gate."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RecoveryFenceEvidenceDenied(f"fence evidence file unreadable: {exc}") from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise RecoveryFenceEvidenceDenied("fence evidence file is malformed") from exc
    if not isinstance(payload, dict):
        raise RecoveryFenceEvidenceDenied("fence evidence file is malformed")

    phase = _require_nonempty_str(payload, "phase")
    network_policy_name = _require_nonempty_str(payload, "network_policy_name")
    namespace = _require_nonempty_str(payload, "namespace")
    target_environment = _require_nonempty_str(payload, "target_environment")
    verified_by = _require_nonempty_str(payload, "verified_by")
    policy_spec_canonical = _require_nonempty_str(payload, "policy_spec_canonical")
    spec_sha256 = _require_nonempty_str(payload, "spec_sha256")
    verified_at = _parse_timestamp(payload.get("verified_at"))

    if len(spec_sha256) != 64 or any(c not in "0123456789abcdef" for c in spec_sha256):
        raise RecoveryFenceEvidenceDenied(
            "fence evidence spec_sha256 is not a valid SHA-256 digest"
        )

    recomputed = sha256_hex(policy_spec_canonical)
    if recomputed != spec_sha256:
        raise RecoveryFenceEvidenceDenied(
            "fence evidence spec_sha256 does not match the embedded policy_spec_canonical "
            "content -- evidence integrity check failed"
        )

    try:
        canonical_spec = json.loads(policy_spec_canonical)
    except ValueError as exc:
        raise RecoveryFenceEvidenceDenied(
            "fence evidence policy_spec_canonical is not valid JSON"
        ) from exc
    if not isinstance(canonical_spec, dict):
        raise RecoveryFenceEvidenceDenied("fence evidence policy_spec_canonical is malformed")
    if canonical_spec.get("policyTypes") != ["Egress"]:
        raise RecoveryFenceEvidenceDenied(
            "fence evidence policy_spec_canonical is not an Egress-only policy"
        )
    validate_db_egress_rules(canonical_spec.get("egress") or [])
    labels = tuple(sorted(pod_selector_labels_from_spec(canonical_spec)))
    if not labels:
        raise RecoveryFenceEvidenceDenied(
            "fence evidence policy_spec_canonical has an empty or unrecognized podSelector"
        )

    return RecoveryFenceEvidence(
        phase=phase,
        network_policy_name=network_policy_name,
        namespace=namespace,
        target_environment=target_environment,
        policy_spec_canonical=policy_spec_canonical,
        spec_sha256=spec_sha256,
        pod_selector_labels=labels,
        verified_at=verified_at,
        verified_by=verified_by,
    )


def validate_recovery_fence_evidence(
    path: Path,
    *,
    expected_phase: str,
    expected_target_environment: str,
    expected_namespace: str | None = None,
    expected_owner: str | None = None,
    max_age_seconds: float = 900.0,
    now: datetime | None = None,
) -> RecoveryFenceEvidence:
    """A9.4/A9.6 fail-closed fence-evidence gate.

    Raises :class:`RecoveryFenceEvidenceDenied` unless the evidence file
    proves, as of ``now``, that the phase-appropriate NetworkPolicy was
    applied to the exact expected object, in the exact expected namespace,
    for the exact expected environment, with an embedded canonical spec whose
    SHA-256 matches the accompanying ``spec_sha256`` (evidence integrity),
    whose pod-selector label set exactly equals the governed contract for
    ``expected_phase`` (:data:`PHASE_POD_SELECTOR_LABELS` -- never a
    separately-asserted label list), and whose egress rules are well-formed
    and not a default route (:func:`validate_db_egress_rules`). The read-back
    verification must not be older than ``max_age_seconds``. A stale,
    wrong-phase, wrong-target, hash-mismatched, or malformed file is treated
    identically to a missing one: recovery does not proceed.

    ``expected_namespace`` and ``expected_owner`` are optional and ``None`` by
    default (the A9.4/A9.6 standalone phase-transition gate does not require
    them). When a caller supplies either (Stage-50 recovery qualification --
    A11 -- always does), it must be a non-empty string, and the evidence's
    corresponding field must match it exactly: a blank expected value, or a
    mismatch against the evidence's ``namespace``/``verified_by``, is denied.
    The expected values must come from the recovery coordinator's own
    invocation, never inferred from the evidence file itself -- this
    function never uses the evidence's own claims to validate itself.
    """

    if expected_phase not in PHASE_POD_SELECTOR_LABELS:
        raise RecoveryFenceEvidenceDenied(f"unknown recovery fence phase: {expected_phase!r}")
    if expected_namespace is not None and not expected_namespace:
        raise RecoveryFenceEvidenceDenied("expected namespace must not be blank")
    if expected_owner is not None and not expected_owner:
        raise RecoveryFenceEvidenceDenied("expected fence owner must not be blank")

    evidence = load_recovery_fence_evidence(path)

    if evidence.network_policy_name != NETWORK_POLICY_NAME:
        raise RecoveryFenceEvidenceDenied("fence evidence names the wrong NetworkPolicy object")
    if evidence.phase != expected_phase:
        raise RecoveryFenceEvidenceDenied(
            f"fence evidence phase {evidence.phase!r} does not match the required "
            f"phase {expected_phase!r} for this step"
        )
    if evidence.target_environment != expected_target_environment:
        raise RecoveryFenceEvidenceDenied(
            "fence evidence target_environment does not match the environment being recovered"
        )
    if expected_namespace is not None and evidence.namespace != expected_namespace:
        raise RecoveryFenceEvidenceDenied(
            "fence evidence namespace does not match the namespace being recovered"
        )
    if expected_owner is not None and evidence.verified_by != expected_owner:
        raise RecoveryFenceEvidenceDenied(
            "fence evidence verified_by does not match the expected governed fence owner "
            "for this recovery (A11 attribution check)"
        )
    expected_labels = PHASE_POD_SELECTOR_LABELS[expected_phase]
    if set(evidence.pod_selector_labels) != set(expected_labels):
        raise RecoveryFenceEvidenceDenied(
            f"fence evidence pod-selector labels {sorted(evidence.pod_selector_labels)} do "
            f"not exactly match the governed {expected_phase!r} contract {sorted(expected_labels)}"
        )

    current_time = now if now is not None else datetime.now(timezone.utc)
    if evidence.verified_at > current_time:
        raise RecoveryFenceEvidenceDenied("fence evidence verified_at is in the future")
    age = (current_time - evidence.verified_at).total_seconds()
    if age > max_age_seconds:
        raise RecoveryFenceEvidenceDenied(
            f"fence evidence is stale ({age:.0f}s old, max {max_age_seconds:.0f}s); "
            "re-verify the live NetworkPolicy before proceeding"
        )

    return evidence
