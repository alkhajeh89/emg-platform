package protocol

import "time"

// CommittedPayload is the canonical, witnessable record of one accepted
// ADR-043 authority rotation. It is a plain data record: any package may
// construct or read one. Trust in a CommittedPayload never comes from who
// constructed the Go value -- it comes from independently recomputing
// CanonicalDigest and verifying WriterSignature against it, which is the
// caller's responsibility (see the recovery package's verification logic).
// The genuine, gated production of a validly-signed CommittedPayload is a
// property of the rotationcommit package, not of this type.
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
}

// NewCommittedPayload constructs a CommittedPayload record. Pass a nil or
// empty writerSignature to build the unsigned form whose CanonicalDigest is
// what a Signer signs; pass the resulting signature to build the signed
// form that is actually witnessed.
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

// WithSignature returns a copy of payload with writerSignature attached. It
// does not sign anything itself -- the caller supplies an already-computed
// signature (normally produced only by rotationcommit's gated signing path).
func (payload CommittedPayload) WithSignature(writerSignature []byte) CommittedPayload {
	payload.writerSignature = cloneCommittedBytes(writerSignature)
	return payload
}

// CanonicalDigest deterministically hashes every field of payload except the
// signature itself, under the DomainCommitted separator. This is the value
// a Signer signs, and the value a verifier must independently recompute --
// never trust a digest read from storage without recomputing it.
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
	encoded, err := EncodeDeterministicCBOR(value)
	if err != nil {
		return Digest32{}, err
	}
	return HashCanonical(DomainCommitted, encoded), nil
}

func cloneCommittedBytes(value []byte) []byte {
	if len(value) == 0 {
		return nil
	}
	result := make([]byte, len(value))
	copy(result, value)
	return result
}
