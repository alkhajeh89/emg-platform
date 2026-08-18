package bootstrap

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/compromiseledger"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/recovery"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationcommit"
)

var (
	// ErrLineageNotConfigured, ErrKeyNotInLineage, ErrKeyNotPinned,
	// ErrCompromiseLedgerUnavailable, and ErrSignerKeyMismatch are the
	// distinct, independently-checked genesis preconditions S6 Phase 5
	// requires. None of these ever substitutes for another --
	// PinnedPublicKeyExists != KeyAuthorized, exactly as keypinning's own
	// package doc requires, and that same non-substitution discipline
	// extends here to genesis specifically.
	ErrLineageNotConfigured        = errors.New("bootstrap: no ApprovedSigningLineage configured; refusing genesis")
	ErrKeyNotInLineage             = errors.New("bootstrap: signing key is not in the approved signing lineage; refusing genesis")
	ErrKeyNotPinned                = errors.New("bootstrap: signing key has no durable pin; refusing genesis")
	ErrCompromiseLedgerUnavailable = errors.New("bootstrap: compromise ledger unavailable or unreadable; refusing genesis")
	ErrKeyRequiresManualReview     = errors.New("bootstrap: signing key requires manual compromise review; refusing genesis")
	ErrSignerKeyMismatch           = errors.New("bootstrap: live signer's active key does not match the requested signing key; refusing genesis")
)

// SigningPreconditions bundles every independent, fail-closed signing-side
// gate S6 Phase 5 requires be satisfied BEFORE any Spanner mutation is
// attempted for genesis. Each field is a narrow, already-existing S1-S3
// capability -- this package adds no new signing-domain capability of its
// own, and, like every other caller in this codebase, never treats one
// check as a substitute for another.
type SigningPreconditions struct {
	// Lineage is the caller-independent trust anchor (ADR-045 §7A) the
	// requested SigningKeyID must belong to. Required; a nil Lineage fails
	// closed rather than treating "not configured" as "not restricted."
	Lineage recovery.ApprovedSigningLineage
	// PinStore resolves whether the requested SigningKeyID already has
	// durably pinned public-key material (ADR-045 §7C). Genesis never
	// captures a new pin itself -- pinning is a separately governed,
	// already-implemented S3 operation that must have already happened
	// for the exact key genesis is about to use.
	PinStore keypinning.Store
	// Ledger is consulted as a defense-in-depth precondition, using the
	// current wall-clock time as the best available proxy for the not-yet-
	// assigned Spanner commit timestamp (the real, authoritative
	// compromise check happens at read/verification time against the
	// payload's actual commit_timestamp -- see recovery.VerifyPersistedCommitted
	// and kmsverifier -- and this precondition never substitutes for it).
	Ledger compromiseledger.Ledger
	// Signer is the exact same rotationcommit.Signer boundary genesis will
	// use to sign the COMMITTED payload (in production, a signerrpc.Client
	// -- genesis never holds a direct KMS signing capability, preserving
	// the same two-process separation ordinary rotation already requires).
	Signer rotationcommit.Signer
}

