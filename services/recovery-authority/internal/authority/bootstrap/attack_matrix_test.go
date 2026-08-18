// This file is the S6 Phase 11 adversarial test matrix: one entry per
// named attack, either a dedicated test in this file or a pointer to the
// specific existing test (in this package or elsewhere in the repository)
// that already exercises it. Every attack must fail closed -- none of
// these tests may ever observe ExecuteGenesis (or an equivalent boundary
// this package/ordinary runtime relies on) return success or silently
// proceed.
package bootstrap

import (
	"context"
	"errors"
	"testing"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// ATTACK_A: fabricate genesis row directly (write a plausible-looking
// witness object at the exact deterministic key without ever going through
// the real Commit + Signer boundary). ExecuteGenesis must independently
// re-verify -- content binding AND signature -- rather than trust the
// object's mere presence.
func TestAttackA_FabricatedGenesisRowIsRejected(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	req := fx.request(t)

	forgedPayload, err := protocol.NewCommittedPayloadV2(
		req.EnvironmentID, req.AuthorityEpoch, req.ResourceIncarnation, req.OperationID,
		GenesisRevision, GenesisPredecessorRevision, GenesisPredecessorDigest,
		protocol.Digest32{}, fx.now, req.SigningKeyID,
		[]byte("not a real signature, never produced by any Signer"),
	)
	if err != nil {
		t.Fatal(err)
	}
	wire, err := protocol.MarshalCommittedPayloadJSON(forgedPayload)
	if err != nil {
		t.Fatal(err)
	}
	fx.witness.objects[req.WitnessKey()] = wire

	outcome, err := ExecuteGenesis(context.Background(), fx.deps(), req, fx.now)
	if outcome != OutcomeConflict {
		t.Fatalf("outcome = %s, want CONFLICT (forged witness content must never be accepted as a genuine prior genesis)", outcome)
	}
	if !errors.Is(err, ErrGenesisConflict) {
		t.Fatalf("err = %v, want ErrGenesisConflict", err)
	}
	if fx.spanner.commitCalls != 0 {
		t.Fatalf("commitCalls = %d, want 0 (a fabricated witness object must be rejected before any real Commit is attempted)", fx.spanner.commitCalls)
	}
}

// ATTACK_B: bypass acceptedRotationContext. See
// TestRotationcommitImportSurfaceIsPublicOnly (this package) and
// rotationcommit's own TestBuildCommittedPayloadRequiresLiveAcceptedContext
// / TestCompleteGenesisCommit* tests: acceptedRotationContext is an
// unexported type with an unexported constructor reachable only from
// completeRawCommit's own success path; no identifier in this package, and
// no Go language feature available to it, can construct or forge one.

// ATTACK_C: unapproved signing lineage. See
// TestCheckSigningPreconditionsRejectsKeyOutsideLineage.

// ATTACK_D: missing key pin. See
// TestCheckSigningPreconditionsRejectsUnpinnedKey and
// TestExecuteGenesisRejectsWhenSigningKeyNotPinned.

// ATTACK_E: compromise ledger unavailable. See
// TestCheckSigningPreconditionsRejectsUnavailableLedger and
// TestCheckSigningPreconditionsRejectsDistrustedKey.

// ATTACK_F: test/local signer selected. See
// TestNoDirectSigningOrEmulatorImports (no conformance/localsigner
// import). Genesis's Signer dependency is always the rotationcommit.Signer
// INTERFACE; which concrete type satisfies it in a given deployment is a
// composition-time decision made by a caller outside this package (see the
// S6 provisioning contract).

// ATTACK_G: emulator endpoint selected. See
// TestNoDirectSigningOrEmulatorImports (no conformance/spanneradapter
// import). GenesisSpannerClient is satisfied in production by the same raw
// spannerpb.SpannerClient stub spannercommit.Dial already constructs
// against the fixed, real spanner.googleapis.com:443 endpoint
// (spannercommit's own defaultEndpoint) -- this package never dials
// anything itself.

// ATTACK_H: authority runtime gains signer identity. See
// TestNoDirectSigningOrEmulatorImports (no kmssigner import in this
// package) and cmd/recovery-authority/boundary_test.go (already
// established in S5: that binary holds no Cloud KMS credential and imports
// no KMS package at all).

// ATTACK_I: signer runtime gains Spanner mutation capability. See
// cmd/recovery-signer/boundary_test.go (S5): that binary imports neither
// spannercommit nor gcswitness, so it cannot construct or issue a Spanner
// Commit RPC regardless of what this package does.

// ATTACK_J: witness target not locked/qualified. This package can verify
// only object-level existence/idempotency (CheckWitnessPreconditions) --
// bucket-level Retention/Bucket-Lock configuration is unverifiable by
// design, because gcswitness's own already-reviewed ADR-043 boundary
// (gcswitness/boundary_test.go, TestNoForbiddenStorageMethods) forbids
// calling Retention/SetRetention/LockRetention/Lifecycle at all. See
// ErrWitnessRetentionUnverifiable's doc comment in preconditions.go and the
// S6 final report's real-cloud qualification section -- this is reported
// as a genuine, structural gap, not silently assumed away.

// ATTACK_K: ambiguous Commit resolved via a later read ("recovery"). See
// TestExecuteGenesisTreatsAmbiguousCommitAsUnresolved: an ambiguous Commit
// outcome is never resolved by attempting a subsequent read of
// authority_head -- ExecuteGenesis has no code path that performs such a
// read at all; the only recovery from OutcomeUnresolved is a fresh
// GenesisRequest with fresh identifiers, following ADR-044 §8's
// NEW_EPOCH_REQUIRED procedure exactly as ordinary rotation already does.

// ATTACK_L: duplicate bootstrap creates a second genesis. See
// TestExecuteGenesisIsIdempotentOnRerunAfterSuccess (a rerun of a
// successful attempt never issues a second Commit) and
// TestExecuteGenesisRetryAfterCommitSucceedsIsUnresolvedNotDuplicated (a
// retry after a partially-failed attempt never reports success a second
// time -- the second Mutation_Insert genuinely conflicts at the Spanner
// layer).

// ATTACK_M: process loss mid-bootstrap. Modeled by
// TestExecuteGenesisRetryAfterCommitSucceedsIsUnresolvedNotDuplicated's
// first phase (Commit succeeds, the subsequent witness write never
// completes -- exactly ADR-044 §9's "genuine process loss... after Commit
// classified UnambiguousSuccess but before the same-operation COMMITTED
// witness write completes" scenario, here simulated via an injected
// witness failure rather than an actual killed process, matching how
// rotationcommit's own emulator_processkill_test.go already covers the
// process-boundary case for ordinary rotation).

// ATTACK_N: witness holds conflicting bytes. See
// TestExecuteGenesisConflictWhenWitnessHoldsMismatchedContent.

// ATTACK_O: bootstrap privilege persists into ordinary runtime. See
// TestOrdinaryRuntimeBinariesNeverImportBootstrap. IAM-level revocability
// of a real bootstrap principal's grants after genesis is a
// deployment/governance fact this package cannot see or enforce -- see the
// S6 provisioning contract and final report.

// ATTACK_P: one person satisfies both approvals. See
// TestValidateDualControlRejectsSameApprover.

// ATTACK_Q: stale or replayed approval used. See
// TestValidateDualControlRejectsStaleApproval,
// TestValidateDualControlRejectsMismatchedRequestDigest, and
// TestNewGenesisRequestApprovalMustBindExactRequest.

// ATTACK_R: static credential file configured. See
// TestNoStaticCredentialImports. Dependencies accepts only
// already-constructed capability objects; there is no field or code path
// in this package that reads a credential file path, and production
// callers (cmd/recovery-authority, cmd/recovery-signer) already
// exclusively use ADC/WIF (S5 Phase 2).

// ATTACK_S: Kubernetes deployment exposes the signer RPC publicly. This is
// an infrastructure-manifest concern, not something this Go package can
// exercise -- see infra/kubernetes/base/network-policies.yaml's
// emg-recovery-signer-ingress policy (S6 Phase 7: ingress restricted to
// emg-recovery-authority pods only, port 8443) and
// tests/infrastructure/test_production_manifests.py.

// ATTACK_T: production deployment accidentally uses the same service
// account for authority and signer. Also an infrastructure-manifest
// concern -- see infra/kubernetes/base/service-accounts.yaml's distinct
// emg-recovery-authority / emg-recovery-signer ServiceAccounts (each with
// its own iam.gke.io/gcp-service-account WIF annotation, S6 Phase 7) and
// docker/dependencies.yaml's distinct path entries (S6, avoiding the
// dict-key collision documented in mutations.go's schema-source comment).
