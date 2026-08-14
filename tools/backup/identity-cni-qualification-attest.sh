#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh disable=SC1091
source "$SCRIPT_DIR/common.sh"
PYTHON_BIN="${EMG_BACKUP_PYTHON:-python3}"

# ADR-043 Amendment 1 A9.4: records the environment/recovery coordinator's
# positive attestation that the target cluster's CNI enforces Kubernetes
# NetworkPolicy Egress semantics -- the precondition every phase-scoped
# database-egress policy in this repository depends on to mean anything.
#
# This script does NOT and CANNOT perform a live packet-level enforcement
# test; no such test can run from this repository without a qualifying live
# cluster. It only produces a well-formed, schema-valid, freshness-bounded
# evidence record of a qualification the coordinator performed by other
# means (for example: confirming the cluster's CNI/dataplane provider out of
# band, such as `gcloud container clusters describe --format
# "value(networkConfig.datapathProvider)"` reporting ADVANCED_DATAPATH for
# GKE Dataplane V2, or an equivalent Calico/Cilium verification) and
# describes that method in EMG_CNI_QUALIFICATION_METHOD. Treat the resulting
# file as REPOSITORY_CNI_QUALIFICATION_CONTRACT evidence, never as proof of
# LIVE_CNI_ENFORCEMENT_WITNESS -- the two are deliberately kept distinct.
: "${EMG_IDENTITY_RECOVERY_TARGET_ENVIRONMENT:?must identify the environment being recovered, e.g. production}"
: "${EMG_CNI_QUALIFICATION_CLUSTER:?must identify the target cluster, e.g. its full resource name}"
: "${EMG_CNI_QUALIFICATION_METHOD:?must describe how egress NetworkPolicy enforcement was verified}"
: "${EMG_IDENTITY_RECOVERY_FENCE_ACTOR:?must identify the verifying actor for the audit trail}"
: "${EMG_IDENTITY_CNI_QUALIFICATION_EVIDENCE:?must be an absolute path to write the CNI qualification evidence file}"
[[ "$EMG_IDENTITY_CNI_QUALIFICATION_EVIDENCE" = /* ]] || die "EMG_IDENTITY_CNI_QUALIFICATION_EVIDENCE must be absolute"

"$PYTHON_BIN" -c '
import json
import os
import sys
from datetime import datetime, timezone

from emg_persistence.provisioning import validate_cni_egress_qualification_evidence

target_environment = os.environ["EMG_IDENTITY_RECOVERY_TARGET_ENVIRONMENT"]
cluster_identifier = os.environ["EMG_CNI_QUALIFICATION_CLUSTER"]
evidence = {
    "target_environment": target_environment,
    "cluster_identifier": cluster_identifier,
    "qualification_method": os.environ["EMG_CNI_QUALIFICATION_METHOD"],
    "verified_by": os.environ["EMG_IDENTITY_RECOVERY_FENCE_ACTOR"],
    "verified_at": datetime.now(timezone.utc).isoformat(),
}
output_path = os.environ["EMG_IDENTITY_CNI_QUALIFICATION_EVIDENCE"]
with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(evidence, handle, indent=2, sort_keys=True)
    handle.write("\n")

# Self-check: the file this script just wrote must itself pass the same
# fail-closed gate Stage-50 recovery mode will apply to it.
from pathlib import Path
validate_cni_egress_qualification_evidence(
    Path(output_path),
    expected_target_environment=target_environment,
    expected_cluster_identifier=cluster_identifier,
)
print(f"CNI egress-enforcement qualification evidence written: {output_path}")
'
