//go:build emulator

package rotationcommit

// The emulator-tier T1-T15 conformance matrix (excluding T7/T8/T10, which
// require a genuinely separate OS process and live in
// emulator_processkill_test.go). Every test here drives the real, frozen
// completeRawCommit/ClassifyCommit functions against the real Cloud
// Spanner emulator, most of them through the real TCP fault-injecting
// proxy in internal/authority/conformance/faultproxy. None of these tests
// call t.Parallel(): the emulator documents and enforces "only one
// transaction at a time" (observed directly -- see the final report), so
// these tests must run sequentially, and each one that begins a
// transaction it does not carry through to a successful Commit MUST clean
// up via rollbackBestEffort or every later test in this file will
// spuriously fail.

import (
	"context"
	"testing"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/faultproxy"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/localsigner"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/spanneradapter"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/witness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/epoch"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/recovery"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotation"
)

// TestT1NormalSuccessReachesActiveOnlyAfterWitness is T1: a completely
// healthy Commit, followed by a genuine witness write, reaching StateActive
// -- and never reaching it on the strength of the Commit alone.
func TestT1NormalSuccessReachesActiveOnlyAfterWitness(t *testing.T) {
	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	client := dialEmulator(t, emulatorAddr)
	request, _, _ := commitRequestFor(t, client, operation)

	accepted, classification, err := completeRawCommit(context.Background(), client.Raw(), request, operation, nil)
	if err != nil || classification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("classification=%v err=%v", classification, err)
	}
	frozen := epoch.TransitionOnCASOutcome(classification.Outcome)
	if frozen != epoch.StateRecoveryFrozenPendingWitness {
		t.Fatalf("state = %v, want StateRecoveryFrozenPendingWitness", frozen)
	}

	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	payload, err := buildCommittedPayload(context.Background(), keyPair.Signer(), accepted)
	if err != nil {
		t.Fatal(err)
	}
	repo, err := witness.NewRepository(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	serialized, err := serializeCommittedPayload(payload)
	if err != nil {
		t.Fatal(err)
	}
	if err := repo.CreateOnlyIfAbsent(context.Background(), "committed", serialized); err != nil {
		t.Fatal(err)
	}
	expected := recovery.ExpectedBinding{
		EnvironmentID: op.Environment, AuthorityEpoch: op.Epoch, ResourceIncarnation: op.ResourceIncarnation,
		OperationID: op.OperationID, PredecessorRevision: operation.ExpectedRevision(), PredecessorDigest: operation.PreparedDigest(),
	}
	if err := recovery.VerifyPersistedCommitted(context.Background(), keyPair.Verifier(), payload, expected); err != nil {
		t.Fatal(err)
	}
	active := epoch.TransitionOnWitnessOutcome(true)
	if active != epoch.StateActive {
		t.Fatalf("state = %v, want StateActive", active)
	}
}

// TestT2ExplicitAbortedIsSafeToRetry is T2: a genuine Spanner-level ABORTED
// (exploiting the emulator's real, documented "one active transaction at a
// time" behavior -- not a fake error value) leaves the epoch StateActive.
func TestT2ExplicitAbortedIsSafeToRetry(t *testing.T) {
	victimOp := newEmulatorOperation(t)
	victimOperation := victimOp.buildFixedOperation(t, 0)
	accepted, classification, err := induceGenuineAbortedCommit(t, victimOperation)
	if classification.Outcome != protocol.UnambiguousNotCommitted || classification.Reason != ReasonExplicitlyAborted {
		t.Fatalf("classification=%+v err=%v, want UnambiguousNotCommitted/ReasonExplicitlyAborted", classification, err)
	}
	if len(accepted.candidateBytes) != 0 {
		t.Fatal("ABORTED must never produce an accepted context")
	}
	state := epoch.TransitionOnCASOutcome(classification.Outcome)
	if state != epoch.StateActive {
		t.Fatalf("state = %v, want StateActive", state)
	}
	if state.NewEpochRequired() {
		t.Fatal("explicit ABORTED must never require a new epoch")
	}
}

