package keypinning

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// GCSStore is the production, durable realization of Store (ADR-045 §7C).
// It is deliberately NOT a new GCS integration: it is composed entirely
// over gcswitness.ImmutableWitness, the same already-qualified ADR-043/044
// create-if-absent primitive the witness boundary uses (real Bucket Lock
// evidence: docs/evidence/adr-043/real-gcp-*-qualification/). Reusing the
// mechanism does not mean reusing the trust domain: the gcswitness.Adapter
// this type is constructed with in production MUST be bound to a bucket
// administered by the SIGNING domain (ADR-045 §5 -- pin capture is a
// signing-domain principal, iam/manifest.json's "recovery-pin-capture"),
// never a bucket the authority/witness domain administers, so that an
// authority/witness administrator has no path -- not even an indirect
// storage-admin path -- to fabricate or replace signing trust material.
// The authority-domain verifier (kmsverifier, inside recovery-authority-runtime)
// is granted only cross-domain READ on that bucket, matching ADR-045 §5's
// "public verification is independent of signing permission."
//
// Every property FileStore already establishes (write-once semantics,
// independent fingerprint re-verification on every read, no Delete/Update
// method anywhere in this package) holds here too -- this type differs
// from FileStore only in NOT being confined to a single node's local
// filesystem, closing FileStore's own documented gap ("NOT implemented
// here, and explicitly deferred to S4... multi-node replication").
type GCSStore struct {
	witness gcswitness.ImmutableWitness
}

// NewGCSStore wraps an already-constructed gcswitness.ImmutableWitness
// (in production, a *gcswitness.Adapter bound to the signing domain's pin
// bucket -- see the package doc above for why that binding is a
// deployment-time, not a code-time, decision). witness must be non-nil.
func NewGCSStore(witness gcswitness.ImmutableWitness) (*GCSStore, error) {
	if witness == nil {
		return nil, errors.New("keypinning: witness is required")
	}
	return &GCSStore{witness: witness}, nil
}

// Pin durably records pin at a deterministic key derived from its
// SigningKeyID (filenameFor, shared with FileStore -- both providers use
// byte-identical on-disk/on-bucket JSON, so operational tooling never
// needs to know which provider produced a given record). CreateExactIfAbsent
// gives the "never silently overwrite" guarantee directly from the
// provider (Attack 22, ADR-045 §13); a byte-level conflict is resolved by
// reading the existing record back and comparing FINGERPRINTS specifically
// -- never raw JSON bytes -- because two genuinely identical captures of
// the same key material can legitimately differ in incidental fields
// (Provenance free text, PinnedAt wall-clock time) without that being a
// real conflict, exactly mirroring FileStore.Pin's own logic.
func (s *GCSStore) Pin(ctx context.Context, pin PinnedKey) error {
	if pin.SigningKeyID.IsZero() {
		return ErrPinRequiresSigningKeyID
	}
	data, err := encodePinRecord(pin)
	if err != nil {
		return err
	}
	key := filenameFor(pin.SigningKeyID)

	outcome, createErr := s.witness.CreateExactIfAbsent(ctx, key, data)
	switch outcome {
	case gcswitness.CreateSuccess, gcswitness.AlreadyExistsIdentical:
		return nil
	case gcswitness.AlreadyExistsConflict:
		existing, getErr := s.Get(ctx, pin.SigningKeyID)
		if getErr != nil {
			return fmt.Errorf("keypinning: existing pin for this SigningKeyID failed its own integrity check: %w", getErr)
		}
		if existing.Fingerprint != pin.Fingerprint {
			return ErrPinConflict
		}
		return nil
	default:
		// AmbiguousCreate or HardFailure: never treated as success, and
		// never resolved by any means other than gcswitness's own
		// already-qualified classification (no alternate key, no retry
		// loop here).
		return fmt.Errorf("keypinning: gcs pin create did not succeed: %w", createErr)
	}
}

// Get reads back pin, independently recomputing its fingerprint from the
// stored material before returning it -- exactly like FileStore.Get, never
// trusting a stored fingerprint value alone.
func (s *GCSStore) Get(ctx context.Context, keyID protocol.SigningKeyID) (PinnedKey, error) {
	key := filenameFor(keyID)
	data, err := s.witness.ReadExact(ctx, key)
	if err != nil {
		if errors.Is(err, gcswitness.ErrNotFound) {
			return PinnedKey{}, ErrPinNotFound
		}
		return PinnedKey{}, fmt.Errorf("keypinning: read pin: %w", err)
	}
	return decodePinRecord(data, keyID)
}

var _ Store = (*GCSStore)(nil)

// encodePinRecord and decodePinRecord share the exact wire shape
// FileStore already uses (pinRecord, defined in file_store.go) so both
// production-grade providers are byte-compatible. The fingerprint
// encode/decode logic is deliberately duplicated from FileStore's own
// Pin/Get, rather than factored into a shared helper both call -- matching
// this codebase's established preference (see
// rotationcommit/genesis.go's relationship to buildCommittedPayload) for
// duplicating a small amount of already-tested logic over restructuring a
// frozen, already-reviewed function's file.
func encodePinRecord(pin PinnedKey) ([]byte, error) {
	record := pinRecord{
		SigningKeyID: pin.SigningKeyID.String(),
		Algorithm:    string(pin.Algorithm),
		PublicKeyPEM: pin.PublicKeyPEM,
		Fingerprint:  base64.StdEncoding.EncodeToString(pin.Fingerprint[:]),
		PinnedAtUnix: pin.PinnedAt.Unix(),
		Provenance:   pin.Provenance,
	}
	data, err := json.Marshal(record)
	if err != nil {
		return nil, fmt.Errorf("keypinning: encode pin: %w", err)
	}
	return data, nil
}

func decodePinRecord(data []byte, keyID protocol.SigningKeyID) (PinnedKey, error) {
	var record pinRecord
	if err := json.Unmarshal(data, &record); err != nil {
		return PinnedKey{}, fmt.Errorf("keypinning: decode pin: %w", err)
	}
	if record.SigningKeyID != keyID.String() {
		return PinnedKey{}, fmt.Errorf("keypinning: stored pin's SigningKeyID %q does not match requested %q -- integrity check failed", record.SigningKeyID, keyID.String())
	}
	storedFingerprint, err := base64.StdEncoding.DecodeString(record.Fingerprint)
	if err != nil || len(storedFingerprint) != 32 {
		return PinnedKey{}, errors.New("keypinning: stored pin has a malformed fingerprint")
	}
	recomputed := computeFingerprint(record.PublicKeyPEM)
	var storedArray [32]byte
	copy(storedArray[:], storedFingerprint)
	if recomputed != storedArray {
		return PinnedKey{}, errors.New("keypinning: stored pin failed integrity check -- fingerprint does not match material")
	}
	return PinnedKey{
		SigningKeyID: keyID,
		Algorithm:    Algorithm(record.Algorithm),
		PublicKeyPEM: record.PublicKeyPEM,
		Fingerprint:  storedArray,
		PinnedAt:     time.Unix(record.PinnedAtUnix, 0).UTC(),
		Provenance:   record.Provenance,
	}, nil
}
