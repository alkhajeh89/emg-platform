package rotationcommit

import (
	"context"
	"errors"
	"fmt"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// Signer produces a V2 COMMITTED payload's detached signature (ADR-045).
// This package defines the interface only; no concrete implementation
// exists here, and this package performs no KMS/GCP calls. A future,
// separate provider adapter (not yet built) supplies a concrete Signer for
// production use. The interface is exported, following the same pattern
// already used for RawCommitClient, so that adapter can implement it
// without needing to live inside this package -- but, exactly like
// RawCommitClient, an exported interface type is not the same thing as an
// exported capability: nothing in this package ever hands a Signer value to
// code outside it, and the sole call site that invokes it is unexported and
// requires a live acceptedRotationContext.
type Signer interface {
	// ActiveKeyID reports the SigningKeyID this Signer currently intends to
	// use for the next signature, queried before the digest that will be
	// signed is constructed (ADR-045 §10 step 2). It performs no signing.
	// The corrected construction order requires this value be known before
	// CanonicalDigest is computed, never discovered only after signing --
	// signing_key_id must already be part of what SignCommittedDigest signs.
	ActiveKeyID(ctx context.Context) (protocol.SigningKeyID, error)

	// SignCommittedDigest signs a digest that already includes the
	// SigningKeyID returned by the immediately preceding ActiveKeyID call.
	// The returned keyID is a defense-in-depth confirmation of the exact
	// key version actually used -- buildCommittedPayload checks it against,
	// never treats it as the origin of, the identifier already bound into
	// digest (ADR-045 §10).
	SignCommittedDigest(ctx context.Context, digest protocol.Digest32) (
		signature []byte, keyID protocol.SigningKeyID, err error,
	)
}

var (
	ErrCommittedPayloadUnavailable = errors.New("committed payload unavailable")

	// ErrSigningKeyMismatch is returned when the signer's post-signing
	// confirmed key identifier does not equal the key identifier already
	// bound into the digest at construction time (ADR-045 §10 step 7). This
	// is a hard construction failure: no payload is produced, no retry is
	// attempted under either identifier, and the resulting signature is
	// discarded rather than silently accepted or rebound.
	ErrSigningKeyMismatch = errors.New("rotationcommit: signer's confirmed key ID does not match the key ID bound into the digest")
)

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
// them, which nothing in this codebase does) and call SignCommittedDigest
// directly -- but that produces a signature over whatever digest they
// supply, not a CommittedPayload bound to a genuine, witnessed
// acceptedRotationContext, and the recovery-side verifier (see the recovery
// package) never trusts a payload on the strength of its having a
// syntactically valid signature over an arbitrary digest -- it always
// independently recomputes the digest from the payload's own bound fields
// first, and independently checks the signing key against an approved
// lineage before trusting the cryptographic result at all (ADR-045 §7A).
//
// Construction order (ADR-045 §10): the intended signing key identifier is
// obtained from the signer BEFORE the digest is constructed, bound into the
// V2 payload, and only then signed. A mismatch between the pre-bound
// identifier and the signer's post-signing confirmation is a hard failure.
func buildCommittedPayload(
	ctx context.Context,
	signer Signer,
	accepted acceptedRotationContext,
) (protocol.CommittedPayload, error) {
	keyID, err := signer.ActiveKeyID(ctx)
	if err != nil {
		return protocol.CommittedPayload{}, fmt.Errorf("%w: %v", ErrCommittedPayloadUnavailable, err)
	}
	if keyID.IsZero() {
		return protocol.CommittedPayload{}, fmt.Errorf("%w: signer returned an empty active key ID", ErrCommittedPayloadUnavailable)
	}

	stateDigest := protocol.HashCanonical(protocol.DomainRotationCandidate, cloneBytes(accepted.candidateBytes))
	unsigned, err := protocol.NewCommittedPayloadV2(
		accepted.environmentID,
		accepted.authorityEpoch,
		accepted.resourceIncarnation,
		accepted.operationID,
		accepted.proposedRevision,
		accepted.expectedRevision,
		accepted.preparedDigest,
		stateDigest,
		accepted.commitTimestamp,
		keyID,
		nil,
	)
	if err != nil {
		return protocol.CommittedPayload{}, fmt.Errorf("%w: %v", ErrCommittedPayloadUnavailable, err)
	}
	digest, err := unsigned.CanonicalDigest()
	if err != nil {
		return protocol.CommittedPayload{}, fmt.Errorf("%w: %v", ErrCommittedPayloadUnavailable, err)
	}
	signature, confirmedKeyID, err := signer.SignCommittedDigest(ctx, digest)
	if err != nil {
		return protocol.CommittedPayload{}, fmt.Errorf("%w: %v", ErrCommittedPayloadUnavailable, err)
	}
	if len(signature) == 0 {
		return protocol.CommittedPayload{}, fmt.Errorf("%w: signer returned an empty signature", ErrCommittedPayloadUnavailable)
	}
	if confirmedKeyID.IsZero() {
		return protocol.CommittedPayload{}, fmt.Errorf("%w: signer returned an empty confirming key ID", ErrCommittedPayloadUnavailable)
	}
	if confirmedKeyID != keyID {
		return protocol.CommittedPayload{}, fmt.Errorf("%w: bound %q, confirmed %q", ErrSigningKeyMismatch, keyID.String(), confirmedKeyID.String())
	}
	return unsigned.WithSignature(signature), nil
}
