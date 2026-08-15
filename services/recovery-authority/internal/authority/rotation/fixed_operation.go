package rotation

import (
	"errors"
	"math"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

var ErrInvalidRevisionTransition = errors.New("proposed revision must equal expected revision plus one")

// FixedOperation is the immutable, precomputed input to every legitimate
// retry of one authorized rotation.
type FixedOperation struct {
	environmentID       protocol.EnvironmentID
	authorityEpoch      protocol.AuthorityEpoch
	resourceIncarnation protocol.ResourceIncarnationID
	operationID         protocol.OperationID
	expectedRevision    protocol.RevisionNumber
	proposedRevision    protocol.RevisionNumber
	preparedDigest      protocol.Digest32
	candidateBytes      []byte
	preparedBytes       []byte
}

func NewFixedOperation(
	environmentID protocol.EnvironmentID,
	authorityEpoch protocol.AuthorityEpoch,
	resourceIncarnation protocol.ResourceIncarnationID,
	operationID protocol.OperationID,
	expectedRevision protocol.RevisionNumber,
	proposedRevision protocol.RevisionNumber,
	preparedDigest protocol.Digest32,
	candidateBytes []byte,
	preparedBytes []byte,
) (FixedOperation, error) {
	if expectedRevision.Uint64() == math.MaxUint64 ||
		proposedRevision.Uint64() != expectedRevision.Uint64()+1 {
		return FixedOperation{}, ErrInvalidRevisionTransition
	}
	return FixedOperation{
		environmentID:       environmentID,
		authorityEpoch:      authorityEpoch,
		resourceIncarnation: resourceIncarnation,
		operationID:         operationID,
		expectedRevision:    expectedRevision,
		proposedRevision:    proposedRevision,
		preparedDigest:      preparedDigest,
		candidateBytes:      clone(candidateBytes),
		preparedBytes:       clone(preparedBytes),
	}, nil
}

func (operation FixedOperation) EnvironmentID() protocol.EnvironmentID {
	return operation.environmentID
}

func (operation FixedOperation) AuthorityEpoch() protocol.AuthorityEpoch {
	return operation.authorityEpoch
}

func (operation FixedOperation) ResourceIncarnation() protocol.ResourceIncarnationID {
	return operation.resourceIncarnation
}

func (operation FixedOperation) OperationID() protocol.OperationID {
	return operation.operationID
}

func (operation FixedOperation) ExpectedRevision() protocol.RevisionNumber {
	return operation.expectedRevision
}

func (operation FixedOperation) ProposedRevision() protocol.RevisionNumber {
	return operation.proposedRevision
}

func (operation FixedOperation) PreparedDigest() protocol.Digest32 {
	return operation.preparedDigest
}

func (operation FixedOperation) CandidateBytes() []byte { return clone(operation.candidateBytes) }

func (operation FixedOperation) PreparedBytes() []byte { return clone(operation.preparedBytes) }

func clone(value []byte) []byte {
	result := make([]byte, len(value))
	copy(result, value)
	return result
}
