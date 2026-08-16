package recovery

import (
	"context"
	"errors"
	"fmt"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// CommittedSignatureVerifier checks a detached writer signature against a
// digest using only public/verify-only key material. It is the sole
// counterpart to rotationcommit.Signer that recovery code may hold: it can
// prove a signature is valid, never produce one. No concrete
// implementation exists in this package; no KMS/GCP call is made here.
type CommittedSignatureVerifier interface {
	VerifyCommittedSignature(ctx context.Context, digest protocol.Digest32, signature []byte) error
}

// ExpectedBinding is what the caller independently expects a persisted
// CommittedPayload to be bound to, before that payload may be trusted.
type ExpectedBinding struct {
	EnvironmentID       protocol.EnvironmentID
	AuthorityEpoch      protocol.AuthorityEpoch
	ResourceIncarnation protocol.ResourceIncarnationID
	OperationID         protocol.OperationID
	PredecessorRevision protocol.RevisionNumber
	PredecessorDigest   protocol.Digest32
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
)

// VerifyPersistedCommitted independently verifies a persisted
// CommittedPayload before it may be treated as activating an authority
// revision. It fails closed: any binding mismatch, absent signature, or
// signature-verification failure returns a non-nil error, and the caller
// MUST NOT activate the revision in that case. The payload's own
// self-reported digest is never trusted -- CanonicalDigest is always
// recomputed here from the payload's bound fields before verification.
//
// Content binding (do these fields match what I expected) and acceptance
// provenance (was this genuinely produced by the authorized writer) are
// deliberately checked as two separate, both-mandatory steps: a payload
// that binds correctly but carries no valid signature must fail exactly as
// hard as one that carries a valid-looking signature over the wrong
// content. Neither property alone is sufficient.
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

	signature := payload.WriterSignature()
	if len(signature) == 0 {
		return ErrCommittedSignatureMissing
	}

	digest, err := payload.CanonicalDigest()
	if err != nil {
		return fmt.Errorf("%w: %v", ErrCommittedSignatureInvalid, err)
	}
	if err := verifier.VerifyCommittedSignature(ctx, digest, signature); err != nil {
		return fmt.Errorf("%w: %v", ErrCommittedSignatureInvalid, err)
	}
	return nil
}
