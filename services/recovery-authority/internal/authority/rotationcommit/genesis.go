package rotationcommit

import (
	"context"
	"fmt"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotation"
)

// CompleteGenesisCommit is S6's authorized, narrowly-scoped genesis
// orchestration entry point (ADR-044 §17 item 5 / the reserved
// EMG-ADR043-NEW-EPOCH-GENESIS-V1 domain separator, previously unused
// anywhere in this codebase). It performs the same raw Commit boundary
// call, the same fail-closed ClassifyCommit, and the same ADR-045 §10 V2
// construction order buildCommittedPayload already implements and
// exercises for every ordinary rotation -- with exactly one difference:
// the candidate/state bytes are hashed under protocol.DomainNewEpochGenesis
// instead of protocol.DomainRotationCandidate, so a genesis record's
// digest can never collide with, or be confused for, an ordinary
// rotation candidate's digest over the same underlying bytes.
//
// buildCommittedPayload itself is NOT modified, refactored, or shared
// with this function -- this function's payload-construction logic below
// is a deliberate, standalone duplication of it (with only the domain
// separator changed), precisely so the frozen, already-reviewed S1/S3
// function and its existing tests carry zero risk from this addition.
func CompleteGenesisCommit(
	ctx context.Context,
	client RawCommitClient,
	request *spannerpb.CommitRequest,
	operation rotation.FixedOperation,
	signer Signer,
) (protocol.CommittedPayload, CommitClassification, error) {
	accepted, classification, err := completeRawCommit(ctx, client, request, operation, nil)
	if err != nil {
		return protocol.CommittedPayload{}, classification, err
	}
	payload, err := buildGenesisCommittedPayload(ctx, signer, accepted)
	if err != nil {
		return protocol.CommittedPayload{}, classification, fmt.Errorf("rotationcommit: genesis payload: %w", err)
	}
	return payload, classification, nil
}

// buildGenesisCommittedPayload mirrors buildCommittedPayload's construction
// order exactly (ADR-045 §10 steps 1-8), differing only in which domain
// separator hashes the candidate/state bytes into the V2 payload's
// stateDigest field.
func buildGenesisCommittedPayload(
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

	stateDigest := protocol.HashCanonical(protocol.DomainNewEpochGenesis, cloneBytes(accepted.candidateBytes))
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
