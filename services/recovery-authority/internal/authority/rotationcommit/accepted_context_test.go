package rotationcommit

import (
	"bytes"
	"context"
	"encoding"
	"encoding/gob"
	"encoding/json"
	"testing"
	"time"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotation"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type fakeRawCommitClient struct {
	response *spannerpb.CommitResponse
	err      error
	calls    int
}

func (client *fakeRawCommitClient) Commit(
	context.Context,
	*spannerpb.CommitRequest,
	...grpc.CallOption,
) (*spannerpb.CommitResponse, error) {
	client.calls++
	return client.response, client.err
}

func fixedOperationForTest(t *testing.T, candidate, prepared []byte) rotation.FixedOperation {
	t.Helper()
	environment, _ := protocol.NewEnvironmentID("staging")
	epoch, _ := protocol.NewAuthorityEpoch("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a1")
	resource, _ := protocol.NewResourceIncarnationID("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a2")
	operationID, _ := protocol.NewOperationID("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a3")
	digest, _ := protocol.NewDigest32(bytes.Repeat([]byte{1}, 32))
	operation, err := rotation.NewFixedOperation(
		environment, epoch, resource, operationID,
		protocol.NewRevisionNumber(8), protocol.NewRevisionNumber(9), digest,
		candidate, prepared,
	)
	if err != nil {
		t.Fatal(err)
	}
	return operation
}

func TestAcceptedContextRequiresSuccessfulCommitAndCopiesInputs(t *testing.T) {
	t.Parallel()
	candidate := []byte("candidate")
	prepared := []byte("prepared")
	attempt := []byte("attempt")
	operation := fixedOperationForTest(t, candidate, prepared)
	response := &spannerpb.CommitResponse{
		CommitTimestamp: timestamppb.New(time.Date(2026, 8, 16, 1, 2, 3, 4, time.UTC)),
	}
	client := &fakeRawCommitClient{response: response}
	accepted, classification, err := completeRawCommit(
		context.Background(), client, &spannerpb.CommitRequest{}, operation, attempt,
	)
	if err != nil {
		t.Fatal(err)
	}
	if classification.Outcome != protocol.UnambiguousSuccess || client.calls != 1 {
		t.Fatalf("classification=%v calls=%d", classification.Outcome, client.calls)
	}
	candidate[0], prepared[0], attempt[0] = 'X', 'X', 'X'
	if string(accepted.candidateBytes) != "candidate" ||
		string(accepted.preparedBytes) != "prepared" ||
		string(accepted.transactionAttempt) != "attempt" {
		t.Fatal("accepted context retained mutable caller storage")
	}
	operationCandidate := operation.CandidateBytes()
	operationCandidate[0] = 'X'
	if string(accepted.candidateBytes) != "candidate" {
		t.Fatal("accepted context shares mutable operation storage")
	}
}

func TestAcceptedContextCannotFollowAmbiguousCommit(t *testing.T) {
	t.Parallel()
	operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))
	client := &fakeRawCommitClient{err: status.Error(codes.DeadlineExceeded, "ambiguous")}
	_, classification, err := completeRawCommit(
		context.Background(), client, &spannerpb.CommitRequest{}, operation, nil,
	)
	if err == nil {
		t.Fatal("ambiguous commit created accepted context")
	}
	if classification.Outcome != protocol.AmbiguousCommitOutcome || client.calls != 1 {
		t.Fatalf("classification=%v calls=%d", classification.Outcome, client.calls)
	}
}

func TestAcceptedContextImplementsNoSerializationInterfaces(t *testing.T) {
	t.Parallel()
	context := acceptedRotationContext{}
	if _, ok := any(context).(json.Marshaler); ok {
		t.Fatal("accepted context implements json.Marshaler")
	}
	if _, ok := any(&context).(json.Unmarshaler); ok {
		t.Fatal("accepted context implements json.Unmarshaler")
	}
	if _, ok := any(context).(encoding.TextMarshaler); ok {
		t.Fatal("accepted context implements encoding.TextMarshaler")
	}
	if _, ok := any(&context).(encoding.TextUnmarshaler); ok {
		t.Fatal("accepted context implements encoding.TextUnmarshaler")
	}
	if _, ok := any(context).(gob.GobEncoder); ok {
		t.Fatal("accepted context implements gob.GobEncoder")
	}
	if _, ok := any(&context).(gob.GobDecoder); ok {
		t.Fatal("accepted context implements gob.GobDecoder")
	}
}
