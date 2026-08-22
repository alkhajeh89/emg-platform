package compromiseledger

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
)

// GCSLedger is the production, durable realization of Ledger (ADR-045
// §7). Like keypinning.GCSStore, it is composed entirely over
// gcswitness.ImmutableWitness -- the same already-qualified ADR-043/044
// GCS create-if-absent primitive -- rather than introducing a new storage
// integration. Reusing the mechanism is not reusing the trust domain: the
// gcswitness.Adapter this type is constructed with in production MUST be
// bound to a bucket in a THIRD administrative domain, distinct from BOTH
// the signing domain and the authority/witness domain (ADR-045 §7
// property 2: "administratively independent of, and unreachable by,
// ordinary signing-domain administration" -- and, symmetrically, never
// reachable by authority/witness administration either, since either one
// being able to suppress or backdate a distrust declaration would defeat
// the property this ledger exists to provide). iam/manifest.json already
// models this as its own domain ("compromise_ledger"), distinct from
// "signing" and "authority_witness" -- this type is that domain's
// concrete storage realization.
//
// ONE RECORD PER SUBJECT, IMMUTABLE ONCE DECLARED. Nothing in ADR-045 §7
// or in this package's existing DistrustRecord/EvaluateStatus model
// requires supporting more than one declaration per subject -- a
// compromise/distrust declaration is a one-time, irreversible governance
// action ("this subject is distrusted, effective from this time"); there
// is no legitimate operational reason to re-declare the SAME subject
// distrusted a second time with a different effective time, and no
// legitimate reason to ever revise one after the fact (that would itself
// be exactly the suppression/backdating threat §7 exists to prevent). This
// lets GCSLedger use the identical create-if-absent-only, no-LIST-required
// design keypinning.GCSStore already uses: FileLedger's append-only
// hash-chain (needed only because a single growing file has no other way
// to prove no record was altered) is unnecessary here -- GCS object
// immutability, optionally reinforced by Bucket Lock retention exactly
// like the witness bucket, gives a STRONGER tamper-evidence property than
// an application-computed hash chain, enforced by the provider rather than
// by this package's own arithmetic.
type GCSLedger struct {
	witness gcswitness.ImmutableWitness
}

// NewGCSLedger wraps an already-constructed gcswitness.ImmutableWitness
// (in production, a *gcswitness.Adapter bound to the compromise-ledger
// domain's own bucket -- see the package doc above). witness must be
// non-nil.
func NewGCSLedger(witness gcswitness.ImmutableWitness) (*GCSLedger, error) {
	if witness == nil {
		return nil, errors.New("compromiseledger: witness is required")
	}
	return &GCSLedger{witness: witness}, nil
}

// gcsDistrustRecord's EffectiveTime/RecordedAt fields are encoded as
// time.RFC3339Nano strings -- full nanosecond precision, deterministic,
// unambiguous, and UTC-normalized on encode -- matching the same
// full-precision convention protocol.MarshalCommittedPayloadJSON already
// uses for commit_timestamp. This is a deliberate correction (not the
// original design): EffectiveTime is compared, via Declare's own
// conflict-resolution equality check and via EvaluateStatus's Before/asOf
// comparison against a record's real Spanner commit_timestamp (which
// itself carries genuine sub-second TrueTime precision), against
// caller-supplied full-precision time.Time values -- truncating it to
// whole seconds on the wire silently shifted the effective distrust
// boundary earlier by up to one second and broke the documented
// idempotent-retry guarantee for any EffectiveTime with a non-zero
// fractional second (found via real-cloud qualification, Wave 2 Track C).
// This package has no production deployment yet (S3, never released), so
// this field rename is a clean wire-format correction, not a
// backward-compatibility migration: no production-written record with the
// old int64 Unix-second field names exists, or needs to remain readable.
type gcsDistrustRecord struct {
	Subject              string `json:"subject"`
	EffectiveTimeRFC3339 string `json:"effective_time_rfc3339"`
	RecordedAtRFC3339    string `json:"recorded_at_rfc3339"`
	Reason               string `json:"reason"`
	RecordedBy           string `json:"recorded_by"`
}

func gcsLedgerKey(subject string) string {
	// The same deterministic, collision-resistant naming approach
	// keypinning.filenameFor already established for an analogous problem
	// (deriving a filesystem/bucket-safe key from an operator-meaningful
	// but arbitrary-shaped string) -- duplicated here rather than shared,
	// since the two packages must never import each other (see
	// boundary_test.go in both).
	sum := sha256.Sum256([]byte(subject))
	return "distrust/" + base64.RawURLEncoding.EncodeToString(sum[:]) + ".json"
}

