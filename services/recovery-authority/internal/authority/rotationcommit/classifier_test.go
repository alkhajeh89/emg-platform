package rotationcommit

import (
	"testing"
	"time"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func TestCommitClassification(t *testing.T) {
	t.Parallel()
	validResponse := &spannerpb.CommitResponse{
		CommitTimestamp: timestamppb.New(time.Date(2026, 8, 16, 1, 2, 3, 4, time.UTC)),
	}
	precommitResponse := &spannerpb.CommitResponse{
		MultiplexedSessionRetry: &spannerpb.CommitResponse_PrecommitToken{
			PrecommitToken: &spannerpb.MultiplexedSessionPrecommitToken{
				PrecommitToken: []byte("opaque"),
				SeqNum:         2,
			},
		},
	}
	tests := []struct {
		name        string
		invoked     bool
		response    *spannerpb.CommitResponse
		err         error
		mode        SessionMode
		want        protocol.CommitOutcome
		unsupported bool
	}{
		{"not invoked", false, nil, nil, RegularSession, protocol.UnambiguousNotCommitted, false},
		{"success", true, validResponse, nil, RegularSession, protocol.UnambiguousSuccess, false},
		{"aborted", true, nil, status.Error(codes.Aborted, "ignored"), RegularSession, protocol.UnambiguousNotCommitted, false},
		{"deadline", true, nil, status.Error(codes.DeadlineExceeded, "ignored"), RegularSession, protocol.AmbiguousCommitOutcome, false},
		{"unavailable", true, nil, status.Error(codes.Unavailable, "ignored"), RegularSession, protocol.AmbiguousCommitOutcome, false},
		{"unknown", true, nil, status.Error(codes.Unknown, "ignored"), RegularSession, protocol.AmbiguousCommitOutcome, false},
		{"internal", true, nil, status.Error(codes.Internal, "ignored"), RegularSession, protocol.AmbiguousCommitOutcome, false},
		{"cancelled", true, nil, status.Error(codes.Canceled, "ignored"), RegularSession, protocol.AmbiguousCommitOutcome, false},
		{"resource exhausted", true, nil, status.Error(codes.ResourceExhausted, "ignored"), RegularSession, protocol.AmbiguousCommitOutcome, false},
		{"unknown numeric status", true, nil, status.Error(codes.Code(99), "ignored"), RegularSession, protocol.AmbiguousCommitOutcome, false},
		{"nil response", true, nil, nil, RegularSession, protocol.AmbiguousCommitOutcome, false},
		{"malformed timestamp", true, &spannerpb.CommitResponse{CommitTimestamp: &timestamppb.Timestamp{Seconds: 253402300800}}, nil, RegularSession, protocol.AmbiguousCommitOutcome, false},
		{"precommit regular session", true, precommitResponse, nil, RegularSession, protocol.UnambiguousNotCommitted, true},
		{"precommit multiplexed session", true, precommitResponse, nil, MultiplexedSession, protocol.UnambiguousNotCommitted, true},
	}
	for _, test := range tests {
		test := test
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()
			got := ClassifyCommit(test.invoked, test.response, test.err, test.mode)
			if got.Outcome != test.want || got.UnsupportedProfile != test.unsupported {
				t.Fatalf("classification = %+v, want outcome %v unsupported=%v", got, test.want, test.unsupported)
			}
		})
	}
}

// TestResponseContentNeverOverridesANonAbortedError proves the classifier
// consults the error before it ever inspects response content: an attacker
// or a buggy transport cannot smuggle a plausible-looking success response
// alongside a non-Aborted error and have the response win.
func TestResponseContentNeverOverridesANonAbortedError(t *testing.T) {
	t.Parallel()
	successLookingResponse := &spannerpb.CommitResponse{
		CommitTimestamp: timestamppb.New(time.Date(2026, 8, 16, 1, 2, 3, 4, time.UTC)),
	}
	unsafeCodes := []codes.Code{
		codes.DeadlineExceeded,
		codes.Unavailable,
		codes.Unknown,
		codes.Internal,
		codes.Canceled,
		codes.ResourceExhausted,
		codes.InvalidArgument,
		codes.FailedPrecondition,
		codes.PermissionDenied,
		codes.Unauthenticated,
		codes.NotFound,
		codes.AlreadyExists,
	}
	for _, code := range unsafeCodes {
		got := ClassifyCommit(true, successLookingResponse, status.Error(code, "ignored"), RegularSession)
		if got.Outcome != protocol.AmbiguousCommitOutcome {
			t.Fatalf("code %v with success-looking response classified as %v", code, got.Outcome)
		}
	}
}

// TestNonPositiveCommitTimestampNeverSucceeds is the explicit security
// decision required for zero and negative commit timestamps: a structurally
// valid protobuf Timestamp is not, by itself, proof of a genuine Spanner
// commit. Official Spanner documentation does not establish that a zero or
// negative commit timestamp is a valid successful Commit value, so none of
// these classify as UnambiguousSuccess.
func TestNonPositiveCommitTimestampNeverSucceeds(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name      string
		timestamp *timestamppb.Timestamp
	}{
		{"nil timestamp", nil},
		{"zero timestamp", &timestamppb.Timestamp{Seconds: 0, Nanos: 0}},
		{"negative timestamp", &timestamppb.Timestamp{Seconds: -1, Nanos: 0}},
		{"structurally invalid timestamp", &timestamppb.Timestamp{Seconds: 253402300800}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()
			response := &spannerpb.CommitResponse{CommitTimestamp: test.timestamp}
			got := ClassifyCommit(true, response, nil, RegularSession)
			if got.Outcome == protocol.UnambiguousSuccess {
				t.Fatalf("timestamp %v classified as UnambiguousSuccess", test.timestamp)
			}
		})
	}
	positive := &spannerpb.CommitResponse{CommitTimestamp: &timestamppb.Timestamp{Seconds: 1, Nanos: 0}}
	if got := ClassifyCommit(true, positive, nil, RegularSession); got.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("positive timestamp classified as %v, want UnambiguousSuccess", got.Outcome)
	}
}

func TestOnlyAbortedErrorIsSafe(t *testing.T) {
	t.Parallel()
	unsafeCodes := []codes.Code{
		codes.InvalidArgument,
		codes.FailedPrecondition,
		codes.PermissionDenied,
		codes.Unauthenticated,
		codes.ResourceExhausted,
		codes.Internal,
		codes.NotFound,
		codes.Unavailable,
		codes.DeadlineExceeded,
		codes.Unknown,
		codes.Canceled,
		codes.AlreadyExists,
	}
	for _, code := range unsafeCodes {
		got := ClassifyCommit(true, nil, status.Error(code, "message must not matter"), RegularSession)
		if got.Outcome != protocol.AmbiguousCommitOutcome {
			t.Fatalf("code %v classified as %v", code, got.Outcome)
		}
	}
}
