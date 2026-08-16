package rotation

import (
	"bytes"
	"errors"
	"testing"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

func TestFixedOperationIsImmutableAndRequiresSuccessorRevision(t *testing.T) {
	t.Parallel()
	environment, _ := protocol.NewEnvironmentID("staging")
	epoch, _ := protocol.NewAuthorityEpoch("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a1")
	resource, _ := protocol.NewResourceIncarnationID("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a2")
	operationID, _ := protocol.NewOperationID("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a3")
	digest, _ := protocol.NewDigest32(bytes.Repeat([]byte{1}, 32))
	candidate := []byte("candidate")
	prepared := []byte("prepared")
	operation, err := NewFixedOperation(
		environment, epoch, resource, operationID,
		protocol.NewRevisionNumber(3), protocol.NewRevisionNumber(4), digest,
		candidate, prepared,
	)
	if err != nil {
		t.Fatal(err)
	}
	candidate[0] = 'X'
	prepared[0] = 'X'
	if string(operation.CandidateBytes()) != "candidate" || string(operation.PreparedBytes()) != "prepared" {
		t.Fatal("fixed operation retained mutable constructor storage")
	}
	returned := operation.CandidateBytes()
	returned[0] = 'X'
	if string(operation.CandidateBytes()) != "candidate" {
		t.Fatal("fixed operation exposed mutable storage")
	}
	_, err = NewFixedOperation(
		environment, epoch, resource, operationID,
		protocol.NewRevisionNumber(3), protocol.NewRevisionNumber(5), digest,
		nil, nil,
	)
	if !errors.Is(err, ErrInvalidRevisionTransition) {
		t.Fatalf("invalid revision transition error = %v", err)
	}
}
