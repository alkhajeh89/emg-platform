package rotationcommit

import (
	"context"
	"errors"
	"fmt"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// Signer produces a detached signature over one COMMITTED payload's
// canonical digest. This package defines the interface only; no concrete
// implementation exists here, and this package performs no KMS/GCP calls.
// A future, separate provider adapter (not yet built) supplies a concrete
// Signer for production use. The interface is exported, following the same
// pattern already used for RawCommitClient, so that adapter can implement
// it without needing to live inside this package -- but, exactly like
// RawCommitClient, an exported interface type is not the same thing as an
// exported capability: nothing in this package ever hands a Signer value to
// code outside it, and the sole call site that invokes SignCommittedDigest
// is unexported and requires a live acceptedRotationContext.
type Signer interface {
	SignCommittedDigest(ctx context.Context, digest protocol.Digest32) (signature []byte, err error)
}

var ErrCommittedPayloadUnavailable = errors.New("committed payload unavailable")

// buildCommittedPayload is the sole path in this module that can produce a
// genuinely, validly signed protocol.CommittedPayload. It requires a live
// acceptedRotationContext -- an unexported type with an unexported
// constructor that only exists as the direct, same-operation result of a
// completeRawCommit call classified UnambiguousSuccess. No package outside
// rotationcommit can construct that argument, and rotationcommit itself
// never constructs one except inside completeRawCommit. Recovery code and
// any future witness/GCS-adapter code therefore have no path to this
// function and no path to mint a provenance signature independently of it:
// at most they can hold a Signer reference (if one were ever handed to
// them, which nothing in this codebase does) and call
// SignCommittedDigest directly -- but that produces a signature over
// whatever digest they supply, not a CommittedPayload bound to a genuine,
// witnessed acceptedRotationContext, and the recovery-side verifier (see
// the recovery package) never trusts a payload on the strength of its
// having a syntactically valid signature over an arbitrary digest -- it
// always independently recomputes the digest from the payload's own bound
// fields first.
func buildCommittedPayload(
	ctx context.Context,
	signer Signer,
	accepted acceptedRotationContext,
) (protocol.CommittedPayload, error) {
	stateDigest := protocol.HashCanonical(protocol.DomainRotationCandidate, cloneBytes(accepted.candidateBytes))
	unsigned := protocol.NewCommittedPayload(
		accepted.environmentID,
		accepted.authorityEpoch,
		accepted.resourceIncarnation,
		accepted.operationID,
		accepted.proposedRevision,
		accepted.expectedRevision,
		accepted.preparedDigest,
		stateDigest,
		accepted.commitTimestamp,
		nil,
	)
	digest, err := unsigned.CanonicalDigest()
	if err != nil {
		return protocol.CommittedPayload{}, fmt.Errorf("%w: %v", ErrCommittedPayloadUnavailable, err)
	}
	signature, err := signer.SignCommittedDigest(ctx, digest)
	if err != nil {
		return protocol.CommittedPayload{}, fmt.Errorf("%w: %v", ErrCommittedPayloadUnavailable, err)
	}
	if len(signature) == 0 {
		return protocol.CommittedPayload{}, fmt.Errorf("%w: signer returned an empty signature", ErrCommittedPayloadUnavailable)
	}
	return unsigned.WithSignature(signature), nil
}