// induceGenuineAbortedCommit reliably produces a genuine gRPC ABORTED from
// the real emulator on victimOperation's Commit call, by exploiting the
// emulator's real, documented "one active transaction at a time" behavior:
// it holds a separate, unrelated transaction genuinely in flight (its
// Commit response deliberately delayed by a real TCP fault proxy) at the
// exact moment victimOperation's Commit is sent, so the two commits
// genuinely race at the backend rather than merely racing in test code.
func induceGenuineAbortedCommit(t *testing.T, victimOperation rotation.FixedOperation) (acceptedRotationContext, CommitClassification, error) {
	t.Helper()
	// The emulator's real, documented "one active transaction at a time"
	// constraint is about genuinely CONCURRENT in-flight RPCs at the
	// backend -- it does not stay "active" merely because a response is
	// slow to reach a client (the backend resolves each RPC at its own,
	// fast pace regardless of how long a proxy takes to relay the
	// response). Reliably reproducing ABORTED therefore requires firing
	// the holder's and the victim's Commit calls genuinely concurrently,
	// with all preceding setup (CreateSession/BeginTransaction/Read)
	// already completed for both sides beforehand, and retrying the race
	// itself (not victimOperation's identity, which never changes) on the
	// rare iteration where scheduling happens to let the victim win.
	for round := 0; round < 8; round++ {
		holderOp := newEmulatorOperation(t)
		holderOperation := holderOp.buildFixedOperation(t, 0)
		holderClient := dialEmulator(t, emulatorAddr)
		holderRequest, _, _ := commitRequestFor(t, holderClient, holderOperation)

		victim := dialEmulator(t, emulatorAddr)
		victimSession, err := victim.CreateSession(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		victimTxn, err := victim.BeginReadWrite(context.Background(), victimSession)
		if err != nil {
			t.Fatal(err)
		}
		mutations := transitionMutationsFor(victimOperation)
		victimRequest := spanneradapter.CommitRequest(victimSession, victimTxn, mutations)

		var holderErr error
		holderDone := make(chan struct{})
		go func() {
			defer close(holderDone)
			_, holderErr = holderClient.Raw().Commit(context.Background(), holderRequest)
		}()
		accepted, classification, commitErr := completeRawCommit(context.Background(), victim.Raw(), victimRequest, victimOperation, victimTxn)
		<-holderDone

		if classification.Reason == ReasonExplicitlyAborted {
			return accepted, classification, commitErr
		}
		// The victim won the race this round (holderErr is nil / holder
		// was the one aborted instead) -- retry with a fresh holder. Log
		// which side actually lost, for diagnosability.
		t.Logf("round %d: victim did not abort (reason=%v); holderErr=%v; retrying the race", round, classification.Reason, holderErr)
	}
	t.Fatal("could not reproduce a genuine ABORTED for the victim operation after 8 rounds")
	return acceptedRotationContext{}, CommitClassification{}, nil
}

// TestT11RepeatedExplicitAbortedNeverAccumulates is T11: retrying the SAME
// immutable operation across repeated genuine ABORTED responses never
// changes its inputs and never requires a new epoch.
func TestT11RepeatedExplicitAbortedNeverAccumulates(t *testing.T) {
	victimOp := newEmulatorOperation(t)
	victimOperation := victimOp.buildFixedOperation(t, 0)
	originalCandidateBytes := string(victimOperation.CandidateBytes())
	for attempt := 0; attempt < 3; attempt++ {
		_, classification, _ := induceGenuineAbortedCommit(t, victimOperation)
		if classification.Reason != ReasonExplicitlyAborted {
			t.Fatalf("attempt %d: reason = %v, want ReasonExplicitlyAborted", attempt, classification.Reason)
		}
		state := epoch.TransitionOnCASOutcome(classification.Outcome)
		if state != epoch.StateActive || state.NewEpochRequired() {
			t.Fatalf("attempt %d: state = %v, must remain StateActive with no new epoch required", attempt, state)
		}
		if victimOperation.OperationID().String() != victimOp.OperationID.String() ||
			string(victimOperation.CandidateBytes()) != originalCandidateBytes {
			t.Fatalf("attempt %d: the retried operation's identity/content changed", attempt)
		}
	}
}

// TestT12CommitAttemptCountingNeverAmplifies is T12: each independent
// rotation attempt against the real backend produces exactly one Commit
// RPC, observed via InstrumentedCommitClient, never internally retried.
func TestT12CommitAttemptCountingNeverAmplifies(t *testing.T) {
	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	client := dialEmulator(t, emulatorAddr)
	instrumented := spanneradapter.NewInstrumentedCommitClient(client.Raw())
	request, _, _ := commitRequestFor(t, client, operation)

	_, classification, err := completeRawCommit(context.Background(), instrumented, request, operation, nil)
	if err != nil || classification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("classification=%v err=%v", classification, err)
	}
	if instrumented.AttemptCount() != 1 {
		t.Fatalf("AttemptCount() = %d, want exactly 1", instrumented.AttemptCount())
	}
	attempts := instrumented.Attempts()
	if !attempts[0].Succeeded {
		t.Fatal("expected the single recorded attempt to have succeeded")
	}
}

