package bootstrap

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
)

func TestExecuteGenesisCompletesOnCleanSuccess(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	req := fx.request(t)

	outcome, err := ExecuteGenesis(context.Background(), fx.deps(), req, fx.now)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if outcome != OutcomeCompleted {
		t.Fatalf("outcome = %s, want COMPLETED", outcome)
	}
	if fx.spanner.commitCalls != 1 {
		t.Fatalf("commitCalls = %d, want 1", fx.spanner.commitCalls)
	}
	exists, err := fx.witness.Exists(context.Background(), req.WitnessKey())
	if err != nil || !exists {
		t.Fatalf("expected witness object to exist: exists=%v err=%v", exists, err)
	}
}

func TestExecuteGenesisIsIdempotentOnRerunAfterSuccess(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	req := fx.request(t)

	first, err := ExecuteGenesis(context.Background(), fx.deps(), req, fx.now)
	if err != nil || first != OutcomeCompleted {
		t.Fatalf("first attempt: outcome=%s err=%v", first, err)
	}

	// Scenario G (S6 Phase 9): rerun the exact same request. No second
	// Spanner Commit must be attempted.
	second, err := ExecuteGenesis(context.Background(), fx.deps(), req, fx.now.Add(time.Minute))
	if err != nil {
		t.Fatalf("second attempt: unexpected error: %v", err)
	}
	if second != OutcomeAlreadyCompleted {
		t.Fatalf("second attempt outcome = %s, want ALREADY_COMPLETED", second)
	}
	if fx.spanner.commitCalls != 1 {
		t.Fatalf("commitCalls after rerun = %d, want still 1 (no second Commit attempted)", fx.spanner.commitCalls)
	}
}

func TestExecuteGenesisRejectsWhenSigningKeyNotPinned(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	// Replace the pin store with an empty one -- lineage still approves the
	// key, but no pin exists for it.
	fx.pinStore = keypinning.NewMemoryStore()
	req := fx.request(t)

	outcome, err := ExecuteGenesis(context.Background(), fx.deps(), req, fx.now)
	if outcome != OutcomeRejected {
		t.Fatalf("outcome = %s, want REJECTED", outcome)
	}
	if !errors.Is(err, ErrKeyNotPinned) {
		t.Fatalf("err = %v, want ErrKeyNotPinned", err)
	}
	if fx.spanner.commitCalls != 0 {
		t.Fatalf("commitCalls = %d, want 0 (no mutation before a rejected precondition)", fx.spanner.commitCalls)
	}
}

func TestExecuteGenesisTreatsAbortedCommitAsSafeToRetry(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	fx.spanner.commitResponse = nil
	fx.spanner.commitErr = abortedCommitErr()
	req := fx.request(t)

	outcome, err := ExecuteGenesis(context.Background(), fx.deps(), req, fx.now)
	if outcome != OutcomeRejected {
		t.Fatalf("outcome = %s, want REJECTED (explicit abort is UnambiguousNotCommitted -> safe to retry)", outcome)
	}
	if err == nil {
		t.Fatal("expected a non-nil error")
	}
}

func TestExecuteGenesisTreatsAmbiguousCommitAsUnresolved(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	fx.spanner.commitResponse = nil
	fx.spanner.commitErr = ambiguousCommitErr()
	req := fx.request(t)

	outcome, err := ExecuteGenesis(context.Background(), fx.deps(), req, fx.now)
	if outcome != OutcomeUnresolved {
		t.Fatalf("outcome = %s, want UNRESOLVED", outcome)
	}
	if !errors.Is(err, ErrGenesisUnresolved) {
		t.Fatalf("err = %v, want ErrGenesisUnresolved", err)
	}
}

func TestExecuteGenesisRetryAfterCommitSucceedsIsUnresolvedNotDuplicated(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	req := fx.request(t)

	// First Commit succeeds, but the witness write fails (process loss /
	// network blip between Commit and witness completion -- ADR-044 §9).
	fx.witness.useForceCreate = true
	fx.witness.forceCreateOutcome = gcswitness.AmbiguousCreate
	fx.witness.forceCreateErr = errInjected

	first, err := ExecuteGenesis(context.Background(), fx.deps(), req, fx.now)
	if first != OutcomeUnresolved {
		t.Fatalf("first attempt outcome = %s, want UNRESOLVED", first)
	}
	if err == nil {
		t.Fatal("expected a non-nil error")
	}
	if fx.spanner.commitCalls != 1 {
		t.Fatalf("commitCalls = %d, want 1", fx.spanner.commitCalls)
	}

	// A naive retry of the SAME identifiers must never silently succeed a
	// second time (ATTACK_L). The Spanner layer itself now rejects the
	// second Insert, and ExecuteGenesis must not paper over that.
	fx.witness.useForceCreate = false
	fx.spanner.commitErr = alreadyExistsCommitErr()
	fx.spanner.commitResponse = nil

	second, err := ExecuteGenesis(context.Background(), fx.deps(), req, fx.now)
	if second == OutcomeCompleted {
		t.Fatal("retry after a partially-failed genesis must never report COMPLETED")
	}
	if err == nil {
		t.Fatal("expected a non-nil error on retry")
	}
}

func TestExecuteGenesisConflictWhenWitnessHoldsMismatchedContent(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	req := fx.request(t)
	// Plant unrelated content at the exact deterministic witness key this
	// request would use -- simulating an identifier reused across two
	// different, non-idempotent attempts.
	fx.witness.objects[req.WitnessKey()] = []byte("not a committed payload")

	outcome, err := ExecuteGenesis(context.Background(), fx.deps(), req, fx.now)
	if outcome != OutcomeConflict {
		t.Fatalf("outcome = %s, want CONFLICT", outcome)
	}
	if !errors.Is(err, ErrGenesisConflict) {
		t.Fatalf("err = %v, want ErrGenesisConflict", err)
	}
	if fx.spanner.commitCalls != 0 {
		t.Fatalf("commitCalls = %d, want 0 (conflict detected before any Spanner attempt)", fx.spanner.commitCalls)
	}
}
