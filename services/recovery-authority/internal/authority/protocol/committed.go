package protocol

import (
	"errors"
	"time"
)

// ErrCommittedSigningKeyIDRequired is returned by NewCommittedPayloadV2 when
// no SigningKeyID is supplied. A V2 payload with no key identifier is not a
// degraded V2 record -- it is not a valid V2 record at all (ADR-045 §8).
var ErrCommittedSigningKeyIDRequired = errors.New("committed payload V2 requires a non-zero signing key ID")

// CommittedPayload is the canonical, witnessable record of one accepted
// ADR-043 authority rotation. It is a plain data record: any package may
// construct or read one. Trust in a CommittedPayload never comes from who
// constructed the Go value -- it comes from independently recomputing
// CanonicalDigest and verifying WriterSignature against it, which is the
// caller's responsibility (see the recovery package's verification logic).
// The genuine, gated production of a validly-signed CommittedPayload is a
// property of the rotationcommit package, not of this type.
//
// V1 (NewCommittedPayload) and V2 (NewCommittedPayloadV2, ADR-045) share
// this representation but digest under disjoint domain separators
// (DomainCommitted vs. DomainCommittedV2) and disjoint canonical field sets:
// V2 additionally binds a SigningKeyID into the digest, V1 never does.
// NewCommittedPayload's signature, behavior, and every digest value it
// produces are unchanged by V2's addition -- a V1-constructed payload never
// sets signingKeyID and always digests under DomainCommitted exactly as
// before ADR-045.
type CommittedPayload struct {
	environmentID       EnvironmentID
	authorityEpoch      AuthorityEpoch
	resourceIncarnation ResourceIncarnationID
	operationID         OperationID
	revisionNumber      RevisionNumber
	predecessorRevision RevisionNumber
	predecessorDigest   Digest32
	stateDigest         Digest32
	commitTimestamp     time.Time
	writerSignature     []byte
	signingKeyID        SigningKeyID
	isV2                bool
}

// NewCommittedPayload constructs a V1 CommittedPayload record, digested
// under DomainCommitted (EMG-ADR043-COMMITTED-V1). Pass a nil or empty
// writerSignature to build the unsigned form whose CanonicalDigest is what a
// Signer signs; pass the resulting signature to build the signed form that
// is actually witnessed.
//
// This constructor's signature and behavior are frozen (ADR-045 §11): every
// existing V1 fixture and digest value must remain exactly as it was.
func NewCommittedPayload(
	environmentID EnvironmentID,
	authorityEpoch AuthorityEpoch,
	resourceIncarnation ResourceIncarnationID,
	operationID OperationID,
	revisionNumber RevisionNumber,
	predecessorRevision RevisionNumber,
	predecessorDigest Digest32,
	stateDigest Digest32,
	commitTimestamp time.Time,
	writerSignature []byte,
) CommittedPayload {
	return CommittedPayload{
		environmentID:       environmentID,
		authorityEpoch:      authorityEpoch,
		resourceIncarnation: resourceIncarnation,
		operationID:         operationID,
		revisionNumber:      revisionNumber,
		predecessorRevision: predecessorRevision,
		predecessorDigest:   predecessorDigest,
		stateDigest:         stateDigest,
		commitTimestamp:     commitTimestamp.UTC(),
		writerSignature:     cloneCommittedBytes(writerSignature),
	}
}

// NewCommittedPayloadV2 constructs a V2 CommittedPayload record (ADR-045),
// digested under DomainCommittedV2 (EMG-ADR044-COMMITTED-V2) and
// additionally binding signingKeyID into the canonical digest. signingKeyID
// must be the exact key identifier already determined before this call --
// rotationcommit's corrected construction sequence obtains it from
// Signer.ActiveKeyID before building the digest, never discovers it only
// after signing (ADR-045 §10). Production genesis uses this constructor
// exclusively; NewCommittedPayload (V1) is never used to produce new
// production records going forward.
func NewCommittedPayloadV2(
	environmentID EnvironmentID,
	authorityEpoch AuthorityEpoch,
	resourceIncarnation ResourceIncarnationID,
	operationID OperationID,
	revisionNumber RevisionNumber,
	predecessorRevision RevisionNumber,
	predecessorDigest Digest32,
	stateDigest Digest32,
	commitTimestamp time.Time,
	signingKeyID SigningKeyID,
	writerSignature []byte,
) (CommittedPayload, error) {
	if signingKeyID.IsZero() {
		return CommittedPayload{}, ErrCommittedSigningKeyIDRequired
	}
	return CommittedPayload{
		environmentID:       environmentID,
		authorityEpoch:      authorityEpoch,
		resourceIncarnation: resourceIncarnation,
		operationID:         operationID,
		revisionNumber:      revisionNumber,
		predecessorRevision: predecessorRevision,
		predecessorDigest:   predecessorDigest,
		stateDigest:         stateDigest,
		commitTimestamp:     commitTimestamp.UTC(),
		writerSignature:     cloneCommittedBytes(writerSignature),
		signingKeyID:        signingKeyID,
		isV2:                true,
	}, nil
}

