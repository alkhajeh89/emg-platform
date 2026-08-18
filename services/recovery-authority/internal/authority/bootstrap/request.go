package bootstrap

import (
	"crypto/sha256"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/runtimeconfig"
)

// GenesisPredecessorRevision, GenesisRevision, and GenesisPredecessorDigest
// are the fixed sentinel values every genesis operation uses in place of a
// real predecessor (S6 Phase 4). protocol never defines a dedicated
// genesis record type -- ADR-044/045 model genesis as an ordinary V2
// CommittedPayload whose predecessor is the well-known "no predecessor
// exists yet" sentinel: revision 0, and a predecessor digest of 32 zero
// bytes (protocol.Digest32's zero value, which NewDigest32 never produces
// from real hash output -- SHA-256 preimage resistance makes a genuine
// digest colliding with the all-zero value negligible). rotation.FixedOperation's
// own validation (proposedRevision == expectedRevision+1) is exactly what
// requires GenesisRevision to be 1.
var (
	GenesisPredecessorRevision = protocol.NewRevisionNumber(0)
	GenesisRevision            = protocol.NewRevisionNumber(1)
	GenesisPredecessorDigest   = protocol.Digest32{}
)

var (
	ErrGenesisRequestFieldRequired = errors.New("bootstrap: genesis request field is required")
)

// GenesisRequestParams is the raw, caller-supplied input contract (S6 Phase
// 3): every field a genesis attempt needs, expressed as unvalidated strings
// exactly as an operator/CLI/config file would supply them. NewGenesisRequest
// is the sole path that turns this into a GenesisRequest -- malformed or
// missing security-critical values are rejected here, before any
// precondition check or provider call is attempted.
//
// AuthorityEpoch, OperationID, and ResourceIncarnationID are still validated
// UUIDv7 strings here (not derived from any other field), but the audited,
// sanctioned way to obtain them is GenerateFreshIdentifiers -- never a hash
// or transform of environment name, candidate content, or any other
// payload-controlled value (S6 Phase 1: "no deriving authority state from
// payload-controlled data"). This constructor cannot itself prove a given
// string came from that function; what it does enforce is the exact
// UUIDv7 structural format (version/variant nibbles), which rules out the
// trivially-predictable or degenerate identifiers (all-zero, sequential,
// truncated) an attacker without access to a CSPRNG would produce.
type GenesisRequestParams struct {
	EnvironmentID            string
	ResourceIncarnationID    string
	AuthorityEpoch           string
	OperationID              string
	SpannerDatabase          string
	SigningKeyID             string
	ApprovedSigningCryptoKey string
	Approvals                []Approval
}

// GenesisRequest is the fully validated form of GenesisRequestParams. Every
// field has already passed its type-specific constructor; no field is ever
// re-validated by any downstream consumer, and no downstream consumer ever
// accepts a raw string in its place.
type GenesisRequest struct {
	EnvironmentID            protocol.EnvironmentID
	ResourceIncarnation      protocol.ResourceIncarnationID
	AuthorityEpoch           protocol.AuthorityEpoch
	OperationID              protocol.OperationID
	SpannerDatabase          string
	SigningKeyID             protocol.SigningKeyID
	ApprovedSigningCryptoKey string
	Approvals                []Approval
	digest                   [32]byte
}

// maxApprovalAge bounds how old a dual-control approval may be at the
// moment ExecuteGenesis runs (ATTACK_Q, S6 Phase 9 scenario J). 72 hours is
// long enough to accommodate a real, governed, multi-party change-approval
// process, short enough that an approval captured for one genesis attempt
// cannot be quietly held in reserve and replayed against an unrelated,
// much later attempt.
const maxApprovalAge = 72 * time.Hour

// NewGenesisRequest validates params field by field -- every identifier
// through its protocol constructor, SpannerDatabase and the approved
// signing CryptoKey through the same resource-name patterns the production
// binaries already require (runtimeconfig), and finally the dual-control
// approvals, bound to the digest of every other field above. Any single
// malformed or missing field fails closed before anything else is
// evaluated.
func NewGenesisRequest(params GenesisRequestParams, now time.Time) (GenesisRequest, error) {
	environmentID, err := protocol.NewEnvironmentID(params.EnvironmentID)
	if err != nil {
		return GenesisRequest{}, fmt.Errorf("environment_id: %w", err)
	}
	resourceIncarnation, err := protocol.NewResourceIncarnationID(params.ResourceIncarnationID)
	if err != nil {
		return GenesisRequest{}, fmt.Errorf("resource_incarnation_id: %w", err)
	}
	authorityEpoch, err := protocol.NewAuthorityEpoch(params.AuthorityEpoch)
	if err != nil {
		return GenesisRequest{}, fmt.Errorf("authority_epoch: %w", err)
	}
	operationID, err := protocol.NewOperationID(params.OperationID)
	if err != nil {
		return GenesisRequest{}, fmt.Errorf("operation_id: %w", err)
	}
	if !runtimeconfig.SpannerDatabasePattern.MatchString(params.SpannerDatabase) {
		return GenesisRequest{}, fmt.Errorf("spanner_database: %w: %q is not a valid Cloud Spanner database resource name", ErrGenesisRequestFieldRequired, params.SpannerDatabase)
	}
	signingKeyID, err := protocol.NewSigningKeyID(params.SigningKeyID)
	if err != nil {
		return GenesisRequest{}, fmt.Errorf("signing_key_id: %w", err)
	}
	if !runtimeconfig.CryptoKeyPattern.MatchString(params.ApprovedSigningCryptoKey) {
		return GenesisRequest{}, fmt.Errorf("approved_signing_crypto_key: %w: %q is not a valid Cloud KMS CryptoKey resource name", ErrGenesisRequestFieldRequired, params.ApprovedSigningCryptoKey)
	}

	digest := computeRequestDigest(
		environmentID.String(),
		resourceIncarnation.String(),
		authorityEpoch.String(),
		operationID.String(),
		params.SpannerDatabase,
		signingKeyID.String(),
		params.ApprovedSigningCryptoKey,
	)
	if err := validateDualControl(params.Approvals, digest, now, maxApprovalAge); err != nil {
		return GenesisRequest{}, err
	}

	return GenesisRequest{
		EnvironmentID:            environmentID,
		ResourceIncarnation:      resourceIncarnation,
		AuthorityEpoch:           authorityEpoch,
		OperationID:              operationID,
		SpannerDatabase:          params.SpannerDatabase,
		SigningKeyID:             signingKeyID,
		ApprovedSigningCryptoKey: params.ApprovedSigningCryptoKey,
		Approvals:                params.Approvals,
		digest:                   digest,
	}, nil
}

