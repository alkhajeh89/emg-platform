package rotationcommit

import (
	"context"
	"time"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotation"
)

type processCapability struct {
	nonComparable func()
}

func newProcessCapability() processCapability {
	return processCapability{nonComparable: func() {}}
}

type acceptedRotationContext struct {
	candidateBytes      []byte
	preparedBytes       []byte
	preparedDigest      protocol.Digest32
	environmentID       protocol.EnvironmentID
	authorityEpoch      protocol.AuthorityEpoch
	resourceIncarnation protocol.ResourceIncarnationID
	operationID         protocol.OperationID
	expectedRevision    protocol.RevisionNumber
	proposedRevision    protocol.RevisionNumber
	commitTimestamp     time.Time
	transactionAttempt  []byte
	capability          processCapability
}

func newAcceptedRotationContext(
	capability processCapability,
	operation rotation.FixedOperation,
	commitTimestamp time.Time,
	transactionAttempt []byte,
) acceptedRotationContext {
	return acceptedRotationContext{
		candidateBytes:      cloneBytes(operation.CandidateBytes()),
		preparedBytes:       cloneBytes(operation.PreparedBytes()),
		preparedDigest:      operation.PreparedDigest(),
		environmentID:       operation.EnvironmentID(),
		authorityEpoch:      operation.AuthorityEpoch(),
		resourceIncarnation: operation.ResourceIncarnation(),
		operationID:         operation.OperationID(),
		expectedRevision:    operation.ExpectedRevision(),
		proposedRevision:    operation.ProposedRevision(),
		commitTimestamp:     commitTimestamp.UTC(),
		transactionAttempt:  cloneBytes(transactionAttempt),
		capability:          capability,
	}
}

// completeRawCommit is the sole context creation path. It invokes the injected
// raw Commit boundary exactly once and never retries an ambiguous result.
func completeRawCommit(
	ctx context.Context,
	client RawCommitClient,
	request *spannerpb.CommitRequest,
	operation rotation.FixedOperation,
	transactionAttempt []byte,
) (acceptedRotationContext, CommitClassification, error) {
	response, commitErr := client.Commit(ctx, request)
	classification := ClassifyCommit(true, response, commitErr, RegularSession)
	if classification.Outcome != protocol.UnambiguousSuccess {
		return acceptedRotationContext{}, classification, ErrAcceptedContextUnavailable
	}
	accepted := newAcceptedRotationContext(
		newProcessCapability(),
		operation,
		response.GetCommitTimestamp().AsTime(),
		transactionAttempt,
	)
	return accepted, classification, nil
}

func cloneBytes(value []byte) []byte {
	result := make([]byte, len(value))
	copy(result, value)
	return result
}