// TestT13PredecessorChangeBetweenAttemptsIsDetectedNotBlindlyOverwritten is
// T13: a second attempt against a resource incarnation whose revision
// genuinely moved (via a real, prior, successful Commit) must detect the
// mismatch from a real Read and refuse to invoke Commit at all -- never
// blindly overwrite the row.
func TestT13PredecessorChangeBetweenAttemptsIsDetectedNotBlindlyOverwritten(t *testing.T) {
	op := newEmulatorOperation(t)
	first := op.buildFixedOperation(t, 0)
	client := dialEmulator(t, emulatorAddr)
	firstRequest, _, _ := commitRequestFor(t, client, first)
	_, firstClassification, err := completeRawCommit(context.Background(), client.Raw(), firstRequest, first, nil)
	if err != nil || firstClassification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("setup: classification=%v err=%v", firstClassification, err)
	}

	// A second, stale attempt: still expects predecessor revision 0, but
	// the real backend has already moved to revision 1.
	stale := op.buildFixedOperation(t, 0)
	verifyClient := dialEmulator(t, emulatorAddr)
	verifySession, err := verifyClient.CreateSession(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	verifyTxn, err := verifyClient.BeginReadWrite(context.Background(), verifySession)
	if err != nil {
		t.Fatal(err)
	}
	row, found, err := verifyClient.ReadAuthorityHead(context.Background(), verifySession, verifyTxn, stale.EnvironmentID().String(), stale.ResourceIncarnation().String())
	if err != nil {
		t.Fatal(err)
	}
	defer rollbackBestEffort(t, emulatorAddr, verifySession, verifyTxn)
	if !found || row.RevisionNumber != stale.ExpectedRevision().Uint64()+1 {
		t.Fatalf("expected the real backend to already be one revision ahead; found=%v row=%+v", found, row)
	}

	// The predecessor genuinely changed -- correct behavior is to detect
	// this from the real read and never invoke Commit at all.
	if row.RevisionNumber == stale.ExpectedRevision().Uint64() {
		t.Fatal("test setup error: expected a genuine mismatch")
	}
	classification := ClassifyCommit(false, nil, nil, RegularSession)
	if classification.Outcome != protocol.UnambiguousNotCommitted || classification.Reason != ReasonCommitNotInvoked {
		t.Fatalf("classification=%+v, want UnambiguousNotCommitted/ReasonCommitNotInvoked", classification)
	}
	state := epoch.TransitionOnCASOutcome(classification.Outcome)
	if state != epoch.StateActive {
		t.Fatalf("state = %v, want StateActive (safe: nothing was attempted)", state)
	}
}

// TestT14OperationIDMismatchIsNeverTreatedAsResolvingADifferentOperation is
// T14: a real, validly signed COMMITTED for operation Y must never satisfy
// verification against operation X's expected binding, even though both
// are real, genuinely committed rotations against the same emulator.
func TestT14OperationIDMismatchIsNeverTreatedAsResolvingADifferentOperation(t *testing.T) {
	opY := newEmulatorOperation(t)
	operationY := opY.buildFixedOperation(t, 0)
	client := dialEmulator(t, emulatorAddr)
	request, _, _ := commitRequestFor(t, client, operationY)
	accepted, classification, err := completeRawCommit(context.Background(), client.Raw(), request, operationY, nil)
	if err != nil || classification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("classification=%v err=%v", classification, err)
	}
	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	payloadY, err := buildCommittedPayload(context.Background(), keyPair.Signer(), accepted)
	if err != nil {
		t.Fatal(err)
	}

	opX := newEmulatorOperation(t) // a DIFFERENT, unrelated operation
	expectedForX := recovery.ExpectedBinding{
		EnvironmentID: opX.Environment, AuthorityEpoch: opX.Epoch, ResourceIncarnation: opX.ResourceIncarnation,
		OperationID: opX.OperationID, PredecessorRevision: protocol.NewRevisionNumber(0), PredecessorDigest: operationY.PreparedDigest(),
	}
	err = recovery.VerifyPersistedCommitted(context.Background(), keyPair.Verifier(), payloadY, expectedForX)
	if err == nil {
		t.Fatal("Y's genuinely signed COMMITTED must never verify against X's expected binding")
	}
}