// ErrDistrustConflict means a distrust declaration already exists for this
// subject with different substantive content (EffectiveTime or
// RecordedBy) than the one being declared now. Declare never overwrites,
// never resolves this by preferring either record, and never appends a
// second, competing record for the same subject -- an operator who hits
// this must resolve it through governed, audited, out-of-band review, not
// by retrying with different content until one attempt succeeds.
var ErrDistrustConflict = errors.New("compromiseledger: a different distrust declaration already exists for this subject")

// Declare appends record, exactly like FileLedger.Declare, except at a
// deterministic key derived from record.Subject rather than at the end of
// a growing log. A retried Declare call for the same (Subject,
// EffectiveTime, RecordedBy) is treated as idempotent even if Reason or
// RecordedAt differ (free text and wall-clock audit metadata can
// legitimately vary across retries of the same underlying decision);
// anything else differing is ErrDistrustConflict.
func (l *GCSLedger) Declare(ctx context.Context, record DistrustRecord) error {
	if err := record.validate(); err != nil {
		return err
	}
	data, err := json.Marshal(gcsDistrustRecord{
		Subject:              record.Subject,
		EffectiveTimeRFC3339: record.EffectiveTime.UTC().Format(time.RFC3339Nano),
		RecordedAtRFC3339:    record.RecordedAt.UTC().Format(time.RFC3339Nano),
		Reason:               record.Reason,
		RecordedBy:           record.RecordedBy,
	})
	if err != nil {
		return fmt.Errorf("compromiseledger: encode record: %w", err)
	}
	key := gcsLedgerKey(record.Subject)

	outcome, createErr := l.witness.CreateExactIfAbsent(ctx, key, data)
	switch outcome {
	case gcswitness.CreateSuccess, gcswitness.AlreadyExistsIdentical:
		return nil
	case gcswitness.AlreadyExistsConflict:
		existing, readErr := l.readSubject(ctx, record.Subject)
		if readErr != nil {
			return fmt.Errorf("compromiseledger: existing declaration for this subject failed its own integrity check: %w", readErr)
		}
		if !existing.EffectiveTime.Equal(record.EffectiveTime) || existing.RecordedBy != record.RecordedBy {
			return ErrDistrustConflict
		}
		return nil
	default:
		return fmt.Errorf("compromiseledger: gcs declare did not succeed: %w", createErr)
	}
}

func (l *GCSLedger) readSubject(ctx context.Context, subject string) (DistrustRecord, error) {
	data, err := l.witness.ReadExact(ctx, gcsLedgerKey(subject))
	if err != nil {
		if errors.Is(err, gcswitness.ErrNotFound) {
			return DistrustRecord{}, nil
		}
		return DistrustRecord{}, err
	}
	var raw gcsDistrustRecord
	if err := json.Unmarshal(data, &raw); err != nil {
		return DistrustRecord{}, fmt.Errorf("decode record: %w", err)
	}
	if raw.Subject != subject {
		return DistrustRecord{}, fmt.Errorf("stored record's subject %q does not match requested %q -- integrity check failed", raw.Subject, subject)
	}
	// Fail closed on a malformed persisted timestamp: never silently
	// reinterpret it as the zero time, which could otherwise be
	// misclassified as "before" every real EffectiveTime/asOf comparison.
	effectiveTime, err := time.Parse(time.RFC3339Nano, raw.EffectiveTimeRFC3339)
	if err != nil {
		return DistrustRecord{}, fmt.Errorf("stored record has a malformed effective_time_rfc3339: %w", err)
	}
	recordedAt, err := time.Parse(time.RFC3339Nano, raw.RecordedAtRFC3339)
	if err != nil {
		return DistrustRecord{}, fmt.Errorf("stored record has a malformed recorded_at_rfc3339: %w", err)
	}
	return DistrustRecord{
		Subject:       raw.Subject,
		EffectiveTime: effectiveTime.UTC(),
		RecordedAt:    recordedAt.UTC(),
		Reason:        raw.Reason,
		RecordedBy:    raw.RecordedBy,
	}, nil
}

// Status evaluates subject's distrust status as of asOf. It never uses
// LIST, and it fails closed exactly like FileLedger.Status: an unreadable
// (as opposed to simply absent) record is never reported as
// StatusNotDistrusted -- an inability to rule out an undetected compromise
// is itself a verification failure (ADR-045 §7's fail-closed scope).
func (l *GCSLedger) Status(ctx context.Context, subject string, asOf time.Time) (Status, error) {
	exists, err := l.witness.Exists(ctx, gcsLedgerKey(subject))
	if err != nil {
		return StatusNotDistrusted, fmt.Errorf("compromiseledger: check distrust record existence: %w", err)
	}
	if !exists {
		return StatusNotDistrusted, nil
	}
	record, err := l.readSubject(ctx, subject)
	if err != nil {
		return StatusNotDistrusted, fmt.Errorf("compromiseledger: read distrust record: %w", err)
	}
	return EvaluateStatus([]DistrustRecord{record}, subject, asOf), nil
}

var _ Ledger = (*GCSLedger)(nil)