// CheckSigningPreconditions implements S6 Phase 5 in the exact order it is
// specified: lineage membership, durable pin existence, compromise-ledger
// availability/status, and finally live signer/verifier key-identity
// agreement. The first failing check returns immediately -- there is no
// "best effort" continuation past a failed gate.
func CheckSigningPreconditions(ctx context.Context, pre SigningPreconditions, keyID protocol.SigningKeyID) error {
	if pre.Lineage == nil {
		return ErrLineageNotConfigured
	}
	if !pre.Lineage(keyID) {
		return fmt.Errorf("%w: %s", ErrKeyNotInLineage, keyID.String())
	}
	if pre.PinStore == nil {
		return fmt.Errorf("%w: no pin store configured", ErrKeyNotPinned)
	}
	if _, err := pre.PinStore.Get(ctx, keyID); err != nil {
		return fmt.Errorf("%w: %v", ErrKeyNotPinned, err)
	}
	if pre.Ledger == nil {
		return fmt.Errorf("%w: no ledger configured", ErrCompromiseLedgerUnavailable)
	}
	status, err := pre.Ledger.Status(ctx, compromiseledger.SigningKeyIDSubject(keyID), time.Now().UTC())
	if err != nil {
		return fmt.Errorf("%w: %v", ErrCompromiseLedgerUnavailable, err)
	}
	if status == compromiseledger.StatusRequiresManualReview {
		return fmt.Errorf("%w: %s", ErrKeyRequiresManualReview, keyID.String())
	}
	if pre.Signer == nil {
		return fmt.Errorf("%w: no signer configured", ErrSignerKeyMismatch)
	}
	activeKeyID, err := pre.Signer.ActiveKeyID(ctx)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrSignerKeyMismatch, err)
	}
	if activeKeyID != keyID {
		return fmt.Errorf("%w: requested %q, live signer reports %q", ErrSignerKeyMismatch, keyID.String(), activeKeyID.String())
	}
	return nil
}

var (
	// ErrWitnessTargetUnavailable means the witness precondition check
	// (S6 Phase 6) could not be evaluated at all -- an ambiguous or failed
	// Exists call. Genesis never proceeds when it cannot establish whether
	// its own target witness key is already occupied.
	ErrWitnessTargetUnavailable = errors.New("bootstrap: could not determine witness target state; refusing genesis")

	// ErrWitnessRetentionUnverifiable documents a genuine, structural gap
	// (S6 Phase 6/14): gcswitness.ImmutableWitness deliberately exposes no
	// bucket-attribute (Retention/Bucket Lock) read capability -- its own
	// boundary_test.go (TestNoForbiddenStorageMethods) forbids calling
	// Retention/SetRetention/LockRetention/Lifecycle at all, by design,
	// because that already-reviewed ADR-043 boundary is scoped to exactly
	// two object-level operations. Verifying that a real target bucket
	// actually has an appropriate retention policy and is Bucket-Lock-ed
	// therefore requires either a separately-reviewed, narrowly-scoped
	// capability addition to gcswitness (out of this package's authority to
	// decide unilaterally) or an out-of-band operational check performed
	// before bootstrap is ever invoked. This package deliberately does not
	// attempt either -- see the S6 final report's real-cloud qualification
	// section.
	ErrWitnessRetentionUnverifiable = errors.New("bootstrap: witness bucket retention/Bucket-Lock configuration cannot be verified by this package (see ErrWitnessRetentionUnverifiable doc)")
)

// WitnessPreconditions bundles the witness-side gate S6 Phase 6 requires.
type WitnessPreconditions struct {
	Witness gcswitness.ImmutableWitness
}

// CheckWitnessPreconditions verifies the ONE witness-side property this
// package is structurally able to verify before genesis: that the exact
// deterministic witness key this genesis attempt would write to is not
// already occupied by conflicting content. It does not, and cannot,
// verify bucket-level retention/Bucket-Lock configuration -- see
// ErrWitnessRetentionUnverifiable. Returning (true, nil, nil) means the
// witness key already holds this exact genesis's own prior output
// (idempotent retry, S6 Phase 9 scenario G); callers must treat that as
// "genesis already completed," never as a precondition failure.
func CheckWitnessPreconditions(ctx context.Context, pre WitnessPreconditions, witnessKey string) (alreadyExists bool, err error) {
	if pre.Witness == nil {
		return false, fmt.Errorf("%w: no witness adapter configured", ErrWitnessTargetUnavailable)
	}
	exists, err := pre.Witness.Exists(ctx, witnessKey)
	if err != nil {
		return false, fmt.Errorf("%w: %v", ErrWitnessTargetUnavailable, err)
	}
	return exists, nil
}