// computeRequestDigest binds a set of Approvals to the exact bootstrap
// content they cover. This is deliberately NOT protocol.HashCanonical under
// any ADR-043/044 domain separator: it is not a witnessed, signed, or
// verified protocol record -- it is an internal, bootstrap-only value used
// only to detect a replayed or mismatched approval, never persisted as
// protocol state and never compared against anything outside this package.
func computeRequestDigest(fields ...string) [32]byte {
	hasher := sha256.New()
	for _, field := range fields {
		length := [8]byte{byte(len(field) >> 56), byte(len(field) >> 48), byte(len(field) >> 40), byte(len(field) >> 32), byte(len(field) >> 24), byte(len(field) >> 16), byte(len(field) >> 8), byte(len(field))}
		hasher.Write(length[:])
		hasher.Write([]byte(field))
	}
	var sum [32]byte
	copy(sum[:], hasher.Sum(nil))
	return sum
}

// RequestDigest exposes the binding digest so callers can construct
// Approval values covering this exact request (e.g. in tests, or in a
// future CLI that prints the digest for an approver to countersign
// out-of-band before it is embedded back into an Approval).
func (r GenesisRequest) RequestDigest() [32]byte { return r.digest }

// WitnessKey is the deterministic GCS witness object key genesis writes to
// and idempotency checks read from. It is a pure function of already
// validated, already dual-control-approved identifiers -- never a
// separately caller-suppliable value -- so a genesis attempt and every
// retry of that exact same attempt always agree on the one witness object
// that either does or does not yet exist (S6 Phase 6/9).
func (r GenesisRequest) WitnessKey() string {
	return fmt.Sprintf(
		"genesis/%s/%s/%s/%s.json",
		r.EnvironmentID.String(),
		r.ResourceIncarnation.String(),
		r.AuthorityEpoch.String(),
		GenesisRevision.String(),
	)
}

// GenerateFreshIdentifiers is the sole sanctioned, audited mechanism (S6
// Phase 3) for minting a new AuthorityEpoch and OperationID for a genesis
// attempt: cryptographically random UUIDv7 values (google/uuid's NewV7,
// RFC 9562), never a hash or transform of any other field. Call it once per
// genesis attempt and persist its output (e.g. into the same durably
// stored GenesisRequestParams a retry will reuse) -- calling it again for a
// retry of the SAME attempt would mint a different epoch, which the
// witness-existence idempotency check (Phase 9) can no longer recognize as
// the same attempt.
func GenerateFreshIdentifiers() (authorityEpoch protocol.AuthorityEpoch, operationID protocol.OperationID, err error) {
	epochUUID, err := uuid.NewV7()
	if err != nil {
		return protocol.AuthorityEpoch{}, protocol.OperationID{}, fmt.Errorf("bootstrap: generate authority epoch: %w", err)
	}
	operationUUID, err := uuid.NewV7()
	if err != nil {
		return protocol.AuthorityEpoch{}, protocol.OperationID{}, fmt.Errorf("bootstrap: generate operation id: %w", err)
	}
	authorityEpoch, err = protocol.NewAuthorityEpoch(epochUUID.String())
	if err != nil {
		return protocol.AuthorityEpoch{}, protocol.OperationID{}, fmt.Errorf("bootstrap: generated authority epoch failed validation: %w", err)
	}
	operationID, err = protocol.NewOperationID(operationUUID.String())
	if err != nil {
		return protocol.AuthorityEpoch{}, protocol.OperationID{}, fmt.Errorf("bootstrap: generated operation id failed validation: %w", err)
	}
	return authorityEpoch, operationID, nil
}

// genesisCandidateBytes deterministically encodes the genesis intent -- the
// "candidate" content a genesis operation's canonical digest is computed
// over (rotationcommit.buildGenesisCommittedPayload, via
// protocol.DomainNewEpochGenesis) -- exclusively from fields already
// validated and dual-control-approved as part of req. It never includes
// anything an attacker who does not already control both approvals could
// influence.
func genesisCandidateBytes(req GenesisRequest) ([]byte, error) {
	return protocol.EncodeDeterministicCBOR(map[string]any{
		"environment_id":       req.EnvironmentID.String(),
		"resource_incarnation": req.ResourceIncarnation.String(),
		"authority_epoch":      req.AuthorityEpoch.String(),
		"operation_id":         req.OperationID.String(),
	})
}
