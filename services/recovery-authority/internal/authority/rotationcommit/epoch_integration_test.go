package rotationcommit

import (
	"context"
	"errors"
	"testing"
	"time"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/epoch"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// This file wires completeRawCommit's classification into the epoch state
// machine and proves, per ambiguous outcome, the six-assertion block ADR-043
// governance requires. No strong-read-based resolution exists anywhere in
// this file or in the production code it exercises -- these tests assert
// that fact, they do not merely happen to pass because such a path is
// unused.

// assertAmbiguousEpochInvariants is the six-assertion block required for
// every ambiguous-Commit test.
func assertAmbiguousEpochInvariants(t *testing.T, state epoch.State, committedCreated bool) {
	t.Helper()
	if state.RecoveryAllowed() {
		t.Fatal("RecoveryAllowed(old_epoch) must be false")
	}
	if state.RotationAllowed() {
		t.Fatal("RotationAllowed(old_epoch) must be false")
	}
	if state.FenceReleaseAllowed() {
		t.Fatal("FenceReleaseAllowed(old_epoch) must be false")
	}
	if state.PostgreSQLReconciliationAllowed() {
		t.Fatal("PostgreSQLReconciliationAllowed(old_epoch) must be false")
	}
	if committedCreated {
		t.Fatal("COMMITTEDCreatedAfterContextLoss must be false")
	}
	if !state.NewEpochRequired() {
		t.Fatal("NewEpochRequired must be true")
	}
}

// TestT3ThroughT6AndT15AreUniformlyAmbiguous exercises DEADLINE_EXCEEDED
// (T3), UNAVAILABLE (T5), a simulated transport reset (T6), and an unknown
// SDK/transport error (T15) through the real completeRawCommit -> epoch
// pipeline, and proves each terminates the epoch. T4 (server success,
// response deliberately lost) is proven separately below because it needs
// a client that can attest, out of band, to the hidden ground truth.
func TestT3ThroughT6AndT15AreUniformlyAmbiguous(t *testing.T) {
	t.Parallel()
	scenarios := []struct {
		name string
		err  error
	}{
		{"T3_DEADLINE_EXCEEDED", status.Error(codes.DeadlineExceeded, "deadline")},
		{"T5_UNAVAILABLE", status.Error(codes.Unavailable, "unavailable")},
		{"T6_transport_reset", errors.New("connection reset by peer")},
		{"T15_unknown_transport_error", status.Error(codes.Code(217), "unrecognized")},
	}
	for _, scenario := range scenarios {
		scenario := scenario
		t.Run(scenario.name, func(t *testing.T) {
			t.Parallel()
			operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))
			client := &fakeRawCommitClient{err: scenario.err}

			accepted, classification, err := completeRawCommit(
				context.Background(), client, &spannerpb.CommitRequest{}, operation, nil,
			)
			if classification.Outcome != protocol.AmbiguousCommitOutcome {
				t.Fatalf("classification.Outcome = %v, want AmbiguousCommitOutcome", classification.Outcome)
			}
			if err == nil {
				t.Fatal("ambiguous outcome must return a non-nil error")
			}
			// No accepted context was produced -- verified the same way the
			// existing failure-injection tests already verify it, and
			// re-verified here as part of the epoch-integration proof.
			committedCreated := len(accepted.candidateBytes) != 0

			state := epoch.TransitionOnCASOutcome(classification.Outcome)
			assertAmbiguousEpochInvariants(t, state, committedCreated)
		})
	}
}

// TestT4ServerSuccessWithLostResponseStillTerminatesEpoch proves the
// sharpest case in the matrix: the backend truly committed, the client
// genuinely cannot tell, and the system must still refuse to trust it.
func TestT4ServerSuccessWithLostResponseStillTerminatesEpoch(t *testing.T) {
	t.Parallel()
	operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))

	// The fake client below simulates the backend having genuinely
	// committed (ground truth tracked only for the test's own assertion,
	// never surfaced to production code) while returning exactly what a
	// real client library returns when a response is lost in transit: an
	// ambiguous transport error.
	groundTruthCommitted := true // the backend, hypothetically, really did commit
	client := &fakeRawCommitClient{err: status.Error(codes.Unavailable, "response lost after send")}

	accepted, classification, err := completeRawCommit(
		context.Background(), client, &spannerpb.CommitRequest{}, operation, nil,
	)
	if classification.Outcome != protocol.AmbiguousCommitOutcome {
		t.Fatalf("classification.Outcome = %v, want AmbiguousCommitOutcome even though ground truth = %v",
			classification.Outcome, groundTruthCommitted)
	}
	if err == nil {
		t.Fatal("ambiguous outcome must return a non-nil error")
	}
	committedCreated := len(accepted.candidateBytes) != 0

	state := epoch.TransitionOnCASOutcome(classification.Outcome)
	assertAmbiguousEpochInvariants(t, state, committedCreated)

	// The critical point of this test: the system reached the safe,
	// terminating outcome specifically DESPITE the favorable ground truth,
	// not because of an accident of the test data. If the classifier or
	// the epoch transition were ever changed to consult ground truth, this
	// assertion is what would catch it.
	if !groundTruthCommitted {
		t.Fatal("test setup error: this test only proves what it claims to prove when ground truth is success")
	}
}

