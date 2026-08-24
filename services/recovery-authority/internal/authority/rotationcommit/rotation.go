package rotationcommit

import (
	"context"
	"fmt"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotation"
)

// CompleteRotationCommit is the ordinary-rotation counterpart to
// CompleteGenesisCommit (ADR-044 §17 item 1's missing production
// PREPARE/mutation-construction closure, S8). It performs the identical raw
// Commit boundary call, the identical fail-closed ClassifyCommit, and the
// identical ADR-045 §10 V2 construction order already frozen and qualified
// by buildCommittedPayload -- the same unexported function every emulator
// T1/T9/T13/T14 conformance test already exercises for ordinary rotations.
// This function adds no new security logic: it is the missing exported
// entry point that lets production orchestration code
// (rotationexecute) reach the already-existing, already-reviewed
// unexported primitives, exactly as CompleteGenesisCommit already does for
// genesis. buildCommittedPayload itself is unmodified; this function calls
// it exactly as every existing test already does.
//
// request MUST already reflect a real-write transaction that read the
// current authority_head row and independently confirmed operation's
// expected revision, authority epoch, and predecessor digest against that
// row (see rotationprepare.PrepareOrdinaryRotation) -- this function
// performs no such read itself, and completeRawCommit never resolves an
// ambiguous Commit outcome by reading again afterward.
func CompleteRotationCommit(
	ctx context.Context,
	client RawCommitClient,
	request *spannerpb.CommitRequest,
	operation rotation.FixedOperation,
	transactionAttempt []byte,
	signer Signer,
) (protocol.CommittedPayload, CommitClassification, error) {
	accepted, classification, err := completeRawCommit(ctx, client, request, operation, transactionAttempt)
	if err != nil {
		return protocol.CommittedPayload{}, classification, err
	}
	payload, err := buildCommittedPayload(ctx, signer, accepted)
	if err != nil {
		return protocol.CommittedPayload{}, classification, fmt.Errorf("rotationcommit: rotation payload: %w", err)
	}
	return payload, classification, nil
}