func (payload CommittedPayload) EnvironmentID() EnvironmentID { return payload.environmentID }

func (payload CommittedPayload) AuthorityEpoch() AuthorityEpoch { return payload.authorityEpoch }

func (payload CommittedPayload) ResourceIncarnation() ResourceIncarnationID {
	return payload.resourceIncarnation
}

func (payload CommittedPayload) OperationID() OperationID { return payload.operationID }

func (payload CommittedPayload) RevisionNumber() RevisionNumber { return payload.revisionNumber }

func (payload CommittedPayload) PredecessorRevision() RevisionNumber {
	return payload.predecessorRevision
}

func (payload CommittedPayload) PredecessorDigest() Digest32 { return payload.predecessorDigest }

func (payload CommittedPayload) StateDigest() Digest32 { return payload.stateDigest }

func (payload CommittedPayload) CommitTimestamp() time.Time { return payload.commitTimestamp }

func (payload CommittedPayload) WriterSignature() []byte {
	return cloneCommittedBytes(payload.writerSignature)
}

// SigningKeyID returns the V2 signing key identifier, or the zero value for
// a V1 payload (IsV2 reports false in that case). A zero SigningKeyID on a
// V2 payload is impossible: NewCommittedPayloadV2 rejects it at
// construction.
func (payload CommittedPayload) SigningKeyID() SigningKeyID { return payload.signingKeyID }

// IsV2 reports whether payload was constructed via NewCommittedPayloadV2
// (EMG-ADR044-COMMITTED-V2) rather than NewCommittedPayload (V1,
// EMG-ADR043-COMMITTED-V1).
func (payload CommittedPayload) IsV2() bool { return payload.isV2 }

// WithSignature returns a copy of payload with writerSignature attached. It
// does not sign anything itself -- the caller supplies an already-computed
// signature (normally produced only by rotationcommit's gated signing path).
func (payload CommittedPayload) WithSignature(writerSignature []byte) CommittedPayload {
	payload.writerSignature = cloneCommittedBytes(writerSignature)
	return payload
}

// CanonicalDigest deterministically hashes every field of payload except the
// signature itself. This is the value a Signer signs, and the value a
// verifier must independently recompute -- never trust a digest read from
// storage without recomputing it.
//
// A V1 payload (IsV2 false) hashes exactly the original nine-field V1 map
// under DomainCommitted, byte-for-byte identical to every digest this
// method ever produced before ADR-045 -- V2's addition changes nothing
// about this path. A V2 payload additionally includes signing_key_id in the
// map and hashes under the disjoint DomainCommittedV2 separator.
func (payload CommittedPayload) CanonicalDigest() (Digest32, error) {
	value := map[string]any{
		"environment_id":       payload.environmentID.String(),
		"authority_epoch":      payload.authorityEpoch.String(),
		"resource_incarnation": payload.resourceIncarnation.String(),
		"operation_id":         payload.operationID.String(),
		"revision_number":      payload.revisionNumber.Uint64(),
		"predecessor_revision": payload.predecessorRevision.Uint64(),
		"predecessor_digest":   payload.predecessorDigest.Bytes(),
		"state_digest":         payload.stateDigest.Bytes(),
		"commit_timestamp":     payload.commitTimestamp.UTC().Format(time.RFC3339Nano),
	}
	domain := DomainCommitted
	if payload.isV2 {
		value["signing_key_id"] = payload.signingKeyID.String()
		domain = DomainCommittedV2
	}
	encoded, err := EncodeDeterministicCBOR(value)
	if err != nil {
		return Digest32{}, err
	}
	return HashCanonical(domain, encoded), nil
}

func cloneCommittedBytes(value []byte) []byte {
	if len(value) == 0 {
		return nil
	}
	result := make([]byte, len(value))
	copy(result, value)
	return result
}