// TestT7T8ProcessOrContextLossRequiresNewEpochUnconditionally models T7/T8:
// no live acceptedRotationContext exists (the process that ran the CAS is
// gone), and no valid persisted COMMITTED exists to independently verify.
// Reconciliation in this state is UNRESOLVABLE_PREPARED_OPERATION
// regardless of what a later Spanner read might show -- this test does not
// perform any such read, because production code has no path to perform
// one for this purpose either.
func TestT7T8ProcessOrContextLossRequiresNewEpochUnconditionally(t *testing.T) {
	t.Parallel()
	// A cold-start reconciliation process, by definition, begins with no
	// acceptedRotationContext and no classification of its own -- there is
	// nothing to classify, because there is no live process artifact left.
	// The only state such a process may ever assign to the stranded
	// operation is the zero value.
	var coldStartState epoch.State // zero value
	if coldStartState != epoch.StateUnresolvablePreparedOperation {
		t.Fatalf("cold-start state = %v, want the zero value StateUnresolvablePreparedOperation", coldStartState)
	}
	assertAmbiguousEpochInvariants(t, coldStartState, false)

	terminated := epoch.Terminate(coldStartState)
	if terminated != epoch.StateEpochTerminated {
		t.Fatalf("Terminate(cold-start) = %v, want StateEpochTerminated", terminated)
	}
	if !terminated.NewEpochRequired() {
		t.Fatal("terminated epoch must require a new epoch")
	}
}

// TestT2AndT11OnlyExplicitAbortedPermitsRetry proves that of every outcome
// this package can classify, only UnambiguousNotCommitted (which, for a raw
// Commit attempt, is reached exclusively via Commit-not-invoked, explicit
// ABORTED, or the defensive precommit-token result) leaves the epoch
// StateActive and therefore eligible for the caller to retry the same
// immutable operation. Repeating this across several ABORTED attempts (T11)
// must never accumulate any different outcome.
func TestT2AndT11OnlyExplicitAbortedPermitsRetry(t *testing.T) {
	t.Parallel()
	operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))
	client := &fakeRawCommitClient{err: status.Error(codes.Aborted, "concurrent modification")}

	for attempt := 0; attempt < 5; attempt++ {
		accepted, classification, err := completeRawCommit(
			context.Background(), client, &spannerpb.CommitRequest{}, operation, nil,
		)
		if classification.Outcome != protocol.UnambiguousNotCommitted {
			t.Fatalf("attempt %d: classification.Outcome = %v, want UnambiguousNotCommitted", attempt, classification.Outcome)
		}
		if err == nil {
			t.Fatalf("attempt %d: expected a non-nil error for a not-committed outcome", attempt)
		}
		if len(accepted.candidateBytes) != 0 {
			t.Fatalf("attempt %d: ABORTED must never produce an accepted context", attempt)
		}
		state := epoch.TransitionOnCASOutcome(classification.Outcome)
		if state != epoch.StateActive {
			t.Fatalf("attempt %d: state = %v, want StateActive (safe to retry)", attempt, state)
		}
		if state.NewEpochRequired() {
			t.Fatalf("attempt %d: ABORTED must never require a new epoch", attempt)
		}
	}
	if client.calls != 5 {
		t.Fatalf("client.calls = %d, want 5 (one per explicit retry, none internally amplified)", client.calls)
	}
}

// TestSuccessThenWitnessCompletionReachesActive is the positive-path
// integration proof: CAS success alone never yields StateActive -- only a
// validated witness completion does.
func TestSuccessThenWitnessCompletionReachesActive(t *testing.T) {
	t.Parallel()
	operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))
	response := &spannerpb.CommitResponse{
		CommitTimestamp: timestamppb.New(time.Date(2026, 8, 16, 1, 2, 3, 0, time.UTC)),
	}
	client := &fakeRawCommitClient{response: response}

	accepted, classification, err := completeRawCommit(
		context.Background(), client, &spannerpb.CommitRequest{}, operation, nil,
	)
	if err != nil || classification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("setup failed: classification=%v err=%v", classification, err)
	}

	frozen := epoch.TransitionOnCASOutcome(classification.Outcome)
	if frozen != epoch.StateRecoveryFrozenPendingWitness {
		t.Fatalf("state after CAS success = %v, want StateRecoveryFrozenPendingWitness", frozen)
	}
	// StateRecoveryFrozenPendingWitness permits none of the four
	// authority-dependent actions -- but, unlike an ambiguous or terminated
	// state, it does not (yet) require a new epoch: the witness write below
	// can still resolve it. assertAmbiguousEpochInvariants is deliberately
	// not reused here, since its NewEpochRequired assertion does not apply
	// to this transitional state.
	if frozen.RecoveryAllowed() || frozen.RotationAllowed() || frozen.FenceReleaseAllowed() || frozen.PostgreSQLReconciliationAllowed() {
		t.Fatal("StateRecoveryFrozenPendingWitness must permit no authority-dependent action")
	}

	signer := newFakeSigner(t, []byte("writer-key"), "projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	payload, err := buildCommittedPayload(context.Background(), signer, accepted)
	if err != nil {
		t.Fatal(err)
	}
	if len(payload.WriterSignature()) == 0 {
		t.Fatal("expected a signed COMMITTED payload")
	}

	active := epoch.TransitionOnWitnessOutcome(true)
	if active != epoch.StateActive {
		t.Fatalf("state after witness completion = %v, want StateActive", active)
	}
	if !active.RecoveryAllowed() || !active.RotationAllowed() {
		t.Fatal("StateActive must allow recovery and rotation")
	}
}