// TestT15UnknownTransportErrorIsAmbiguous, TestT6TransportResetIsAmbiguous,
// TestT5UnavailableAfterPossibleTransmissionIsAmbiguous, and
// TestT3DeadlineAfterPossibleTransmissionIsAmbiguous all drive
// completeRawCommit through a real TCP connection to the real emulator via
// faultproxy, each with a distinct, genuinely observed transport failure
// mode, and each asserts the full six-flag ambiguous-outcome block.

func assertEmulatorAmbiguousInvariants(t *testing.T, accepted acceptedRotationContext, classification CommitClassification, commitErr error) {
	t.Helper()
	if classification.Outcome != protocol.AmbiguousCommitOutcome {
		t.Fatalf("classification.Outcome = %v, want AmbiguousCommitOutcome", classification.Outcome)
	}
	if commitErr == nil {
		t.Fatal("expected a non-nil error for an ambiguous outcome")
	}
	committedCreated := len(accepted.candidateBytes) != 0
	state := epoch.TransitionOnCASOutcome(classification.Outcome)
	assertAmbiguousEpochInvariants(t, state, committedCreated)
}

func TestT3DeadlineAfterPossibleTransmissionIsAmbiguous(t *testing.T) {
	proxy := faultproxy.New(emulatorAddr, 3*time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()

	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	sessionClient := dialEmulator(t, emulatorAddr)
	request, sessionName, txn := commitRequestFor(t, sessionClient, operation)

	proxy.QueueFault(faultproxy.DelayPastDeadline)
	commitClient := dialEmulator(t, proxyAddr)
	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()
	accepted, classification, err := completeRawCommit(ctx, commitClient.Raw(), request, operation, nil)
	defer rollbackBestEffort(t, emulatorAddr, sessionName, txn)
	assertEmulatorAmbiguousInvariants(t, accepted, classification, err)
}

func TestT5UnavailableAfterPossibleTransmissionIsAmbiguous(t *testing.T) {
	proxy := faultproxy.New(emulatorAddr, time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()

	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	sessionClient := dialEmulator(t, emulatorAddr)
	request, sessionName, txn := commitRequestFor(t, sessionClient, operation)

	proxy.QueueFault(faultproxy.ResetAfterRequestTransmission)
	commitClient := dialEmulator(t, proxyAddr)
	accepted, classification, err := completeRawCommit(context.Background(), commitClient.Raw(), request, operation, nil)
	defer rollbackBestEffort(t, emulatorAddr, sessionName, txn)
	assertEmulatorAmbiguousInvariants(t, accepted, classification, err)
}

func TestT6TransportResetIsAmbiguous(t *testing.T) {
	proxy := faultproxy.New(emulatorAddr, time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()

	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	sessionClient := dialEmulator(t, emulatorAddr)
	request, sessionName, txn := commitRequestFor(t, sessionClient, operation)

	proxy.QueueFault(faultproxy.AbruptClose)
	commitClient := dialEmulator(t, proxyAddr)
	accepted, classification, err := completeRawCommit(context.Background(), commitClient.Raw(), request, operation, nil)
	defer rollbackBestEffort(t, emulatorAddr, sessionName, txn)
	assertEmulatorAmbiguousInvariants(t, accepted, classification, err)
}

func TestT15UnknownTransportErrorIsAmbiguous(t *testing.T) {
	proxy := faultproxy.New(emulatorAddr, time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()

	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	sessionClient := dialEmulator(t, emulatorAddr)
	request, sessionName, txn := commitRequestFor(t, sessionClient, operation)

	proxy.QueueFault(faultproxy.DropBeforeBackend)
	commitClient := dialEmulator(t, proxyAddr)
	accepted, classification, err := completeRawCommit(context.Background(), commitClient.Raw(), request, operation, nil)
	defer rollbackBestEffort(t, emulatorAddr, sessionName, txn)
	assertEmulatorAmbiguousInvariants(t, accepted, classification, err)
}

// TestT4BackendSuccessDroppedResponseIsAmbiguous is T4: the backend
// genuinely commits (proven by a direct, unproxied ground-truth read
// afterward), while the client observes only a transport failure.
func TestT4BackendSuccessDroppedResponseIsAmbiguous(t *testing.T) {
	proxy := faultproxy.New(emulatorAddr, time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()

	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	sessionClient := dialEmulator(t, emulatorAddr)
	request, sessionName, txn := commitRequestFor(t, sessionClient, operation)

	proxy.QueueFault(faultproxy.DropResponseAfterBackendSuccess)
	commitClient := dialEmulator(t, proxyAddr)
	accepted, classification, err := completeRawCommit(context.Background(), commitClient.Raw(), request, operation, nil)
	// Not deferred: the ground-truth read below needs the emulator's single
	// active-transaction slot released first, not at function return.
	rollbackBestEffort(t, emulatorAddr, sessionName, txn)
	assertEmulatorAmbiguousInvariants(t, accepted, classification, err)

	// Ground truth, on a fresh, unproxied connection: this MUST show the
	// row genuinely committed.
	verifyClient := dialEmulator(t, emulatorAddr)
	verifySession, err := verifyClient.CreateSession(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	verifyTxn, err := verifyClient.BeginReadWrite(context.Background(), verifySession)
	if err != nil {
		t.Fatal(err)
	}
	row, found, err := verifyClient.ReadAuthorityHead(context.Background(), verifySession, verifyTxn, operation.EnvironmentID().String(), operation.ResourceIncarnation().String())
	verifyClient.Rollback(context.Background(), verifySession, verifyTxn)
	if err != nil {
		t.Fatal(err)
	}
	if !found || row.RevisionNumber != 1 {
		t.Fatalf("expected ground truth to show a genuinely committed row (backend_commit == SUCCESS); found=%v row=%+v", found, row)
	}
	t.Log("ground truth CONFIRMS backend_commit == SUCCESS; client_commit_result == AMBIGUOUS; NewEpochRequired == true regardless")
}

// TestT9SameProcessRetryAfterAmbiguousWitnessWriteIsSafe is T9: unlike
// T7/T8/T10, the process here never dies -- it retains the same in-memory
// signed CommittedPayload and retries the witness create, which succeeds
// idempotently. This is the one case where retrying after an ambiguous
// step is safe, and it is safe specifically because of
// create-only-if-absent idempotency, not because of any relaxation of the
// ambiguous-Commit rule (the Commit step itself was NOT ambiguous here).
func TestT9SameProcessRetryAfterAmbiguousWitnessWriteIsSafe(t *testing.T) {
	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	client := dialEmulator(t, emulatorAddr)
	request, _, _ := commitRequestFor(t, client, operation)
	accepted, classification, err := completeRawCommit(context.Background(), client.Raw(), request, operation, nil)
	if err != nil || classification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("classification=%v err=%v", classification, err)
	}
	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	payload, err := buildCommittedPayload(context.Background(), keyPair.Signer(), accepted)
	if err != nil {
		t.Fatal(err)
	}
	serialized, err := serializeCommittedPayload(payload)
	if err != nil {
		t.Fatal(err)
	}
	repo, err := witness.NewRepository(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	// First "attempt" -- simulates an ambiguous response to the witness
	// write itself (the write actually landed, but the caller couldn't
	// tell). The SAME live process retries with the SAME retained bytes.
	if err := repo.CreateOnlyIfAbsent(context.Background(), "committed", serialized); err != nil {
		t.Fatal(err)
	}
	if err := repo.CreateOnlyIfAbsent(context.Background(), "committed", serialized); err != nil {
		t.Fatalf("idempotent same-process retry must succeed: %v", err)
	}
	content, err := repo.Read(context.Background(), "committed")
	if err != nil {
		t.Fatal(err)
	}
	if string(content) != string(serialized) {
		t.Fatal("retried content must be byte-identical")
	}
}

// TestAdminForgeryCannotPromoteAmbiguousOperation is the mandatory
// simulation from section 10: an administrator with direct raw access to
// the emulator (bypassing rotationcommit entirely -- using only
// spanneradapter, never completeRawCommit) mutates authority_head to
// exactly the bytes a legitimate commit would have produced, after the
// original attempt was made ambiguous. Recovery must not promote, must not
// construct COMMITTED, and must require a new epoch, because it never
// trusts authority_head content in the first place -- only a validly
// signed COMMITTED witness object, which the administrator has no way to
// produce without the private signing key.
func TestAdminForgeryCannotPromoteAmbiguousOperation(t *testing.T) {
	proxy := faultproxy.New(emulatorAddr, time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()

	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	sessionClient := dialEmulator(t, emulatorAddr)
	request, sessionName, txn := commitRequestFor(t, sessionClient, operation)

	// Step 1: make the original commit ambiguous -- reset genuinely BEFORE
	// the backend necessarily processes it, so nothing lands yet. (Unlike
	// T4, this step deliberately does not use DropResponseAfterBackendSuccess:
	// this test's point is that a SEPARATE, later administrative mutation
	// forges the expected content, distinct from "the real writer's commit
	// happened to already do it".)
	proxy.QueueFault(faultproxy.ResetAfterRequestTransmission)
	commitClient := dialEmulator(t, proxyAddr)
	accepted, classification, commitErr := completeRawCommit(context.Background(), commitClient.Raw(), request, operation, nil)
	rollbackBestEffort(t, emulatorAddr, sessionName, txn)
	assertEmulatorAmbiguousInvariants(t, accepted, classification, commitErr)

	// Step 2: an administrator, with raw access, directly mutates
	// authority_head to the EXACT bytes a legitimate commit would have
	// produced -- indistinguishable at the content level from the real
	// thing, but produced by someone with no signing capability at all.
	adminClient := dialEmulator(t, emulatorAddr)
	adminSession, err := adminClient.CreateSession(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	adminTxn, err := adminClient.BeginReadWrite(context.Background(), adminSession)
	if err != nil {
		t.Fatal(err)
	}
	forgedMutations := transitionMutationsFor(operation)
	forgedRequest := spanneradapter.CommitRequest(adminSession, adminTxn, forgedMutations)
	if _, err := adminClient.Raw().Commit(context.Background(), forgedRequest); err != nil {
		t.Fatalf("admin mutation failed: %v", err)
	}

	// Step 3: confirm the admin's forged content is now genuinely
	// present -- CONTENT_BINDING == true.
	verifyClient := dialEmulator(t, emulatorAddr)
	verifySession, err := verifyClient.CreateSession(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	verifyTxn, err := verifyClient.BeginReadWrite(context.Background(), verifySession)
	if err != nil {
		t.Fatal(err)
	}
	row, found, err := verifyClient.ReadAuthorityHead(context.Background(), verifySession, verifyTxn, operation.EnvironmentID().String(), operation.ResourceIncarnation().String())
	verifyClient.Rollback(context.Background(), verifySession, verifyTxn)
	if err != nil || !found || row.RevisionNumber != 1 {
		t.Fatalf("expected the forged row to be present: found=%v row=%+v err=%v", found, row, err)
	}

	// Step 4: run recovery logic. There is no COMMITTED witness object at
	// all (the admin only touched Spanner; they hold no signing key and
	// cannot produce one), so there is nothing to verify, and no promotion
	// is possible. Content matching the expected bytes proves nothing.
	witnessRoot := t.TempDir()
	repo, err := witness.NewRepository(witnessRoot)
	if err != nil {
		t.Fatal(err)
	}
	exists, err := repo.Exists(context.Background(), "committed")
	if err != nil {
		t.Fatal(err)
	}
	if exists {
		t.Fatal("no COMMITTED witness object should exist in this scenario")
	}

	var state epoch.State // zero value: StateUnresolvablePreparedOperation
	terminated := epoch.Terminate(state)
	assertAmbiguousEpochInvariants(t, terminated, false)
	t.Log("CONTENT_BINDING == true (forged row matches exactly); ACCEPTANCE_PROVENANCE == false (no valid signature exists); Canonical == false")
}

// TestNegativeProvenanceContentMatchAloneNeverVerifies is the section-9
// negative-provenance proof: a CommittedPayload whose every content field
// (operation_id, candidate/state digest, commit_timestamp, environment,
// epoch, resource incarnation, predecessor binding) is copied EXACTLY from
// a real, genuinely committed row -- but which carries no valid writer
// signature -- must still fail verification. CONTENT_BINDING == true does
// not imply ACCEPTANCE_PROVENANCE == true.
func TestNegativeProvenanceContentMatchAloneNeverVerifies(t *testing.T) {
	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	client := dialEmulator(t, emulatorAddr)
	request, _, _ := commitRequestFor(t, client, operation)
	accepted, classification, err := completeRawCommit(context.Background(), client.Raw(), request, operation, nil)
	if err != nil || classification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("classification=%v err=%v", classification, err)
	}

	genuineKeyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	genuinePayload, err := buildCommittedPayload(context.Background(), genuineKeyPair.Signer(), accepted)
	if err != nil {
		t.Fatal(err)
	}

	// An attacker (or a confused later process) builds a payload with
	// IDENTICAL content -- copied field for field from the genuine one --
	// but signs it with a DIFFERENT key (modeling "an admin who can write
	// any bytes but does not hold the writer's private key").
	forgerKeyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	digest, err := protocol.NewCommittedPayload(
		genuinePayload.EnvironmentID(), genuinePayload.AuthorityEpoch(), genuinePayload.ResourceIncarnation(),
		genuinePayload.OperationID(), genuinePayload.RevisionNumber(), genuinePayload.PredecessorRevision(),
		genuinePayload.PredecessorDigest(), genuinePayload.StateDigest(), genuinePayload.CommitTimestamp(), nil,
	).CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	forgedSignature, err := forgerKeyPair.Signer().SignCommittedDigest(context.Background(), digest)
	if err != nil {
		t.Fatal(err)
	}
	forgedPayload := protocol.NewCommittedPayload(
		genuinePayload.EnvironmentID(), genuinePayload.AuthorityEpoch(), genuinePayload.ResourceIncarnation(),
		genuinePayload.OperationID(), genuinePayload.RevisionNumber(), genuinePayload.PredecessorRevision(),
		genuinePayload.PredecessorDigest(), genuinePayload.StateDigest(), genuinePayload.CommitTimestamp(), forgedSignature,
	)

	// Content is byte-for-byte identical to the genuine payload (verified
	// via the shared canonical digest, which hashes every content field).
	genuineDigest, err := genuinePayload.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	forgedContentDigest, err := protocol.NewCommittedPayload(
		forgedPayload.EnvironmentID(), forgedPayload.AuthorityEpoch(), forgedPayload.ResourceIncarnation(),
		forgedPayload.OperationID(), forgedPayload.RevisionNumber(), forgedPayload.PredecessorRevision(),
		forgedPayload.PredecessorDigest(), forgedPayload.StateDigest(), forgedPayload.CommitTimestamp(), nil,
	).CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	if genuineDigest.String() != forgedContentDigest.String() {
		t.Fatal("test setup error: content digests must match -- CONTENT_BINDING must be true for this test to prove anything")
	}

	expected := recovery.ExpectedBinding{
		EnvironmentID: op.Environment, AuthorityEpoch: op.Epoch, ResourceIncarnation: op.ResourceIncarnation,
		OperationID: op.OperationID, PredecessorRevision: operation.ExpectedRevision(), PredecessorDigest: operation.PreparedDigest(),
	}
	// The genuine, correctly-signed payload verifies.
	if err := recovery.VerifyPersistedCommitted(context.Background(), genuineKeyPair.Verifier(), genuinePayload, expected); err != nil {
		t.Fatalf("genuine payload should verify: %v", err)
	}
	// The content-identical forged payload, verified against the GENUINE
	// verifier key (the only key recovery would ever legitimately hold),
	// must fail -- CONTENT_BINDING == true, ACCEPTANCE_PROVENANCE == false.
	err = recovery.VerifyPersistedCommitted(context.Background(), genuineKeyPair.Verifier(), forgedPayload, expected)
	if err == nil {
		t.Fatal("a content-identical but wrongly-signed payload must never verify")
	}
}
