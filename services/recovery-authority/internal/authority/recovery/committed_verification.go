package recovery

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// CommittedSignatureVerifier checks a detached writer signature against a
// digest using only public/verify-only key material. It is the sole
// counterpart to rotationcommit.Signer that recovery code may hold: it can
// prove a signature is valid, never produce one. No concrete
// implementation exists in this package; no KMS/GCP call is made here.
//
// keyID and signedAt are supplied so a concrete implementation can resolve
// the correct historical public key (ADR-045 §7C's pinned public-key
// material, or a live provider call) and apply compromise/distrust
// semantics (ADR-045 §7) internally, using signedAt (the payload's own
// trusted commit_timestamp) as the compromise distrust-effective-time
// comparison anchor. Building that ledger/pinning mechanism is out of this
// package's and S1's scope (ADR-045 §7, §7C) -- this interface only
// reserves the parameters a future implementation needs so it never
// requires a breaking change to add them later.
type CommittedSignatureVerifier interface {
	VerifyCommittedSignature(
		ctx context.Context,
		keyID protocol.SigningKeyID,
		signedAt time.Time,
		digest protocol.Digest32,
		signature []byte,
	) error
}

// ApprovedSigningLineage reports whether keyID belongs to the specific,
// independently approved signing lineage for this environment/resource
// (ADR-045 §7A) -- for the GCP-native realization ADR-044/ADR-045 select,
// typically membership in one specific approved CryptoKey's resource-name
// prefix, never merely "is this a syntactically valid identifier." This
// predicate is supplied by the caller as caller-independent configuration;
// it MUST NOT be derived from the persisted payload, from GCS, from the
// claimed SigningKeyID itself, or from any attacker-controlled provider
// metadata (ADR-045 §7A).
type ApprovedSigningLineage func(keyID protocol.SigningKeyID) bool

// ExpectedBinding is what the caller independently expects a persisted
// CommittedPayload to be bound to, before that payload may be trusted.
type ExpectedBinding struct {
	EnvironmentID       protocol.EnvironmentID
	AuthorityEpoch      protocol.AuthorityEpoch
	ResourceIncarnation protocol.ResourceIncarnationID
	OperationID         protocol.OperationID
	PredecessorRevision protocol.RevisionNumber
	PredecessorDigest   protocol.Digest32

	// ApprovedSigningLineage is the caller-independent key-authorization
	// trust anchor (ADR-045 §7A). It is consulted only for V2 payloads
	// (protocol.CommittedPayload.IsV2); V1 payloads predate SigningKeyID
	// entirely and are unaffected. Required (non-nil) whenever a V2 payload
	// is verified -- VerifyPersistedCommitted fails closed if it is nil.
	ApprovedSigningLineage ApprovedSigningLineage
}

var (
	// ErrCommittedBindingMismatch means the payload's own bound fields
	// (environment, epoch, resource incarnation, operation ID, predecessor
	// revision, predecessor checkpoint digest) do not match what the
	// caller independently expected.
	ErrCommittedBindingMismatch = errors.New("committed payload binding mismatch")

	// ErrCommittedSignatureMissing means no signature is present at all.
	ErrCommittedSignatureMissing = errors.New("committed payload has no writer signature")

	// ErrCommittedSignatureInvalid means a signature is present but does
	// not verify against the independently recomputed digest.
	ErrCommittedSignatureInvalid = errors.New("committed payload writer signature does not verify")

	// ErrCommittedSigningLineageNotConfigured means a V2 payload was
	// presented for verification with no ApprovedSigningLineage predicate
	// configured. This is a caller configuration error, not a payload
	// defect, and fails closed exactly like a genuine authorization
	// failure: key authorization can never be skipped merely because the
	// caller forgot to wire in a lineage check (ADR-045 §7A).
	ErrCommittedSigningLineageNotConfigured = errors.New("committed payload V2 verification requires an ApprovedSigningLineage")

	// ErrCommittedKeyNotAuthorized means a V2 payload's SigningKeyID does
	// not belong to the independently approved signing lineage. This check
	// is independent of, and never substitutes for or is substituted by,
	// cryptographic signature verification (ADR-045 §7A:
	// CONTENT_BINDING != KEY_AUTHORIZATION != ACCEPTANCE_PROVENANCE).
	ErrCommittedKeyNotAuthorized = errors.New("committed payload signing key is not in the approved signing lineage")
)

// VerifyPersistedCommitted independently verifies a persisted
// CommittedPayload before it may be treated as activating an authority
// revision. It fails closed: any binding mismatch, unauthorized signing
// key, absent signature, or signature-verification failure returns a
// non-nil error, and the caller MUST NOT activate the revision in that
// case. The payload's own self-reported digest is never trusted --
// CanonicalDigest is always recomputed here from the payload's bound
// fields before verification.
//
// Three properties are checked as separate, independent, all-mandatory
// steps (ADR-045 §7A): content binding (do these fields match what I
// expected), key authorization (V2 only -- does the signing key belong to
// the approved lineage), and acceptance provenance (was this genuinely
// produced by an authorized writer holding that key). A payload that binds
// correctly but carries no valid signature must fail exactly as hard as one
// that carries a valid-looking signature from an unauthorized key.
// CONTENT_BINDING != KEY_AUTHORIZATION != ACCEPTANCE_PROVENANCE: none of
// the three ever substitutes for another.
func VerifyPersistedCommitted(
	ctx context.Context,
	verifier CommittedSignatureVerifier,
	payload protocol.CommittedPayload,
	expected ExpectedBinding,
) error {
	if payload.EnvironmentID() != expected.EnvironmentID ||
		payload.AuthorityEpoch() != expected.AuthorityEpoch ||
		payload.ResourceIncarnation() != expected.ResourceIncarnation ||
		payload.OperationID() != expected.OperationID ||
		payload.PredecessorRevision() != expected.PredecessorRevision ||
		payload.PredecessorDigest() != expected.PredecessorDigest {
		return ErrCommittedBindingMismatch
	}

	if payload.IsV2() {
		if expected.ApprovedSigningLineage == nil {
			return ErrCommittedSigningLineageNotConfigured
		}
		if !expected.ApprovedSigningLineage(payload.SigningKeyID()) {
			return ErrCommittedKeyNotAuthorized
		}
	}

	signature := payload.WriterSignature()
	if len(signature) == 0 {
		return ErrCommittedSignatureMissing
	}

	digest, err := payload.CanonicalDigest()
	if err != nil {
		return fmt.Errorf("%w: %v", ErrCommittedSignatureInvalid, err)
	}
	if err := verifier.VerifyCommittedSignature(ctx, payload.SigningKeyID(), payload.CommitTimestamp(), digest, signature); err != nil {
		return fmt.Errorf("%w: %v", ErrCommittedSignatureInvalid, err)
	}
	return nil
}
