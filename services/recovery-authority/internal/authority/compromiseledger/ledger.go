// Package compromiseledger implements the ADR-045 §7 compromise/distrust
// ledger semantics: an append-only, audited record of when a previously
// authorized signing key or lineage was declared distrusted, and from what
// effective time, compared against a COMMITTED record's own trusted
// commit_timestamp.
//
// This package answers exactly one question: "is this otherwise-authorized
// subject distrusted for a record with this trusted timestamp?" It does
// NOT answer "what public key corresponds to this identifier" (keypinning's
// job) and does NOT itself perform or gate cryptographic signature
// verification (kmsverifier's job) -- ADR-045 is explicit that none of
// CONTENT_BINDING, KEY_AUTHORIZATION, ACCEPTANCE_PROVENANCE, and this
// ledger's compromise/distrust check may substitute for one another.
//
// Routine rotation is never compromise: this package's Ledger has no
// opinion at all about a key's live ENABLED/DISABLED/DESTROYED state --
// only about explicit, separately declared distrust events. DISABLED !=
// COMPROMISED, DESTROYED does not retroactively invalidate history, and a
// superseded (but not distrusted) lineage is not compromised either --
// none of those states are represented in this package at all, precisely
// because conflating them with compromise was S0's original defect,
// corrected in ADR-045 §7.
//
// ADMINISTRATIVE INDEPENDENCE (ADR-045 §7, property 2) IS NOT, AND CANNOT
// BE, FULLY ESTABLISHED BY THIS PACKAGE ALONE. Real administrative
// independence requires a separately governed writer principal/IAM binding
// distinct from ordinary signing-domain administration -- that is S4
// scope. What this package DOES implement: an append-only, integrity-
// protected data model and durable store that structurally cannot be
// mutated or deleted through its own API (no Delete, no Update, no
// in-place edit of any kind exists anywhere in this package), and a
// tamper-evident hash chain (FileLedger) that makes silent truncation or
// reordering of the log detectable. Whether the principal permitted to
// write to a given deployment of this store is actually independent of
// signing-domain administration is a deployment/IAM fact this code cannot
// see or enforce -- see the S4 classification note in file_ledger.go.
package compromiseledger

import (
	"context"
	"errors"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// DistrustRecord is one append-only compromise/distrust declaration.
type DistrustRecord struct {
	// Subject is the distrusted identifier: either a protocol.SigningKeyID
	// string (key-level distrust) or an approved-lineage identifier such as
	// a CryptoKey resource name (lineage-level distrust, ADR-045 §7D). This
	// package treats both uniformly as opaque strings -- it has no
	// provider-specific parsing logic, matching the same
	// provider-agnostic-core discipline ADR-045 §6 already applies to
	// SigningKeyID itself.
	Subject string
	// EffectiveTime is the point after which any record whose trusted
	// commit_timestamp is at-or-after this time requires manual review
	// (ADR-045 §7). A record signed strictly before EffectiveTime is
	// unaffected by this declaration.
	EffectiveTime time.Time
	// RecordedAt is when the declaration itself was written to the ledger
	// -- audit metadata, never used as the comparison anchor (EffectiveTime
	// is).
	RecordedAt time.Time
	Reason     string
	// RecordedBy identifies the principal that made this declaration, for
	// audit purposes (ADR-045 §7, property 3).
	RecordedBy string
}

var (
	ErrSubjectRequired       = errors.New("compromiseledger: Subject is required")
	ErrEffectiveTimeRequired = errors.New("compromiseledger: EffectiveTime is required")
	ErrRecordedByRequired    = errors.New("compromiseledger: RecordedBy is required")
)

func (r DistrustRecord) validate() error {
	if r.Subject == "" {
		return ErrSubjectRequired
	}
	if r.EffectiveTime.IsZero() {
		return ErrEffectiveTimeRequired
	}
	if r.RecordedBy == "" {
		return ErrRecordedByRequired
	}
	return nil
}

// Status is the tri-state outcome of evaluating a subject's distrust status
// as of a record's trusted timestamp (ADR-045 §7). It is deliberately not a
// boolean: a record at or after a declared distrust-effective-time is
// neither auto-accepted nor auto-rejected by this check alone.
type Status int

const (
	// StatusNotDistrusted means no applicable distrust declaration governs
	// this record -- either none exists for the subject, or every existing
	// declaration's EffectiveTime is strictly after the record's trusted
	// timestamp.
	StatusNotDistrusted Status = iota
	// StatusRequiresManualReview means the record's trusted timestamp is at
	// or after a declared distrust-effective-time for this subject.
	// ADR-045 §7: "not auto-accepted or auto-rejected... SHALL be treated
	// as requiring separate, manual, audited review." Callers MUST NOT
	// treat this as ordinary verification success.
	StatusRequiresManualReview
)

func (s Status) String() string {
	switch s {
	case StatusNotDistrusted:
		return "NOT_DISTRUSTED"
	case StatusRequiresManualReview:
		return "REQUIRES_MANUAL_REVIEW"
	default:
		return "UNKNOWN"
	}
}

// Ledger is an append-only compromise/distrust declaration log.
//
// Every implementation MUST:
//   - never expose any method that edits, deletes, or reorders an existing
//     record (there is deliberately no such method on this interface at
//     all -- an implementation cannot accidentally satisfy it);
//   - fail closed (a non-nil error, never a silent StatusNotDistrusted) if
//     the declarations governing subject cannot be read/established with
//     confidence (ADR-045 §7's fail-closed scope).
type Ledger interface {
	// Declare appends record. Fails validate()'s required-field checks
	// closed; never overwrites or reorders any existing record.
	Declare(ctx context.Context, record DistrustRecord) error
	// Status evaluates subject's distrust status as of asOf (a record's own
	// trusted commit_timestamp -- never wall-clock "now"). asOf MUST be the
	// same value passed to CommittedSignatureVerifier as signedAt.
	Status(ctx context.Context, subject string, asOf time.Time) (Status, error)
}

// EvaluateStatus is the shared, provider-independent tri-state comparison
// (ADR-045 §7) every Ledger implementation's Status method delegates to,
// so this logic is written, tested, and reasoned about exactly once.
func EvaluateStatus(records []DistrustRecord, subject string, asOf time.Time) Status {
	for _, record := range records {
		if record.Subject != subject {
			continue
		}
		if !asOf.Before(record.EffectiveTime) {
			// asOf is at or after EffectiveTime.
			return StatusRequiresManualReview
		}
	}
	return StatusNotDistrusted
}

// SigningKeyIDSubject is a small convenience so callers do not need to
// remember the exact string form a protocol.SigningKeyID must be compared
// as -- Subject is always keyID.String(), with no additional transform.
func SigningKeyIDSubject(keyID protocol.SigningKeyID) string { return keyID.String() }
