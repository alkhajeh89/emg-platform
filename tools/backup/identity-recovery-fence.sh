#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh disable=SC1091
source "$SCRIPT_DIR/common.sh"
require_command kubectl
require_command python3
PYTHON_BIN="${EMG_BACKUP_PYTHON:-python3}"

# ADR-043 Amendment 1 A9.4/A9.6: applies exactly one of the mutually exclusive
# identity-db-egress.{normal,phase1,phase2}.example.yaml derivatives (the
# environment-filled copy, never the .example.yaml template itself), then
# reads BOTH the live object back AND every other NetworkPolicy in the
# namespace from the cluster -- never assumes `kubectl apply` exiting zero is
# evidence -- and writes a non-secret, hash-bound fence-evidence file only if
# ALL of the following hold:
#   1. the read-back object's podSelector exactly matches the governed label
#      set for the claimed phase (emg_persistence.provisioning
#      .PHASE_POD_SELECTOR_LABELS, the single source of truth also used by
#      `validate-recovery-fence`);
#   2. its egress rule is well-formed (explicit port, explicit ipBlock, not a
#      default route);
#   3. no OTHER NetworkPolicy in the namespace selects an Identity-labeled pod
#      and grants overlapping egress to the same destination (round-2
#      remediation: closes the additive-policy-bypass hazard round-1's
#      comment-only convention could not).
# The evidence file embeds the canonicalized live spec and its SHA-256
# together, so a validator can independently recompute and compare the hash
# rather than trusting an opaque, unverified digest.
#
# This script never mutates PostgreSQL, database privilege, or the recovery-
# authority pair; it only establishes and evidences the network-layer fence
# state A9.4 requires in addition to (never instead of) the already-
# implemented application/database recovery gate.
: "${EMG_RECOVERY_FENCE_PHASE:?must be one of: normal, phase1, phase2}"
: "${EMG_RECOVERY_FENCE_MANIFEST:?must be the environment-filled NetworkPolicy YAML for this phase}"
: "${EMG_RECOVERY_FENCE_NAMESPACE:?must name the target Kubernetes namespace}"
: "${EMG_RECOVERY_FENCE_TARGET_ENVIRONMENT:?must identify the environment being recovered, e.g. production}"
: "${EMG_RECOVERY_FENCE_ACTOR:?must identify the fence owner (A9.1) for the audit trail}"
: "${EMG_RECOVERY_FENCE_EVIDENCE_OUTPUT:?must be an absolute path to write the fence-evidence file}"

case "$EMG_RECOVERY_FENCE_PHASE" in
  normal|phase1|phase2) ;;
  *) die "EMG_RECOVERY_FENCE_PHASE must be one of: normal, phase1, phase2" ;;
esac
[[ -f "$EMG_RECOVERY_FENCE_MANIFEST" ]] || die "fence manifest not found: $EMG_RECOVERY_FENCE_MANIFEST"
[[ "$EMG_RECOVERY_FENCE_EVIDENCE_OUTPUT" = /* ]] || die "EMG_RECOVERY_FENCE_EVIDENCE_OUTPUT must be absolute"

manifest_name="$("$PYTHON_BIN" -c '
import sys, yaml
from emg_persistence.provisioning import validate_db_egress_rules, RecoveryFenceEvidenceDenied
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
if doc.get("kind") != "NetworkPolicy":
    sys.exit("fence manifest is not a NetworkPolicy")
name = doc.get("metadata", {}).get("name")
if name != "emg-identity-db-egress":
    sys.exit("fence manifest must be named emg-identity-db-egress, found: " + str(name))
try:
    validate_db_egress_rules(doc.get("spec", {}).get("egress") or [])
except RecoveryFenceEvidenceDenied as exc:
    sys.exit(f"fence manifest egress rule is invalid: {exc}")
print(name)
' "$EMG_RECOVERY_FENCE_MANIFEST")"

kubectl apply -n "$EMG_RECOVERY_FENCE_NAMESPACE" -f "$EMG_RECOVERY_FENCE_MANIFEST"

fence_tmp="$(mktemp -d)"
trap 'rm -rf -- "$fence_tmp"' EXIT
kubectl get networkpolicy "$manifest_name" -n "$EMG_RECOVERY_FENCE_NAMESPACE" -o json > "$fence_tmp/own.json"
kubectl get networkpolicy -n "$EMG_RECOVERY_FENCE_NAMESPACE" -o json > "$fence_tmp/all.json"

"$PYTHON_BIN" -c '
import json
import sys
from datetime import datetime, timezone

from emg_persistence.provisioning import (
    NETWORK_POLICY_NAME,
    PHASE_POD_SELECTOR_LABELS,
    RecoveryFenceEvidenceDenied,
    canonicalize_network_policy_spec,
    detect_additive_identity_bypass,
    pod_selector_labels_from_spec,
    sha256_hex,
    validate_db_egress_rules,
)

phase = sys.argv[1]
namespace = sys.argv[2]
target_environment = sys.argv[3]
actor = sys.argv[4]
output_path = sys.argv[5]
own_path = sys.argv[6]
all_path = sys.argv[7]

with open(own_path, encoding="utf-8") as handle:
    live = json.load(handle)
with open(all_path, encoding="utf-8") as handle:
    all_policies = json.load(handle).get("items", [])

spec = live.get("spec", {})

try:
    labels = pod_selector_labels_from_spec(spec)
    expected = set(PHASE_POD_SELECTOR_LABELS[phase])
    if labels != expected:
        raise RecoveryFenceEvidenceDenied(
            f"read-back podSelector {sorted(labels)} does not match the governed "
            f"{phase!r} contract {sorted(expected)}"
        )
    validate_db_egress_rules(spec.get("egress") or [])
    detect_additive_identity_bypass(all_policies, protected_egress=spec.get("egress") or [])
except RecoveryFenceEvidenceDenied as exc:
    sys.exit(f"refusing to write fence evidence: {exc}")

canonical = canonicalize_network_policy_spec(spec)
evidence = {
    "phase": phase,
    "network_policy_name": NETWORK_POLICY_NAME,
    "namespace": namespace,
    "target_environment": target_environment,
    "policy_spec_canonical": canonical,
    "spec_sha256": sha256_hex(canonical),
    "verified_at": datetime.now(timezone.utc).isoformat(),
    "verified_by": actor,
}
with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(evidence, handle, indent=2, sort_keys=True)
    handle.write("\n")
print(f"recovery network fence evidence written: {output_path} (phase={phase})")
' "$EMG_RECOVERY_FENCE_PHASE" "$EMG_RECOVERY_FENCE_NAMESPACE" "$EMG_RECOVERY_FENCE_TARGET_ENVIRONMENT" "$EMG_RECOVERY_FENCE_ACTOR" "$EMG_RECOVERY_FENCE_EVIDENCE_OUTPUT" "$fence_tmp/own.json" "$fence_tmp/all.json"
