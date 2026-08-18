package protocol

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"time"
)

// committedPayloadWire is the canonical production JSON wire format for a
// witness-persisted CommittedPayload. It mirrors, field-for-field, the
// shape informally proven correct by rotationcommit's own emulator-tier
// process-kill/GCS-witness round-trip tests (committedPayloadDTO) --
// promoted here to production, exported code because, before this file,
// no production serialization for CommittedPayload existed anywhere in
// this codebase (an S5 finding: GCS witness reads/writes need SOME wire
// format, and none had been defined outside test code).
//
// This format is deliberately NOT the input to CanonicalDigest --
// CanonicalDigest always hashes the payload's own bound Go field values
// via deterministic CBOR (EncodeDeterministicCBOR), completely
// independent of how those same values happen to be serialized for
// storage. A different wire format chosen later would not change any
// digest value, precisely because verification never trusts serialized
// bytes as authoritative -- it always independently reconstructs the
// payload from decoded fields first (recovery.VerifyPersistedCommitted).
type committedPayloadWire struct {
	EnvironmentID       string `json:"environment_id"`
	AuthorityEpoch      string `json:"authority_epoch"`
	ResourceIncarnation string `json:"resource_incarnation"`
	OperationID         string `json:"operation_id"`
	RevisionNumber      uint64 `json:"revision_number"`
	PredecessorRevision uint64 `json:"predecessor_revision"`
	PredecessorDigest   string `json:"predecessor_digest_hex"`
	StateDigest         string `json:"state_digest_hex"`
	CommitTimestamp     string `json:"commit_timestamp"`
	WriterSignature     string `json:"writer_signature_hex"`
	// SigningKeyID is present (non-empty) for V2 payloads only. Its
	// absence is what MarshalCommittedPayloadJSON/UnmarshalCommittedPayloadJSON
	// use to distinguish V1 from V2 -- never inferred from any other field.
	SigningKeyID string `json:"signing_key_id,omitempty"`
}

// MarshalCommittedPayloadJSON encodes payload in the canonical production
// witness wire format. It never encodes signing_key_id for a V1 payload
// (IsV2 false) and always encodes it for a V2 payload -- V1/V2 remain
// exactly as distinguishable on the wire as they are in memory.
func MarshalCommittedPayloadJSON(payload CommittedPayload) ([]byte, error) {
	wire := committedPayloadWire{
		EnvironmentID:       payload.EnvironmentID().String(),
		AuthorityEpoch:      payload.AuthorityEpoch().String(),
		ResourceIncarnation: payload.ResourceIncarnation().String(),
		OperationID:         payload.OperationID().String(),
		RevisionNumber:      payload.RevisionNumber().Uint64(),
		PredecessorRevision: payload.PredecessorRevision().Uint64(),
		PredecessorDigest:   payload.PredecessorDigest().String(),
		StateDigest:         payload.StateDigest().String(),
		CommitTimestamp:     payload.CommitTimestamp().UTC().Format(time.RFC3339Nano),
		WriterSignature:     hex.EncodeToString(payload.WriterSignature()),
	}
	if payload.IsV2() {
		wire.SigningKeyID = payload.SigningKeyID().String()
	}
	data, err := json.Marshal(wire)
	if err != nil {
		return nil, fmt.Errorf("protocol: marshal committed payload: %w", err)
	}
	return data, nil
}

// UnmarshalCommittedPayloadJSON decodes the canonical production witness
// wire format, reconstructing a V1 payload (via NewCommittedPayload) when
// signing_key_id is absent/empty, or a V2 payload (via
// NewCommittedPayloadV2) when it is present -- there is no other
// format-detection rule, matching ADR-045 §11's "no automatic V1/V2
// format detection" for any OTHER inference source; this one, explicit,
// always-present-or-absent field is the sole and intentional discriminator.
func UnmarshalCommittedPayloadJSON(data []byte) (CommittedPayload, error) {
	var wire committedPayloadWire
	if err := json.Unmarshal(data, &wire); err != nil {
		return CommittedPayload{}, fmt.Errorf("protocol: decode committed payload: %w", err)
	}
	environment, err := NewEnvironmentID(wire.EnvironmentID)
	if err != nil {
		return CommittedPayload{}, fmt.Errorf("protocol: %w", err)
	}
	authorityEpoch, err := NewAuthorityEpoch(wire.AuthorityEpoch)
	if err != nil {
		return CommittedPayload{}, fmt.Errorf("protocol: %w", err)
	}
	resource, err := NewResourceIncarnationID(wire.ResourceIncarnation)
	if err != nil {
		return CommittedPayload{}, fmt.Errorf("protocol: %w", err)
	}
	operationID, err := NewOperationID(wire.OperationID)
	if err != nil {
		return CommittedPayload{}, fmt.Errorf("protocol: %w", err)
	}
	predecessorDigest, err := ParseDigest32(wire.PredecessorDigest)
	if err != nil {
		return CommittedPayload{}, fmt.Errorf("protocol: predecessor digest: %w", err)
	}
	stateDigest, err := ParseDigest32(wire.StateDigest)
	if err != nil {
		return CommittedPayload{}, fmt.Errorf("protocol: state digest: %w", err)
	}
	commitTimestamp, err := time.Parse(time.RFC3339Nano, wire.CommitTimestamp)
	if err != nil {
		return CommittedPayload{}, fmt.Errorf("protocol: commit timestamp: %w", err)
	}
	signature, err := hex.DecodeString(wire.WriterSignature)
	if err != nil {
		return CommittedPayload{}, fmt.Errorf("protocol: writer signature: %w", err)
	}

	if wire.SigningKeyID == "" {
		return NewCommittedPayload(
			environment, authorityEpoch, resource, operationID,
			NewRevisionNumber(wire.RevisionNumber), NewRevisionNumber(wire.PredecessorRevision),
			predecessorDigest, stateDigest, commitTimestamp, signature,
		), nil
	}
	keyID, err := NewSigningKeyID(wire.SigningKeyID)
	if err != nil {
		return CommittedPayload{}, fmt.Errorf("protocol: %w", err)
	}
	payload, err := NewCommittedPayloadV2(
		environment, authorityEpoch, resource, operationID,
		NewRevisionNumber(wire.RevisionNumber), NewRevisionNumber(wire.PredecessorRevision),
		predecessorDigest, stateDigest, commitTimestamp, keyID, signature,
	)
	if err != nil {
		return CommittedPayload{}, fmt.Errorf("protocol: %w", err)
	}
	return payload, nil
}
