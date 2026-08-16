// Package epoch models the ADR-043 authority-epoch state machine. It has no
// provider dependency: it operates purely on protocol.CommitOutcome values
// and boolean facts supplied by callers (e.g. rotationcommit), and performs
// no Spanner or GCS calls itself.
package epoch

import "github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"

// State is the security state of one authority epoch or in-flight rotation.
type State uint8

const (
	// StateUnresolvablePreparedOperation is the zero value: the safest
	// possible default. Any epoch/operation whose state has not been
	// affirmatively established as anything else is maximally untrusted --
	// no recovery, rotation, fence release, or PostgreSQL reconciliation is
	// permitted, and a new epoch is required.
	StateUnresolvablePreparedOperation State = iota

	// StateActive is the only state in which the epoch may be used for any
	// authority-dependent decision.
	StateActive

	// StatePrepared reflects a durably written GCS intent object for a
	// candidate transition whose Spanner CAS attempt has not yet been made
	// or whose outcome is not yet known to this state.
	StatePrepared

	// StateRecoveryFrozenPendingWitness is reached the instant a Spanner CAS
	// is classified UnambiguousSuccess. No authority-dependent decision may
	// be made in this state -- not even one based on the prior, still
	// witnessed revision -- until the same-operation COMMITTED witness
	// write completes and validates.
	StateRecoveryFrozenPendingWitness

	// StateEpochTerminated is the formal, permanent closure of an epoch
	// following an unresolvable operation: an AmbiguousOperationTombstone
	// and EpochTerminationRecord are required before this state is reached
	// in a real deployment. In this provider-independent phase, Terminate
	// performs no I/O; callers are responsible for having recorded (or, in
	// tests, simulated) that evidence first.
	StateEpochTerminated
)

func (s State) String() string {
	switch s {
	case StateActive:
		return "ACTIVE"
	case StatePrepared:
		return "PREPARED"
	case StateRecoveryFrozenPendingWitness:
		return "RECOVERY_FROZEN_PENDING_WITNESS"
	case StateEpochTerminated:
		return "EPOCH_TERMINATED"
	default:
		return "UNRESOLVABLE_PREPARED_OPERATION"
	}
}

// RecoveryAllowed reports whether a recovery decision may be made using this
// epoch's current state. Only StateActive permits this.
func (s State) RecoveryAllowed() bool { return s == StateActive }

// RotationAllowed reports whether a new rotation may be attempted against
// this epoch's current state as predecessor. Only StateActive permits this;
// in every other state, a CAS predicated on this epoch's assumed predecessor
// would either be unsafe to attempt or would fail at the Spanner layer
// regardless.
func (s State) RotationAllowed() bool { return s == StateActive }

// FenceReleaseAllowed reports whether recovery fencing may be released based
// on this epoch's current state.
func (s State) FenceReleaseAllowed() bool { return s == StateActive }

// PostgreSQLReconciliationAllowed reports whether PostgreSQL-side refresh
// state reconciliation may proceed based on this epoch's current state.
func (s State) PostgreSQLReconciliationAllowed() bool { return s == StateActive }

// NewEpochRequired reports whether this epoch can never be safely resumed
// and a new epoch's genesis must be established through the governed
// NEW_EPOCH_REQUIRED procedure.
func (s State) NewEpochRequired() bool {
	return s == StateUnresolvablePreparedOperation || s == StateEpochTerminated
}

// TransitionOnCASOutcome computes the resulting state after a Spanner CAS
// attempt, given only its ADR-043 security classification. It never
// consults, and this package never provides a way to consult, any later
// read of Spanner state to arrive at a different answer: the classification
// alone determines the outcome.
//
//   - UnambiguousSuccess    -> StateRecoveryFrozenPendingWitness (never
//     directly ACTIVE; the same-operation witness write must still
//     complete -- see TransitionOnWitnessOutcome).
//   - UnambiguousNotCommitted (explicit ABORTED, Commit-not-invoked, or the
//     defensive precommit-token result) -> StateActive: nothing changed,
//     safe to retry the same immutable operation.
//   - Anything else (AmbiguousCommitOutcome, or any outcome value this
//     package does not explicitly recognize) -> StateUnresolvablePreparedOperation.
func TransitionOnCASOutcome(outcome protocol.CommitOutcome) State {
	switch outcome {
	case protocol.UnambiguousSuccess:
		return StateRecoveryFrozenPendingWitness
	case protocol.UnambiguousNotCommitted:
		return StateActive
	default:
		return StateUnresolvablePreparedOperation
	}
}

// TransitionOnWitnessOutcome computes the resulting state after an attempt
// to complete the same-operation COMMITTED witness write for a revision
// currently in StateRecoveryFrozenPendingWitness. witnessed must be true
// only when the COMMITTED payload was durably created (or idempotently
// confirmed already to exist) by the same process, from its own retained
// in-memory values, with a validating writer signature -- never merely
// because a later read found something that looks right.
func TransitionOnWitnessOutcome(witnessed bool) State {
	if witnessed {
		return StateActive
	}
	return StateUnresolvablePreparedOperation
}

// Terminate moves an unresolvable operation to its formally terminated
// state. Terminate performs no provider I/O; callers must have already
// recorded (or, in tests, simulated recording) the required
// AmbiguousOperationTombstone and EpochTerminationRecord evidence before
// calling this. Terminate is a no-op (returns the input unchanged) for any
// state other than StateUnresolvablePreparedOperation.
func Terminate(current State) State {
	if current == StateUnresolvablePreparedOperation {
		return StateEpochTerminated
	}
	return current
}
