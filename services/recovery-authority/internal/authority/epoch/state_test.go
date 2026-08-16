package epoch_test

import (
	"testing"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/epoch"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

func TestZeroValueIsMaximallyRestrictive(t *testing.T) {
	t.Parallel()
	var zero epoch.State
	if zero != epoch.StateUnresolvablePreparedOperation {
		t.Fatalf("zero value = %v, want StateUnresolvablePreparedOperation", zero)
	}
	assertNothingAllowed(t, zero)
	if !zero.NewEpochRequired() {
		t.Fatal("zero value must require a new epoch")
	}
}

func TestOnlyActiveAllowsAnything(t *testing.T) {
	t.Parallel()
	states := []epoch.State{
		epoch.StateUnresolvablePreparedOperation,
		epoch.StateActive,
		epoch.StatePrepared,
		epoch.StateRecoveryFrozenPendingWitness,
		epoch.StateEpochTerminated,
	}
	for _, state := range states {
		state := state
		t.Run(state.String(), func(t *testing.T) {
			t.Parallel()
			if state == epoch.StateActive {
				if !state.RecoveryAllowed() || !state.RotationAllowed() ||
					!state.FenceReleaseAllowed() || !state.PostgreSQLReconciliationAllowed() {
					t.Fatal("StateActive must allow every authority-dependent action")
				}
				if state.NewEpochRequired() {
					t.Fatal("StateActive must not require a new epoch")
				}
				return
			}
			assertNothingAllowed(t, state)
		})
	}
}

func assertNothingAllowed(t *testing.T, state epoch.State) {
	t.Helper()
	if state.RecoveryAllowed() {
		t.Fatalf("%v: RecoveryAllowed must be false", state)
	}
	if state.RotationAllowed() {
		t.Fatalf("%v: RotationAllowed must be false", state)
	}
	if state.FenceReleaseAllowed() {
		t.Fatalf("%v: FenceReleaseAllowed must be false", state)
	}
	if state.PostgreSQLReconciliationAllowed() {
		t.Fatalf("%v: PostgreSQLReconciliationAllowed must be false", state)
	}
}

// TestAmbiguousAndUnrecognizedOutcomesAreIndistinguishablyUnsafe proves the
// transition function treats AmbiguousCommitOutcome and any future,
// currently-unrecognized outcome value identically: both fail closed. No
// later evidence -- this function accepts none -- can reverse either.
func TestAmbiguousAndUnrecognizedOutcomesAreIndistinguishablyUnsafe(t *testing.T) {
	t.Parallel()
	unrecognized := protocol.CommitOutcome(200) // not a value this package defines any handling for
	for _, outcome := range []protocol.CommitOutcome{protocol.AmbiguousCommitOutcome, unrecognized} {
		got := epoch.TransitionOnCASOutcome(outcome)
		if got != epoch.StateUnresolvablePreparedOperation {
			t.Fatalf("TransitionOnCASOutcome(%v) = %v, want StateUnresolvablePreparedOperation", outcome, got)
		}
		if !got.NewEpochRequired() {
			t.Fatalf("outcome %v: resulting state must require a new epoch", outcome)
		}
		assertNothingAllowed(t, got)
	}
}

func TestUnambiguousSuccessNeverDirectlyActivates(t *testing.T) {
	t.Parallel()
	got := epoch.TransitionOnCASOutcome(protocol.UnambiguousSuccess)
	if got != epoch.StateRecoveryFrozenPendingWitness {
		t.Fatalf("TransitionOnCASOutcome(UnambiguousSuccess) = %v, want StateRecoveryFrozenPendingWitness", got)
	}
	// The whole point of this intermediate state: nothing is allowed yet,
	// not even by reference to whatever the prior, already-witnessed
	// revision was.
	assertNothingAllowed(t, got)
}

func TestUnambiguousNotCommittedLeavesEpochActive(t *testing.T) {
	t.Parallel()
	got := epoch.TransitionOnCASOutcome(protocol.UnambiguousNotCommitted)
	if got != epoch.StateActive {
		t.Fatalf("TransitionOnCASOutcome(UnambiguousNotCommitted) = %v, want StateActive", got)
	}
}

func TestWitnessOutcomeTransition(t *testing.T) {
	t.Parallel()
	if got := epoch.TransitionOnWitnessOutcome(true); got != epoch.StateActive {
		t.Fatalf("TransitionOnWitnessOutcome(true) = %v, want StateActive", got)
	}
	got := epoch.TransitionOnWitnessOutcome(false)
	if got != epoch.StateUnresolvablePreparedOperation {
		t.Fatalf("TransitionOnWitnessOutcome(false) = %v, want StateUnresolvablePreparedOperation", got)
	}
	if !got.NewEpochRequired() {
		t.Fatal("failed witness completion must require a new epoch")
	}
}

func TestTerminate(t *testing.T) {
	t.Parallel()
	if got := epoch.Terminate(epoch.StateUnresolvablePreparedOperation); got != epoch.StateEpochTerminated {
		t.Fatalf("Terminate(Unresolvable) = %v, want StateEpochTerminated", got)
	}
	if !epoch.StateEpochTerminated.NewEpochRequired() {
		t.Fatal("StateEpochTerminated must require a new epoch")
	}
	assertNothingAllowed(t, epoch.StateEpochTerminated)

	// Terminate is a no-op for any state other than Unresolvable -- in
	// particular it must never be usable to "escape" ACTIVE or freeze
	// states into termination as a side channel.
	for _, state := range []epoch.State{epoch.StateActive, epoch.StatePrepared, epoch.StateRecoveryFrozenPendingWitness, epoch.StateEpochTerminated} {
		if got := epoch.Terminate(state); got != state {
			t.Fatalf("Terminate(%v) = %v, want unchanged %v", state, got, state)
		}
	}
}
