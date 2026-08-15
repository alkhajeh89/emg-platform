package rotationcommit

import (
	"context"
	"errors"
	"testing"
	"time"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// This file is a TEST-ONLY, no-network failure-injection harness. It performs
// no I/O and never constructs a real Spanner or GCS client. It exists to
// exercise completeRawCommit against every commit-outcome shape ADR-043's
// protocol review enumerated, using the fake RawCommitClient already defined
// in this package's tests.
//
// It does not, and cannot, test "no Spanner row/read reconstruction path
// exists" or "no public API can construct acceptedRotationContext" as a
// runtime assertion — those are structural absence properties already
// covered by TestAuthorityImportBoundary and
// TestAcceptedContextHasNoExportedTypeOrConstructor in boundary_test.go,
// which scan the package's own non-test source. This harness only asserts
// completeRawCommit's observable call and outcome behavior.

type failureInjectionScenario struct {
	name           string
	response       *spannerpb.CommitResponse
	err            error
	wantOutcome    protocol.CommitOutcome
	wantContext    bool
	wantErrIsSetup bool
}

func TestFailureInjectionHarness(t *testing.T) {
	t.Parallel()

	validTimestamp := timestamppb.New(time.Date(2026, 8, 16, 1, 2, 3, 4, time.UTC))
	precommitResponse := &spannerpb.CommitResponse{
		MultiplexedSessionRetry: &spannerpb.CommitResponse_PrecommitToken{
			PrecommitToken: &spannerpb.MultiplexedSessionPrecommitToken{
				PrecommitToken: []byte("opaque"),
				SeqNum:         1,
			},
		},
	}

	scenarios := []failureInjectionScenario{
		{
			name:        "1 normal Commit success",
			response:    &spannerpb.CommitResponse{CommitTimestamp: validTimestamp},
			wantOutcome: protocol.UnambiguousSuccess,
			wantContext: true,
		},
		{
			name:        "2 ABORTED",
			err:         status.Error(codes.Aborted, "concurrent modification"),
			wantOutcome: protocol.UnambiguousNotCommitted,
		},
		{
			name:        "3 DEADLINE_EXCEEDED",
			err:         status.Error(codes.DeadlineExceeded, "deadline"),
			wantOutcome: protocol.AmbiguousCommitOutcome,
		},
		{
			name:        "4 UNAVAILABLE",
			err:         status.Error(codes.Unavailable, "unavailable"),
			wantOutcome: protocol.AmbiguousCommitOutcome,
		},
		{
			name:        "5 UNKNOWN",
			err:         status.Error(codes.Unknown, "unknown"),
			wantOutcome: protocol.AmbiguousCommitOutcome,
		},
		{
			name:        "6 INTERNAL",
			err:         status.Error(codes.Internal, "internal"),
			wantOutcome: protocol.AmbiguousCommitOutcome,
		},
		{
			name:        "7 CANCELLED",
			err:         status.Error(codes.Canceled, "cancelled"),
			wantOutcome: protocol.AmbiguousCommitOutcome,
		},
		{
			name:        "8 RESOURCE_EXHAUSTED",
			err:         status.Error(codes.ResourceExhausted, "resource exhausted"),
			wantOutcome: protocol.AmbiguousCommitOutcome,
		},
		{
			name:        "9 arbitrary non-gRPC error",
			err:         errors.New("some non-status error"),
			wantOutcome: protocol.AmbiguousCommitOutcome,
		},
		{
			name:        "10 nil response nil error",
			response:    nil,
			err:         nil,
			wantOutcome: protocol.AmbiguousCommitOutcome,
		},
		{
			name:        "11 response and non-nil error",
			response:    &spannerpb.CommitResponse{CommitTimestamp: validTimestamp},
			err:         status.Error(codes.Internal, "should not override"),
			wantOutcome: protocol.AmbiguousCommitOutcome,
		},
		{
			name:        "12 malformed/zero timestamp",
			response:    &spannerpb.CommitResponse{CommitTimestamp: &timestamppb.Timestamp{Seconds: 0}},
			wantOutcome: protocol.AmbiguousCommitOutcome,
		},
		{
			name:        "13 simulated transport reset",
			err:         errors.New("connection reset by peer"),
			wantOutcome: protocol.AmbiguousCommitOutcome,
		},
		{
			name:        "precommit token (defensive not-committed result)",
			response:    precommitResponse,
			wantOutcome: protocol.UnambiguousNotCommitted,
		},
	}

	for _, scenario := range scenarios {
		scenario := scenario
		t.Run(scenario.name, func(t *testing.T) {
			t.Parallel()
			operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))
			client := &fakeRawCommitClient{response: scenario.response, err: scenario.err}

			accepted, classification, err := completeRawCommit(
				context.Background(), client, &spannerpb.CommitRequest{}, operation, []byte("attempt"),
			)

			// Scenario 14: multiple invocation counter — completeRawCommit must
			// invoke Commit exactly once per call, regardless of outcome.
			if client.calls != 1 {
				t.Fatalf("client.calls = %d, want exactly 1 (no internal retry)", client.calls)
			}

			if classification.Outcome != scenario.wantOutcome {
				t.Fatalf("classification.Outcome = %v, want %v", classification.Outcome, scenario.wantOutcome)
			}

			if scenario.wantContext {
				if err != nil {
					t.Fatalf("unexpected error for a valid direct success: %v", err)
				}
				if len(accepted.candidateBytes) == 0 {
					t.Fatal("expected a populated accepted context for unambiguous success")
				}
			} else {
				if err == nil {
					t.Fatalf("outcome %v produced no error: an accepted context may have been created", classification.Outcome)
				}
				if !errors.Is(err, ErrAcceptedContextUnavailable) {
					t.Fatalf("err = %v, want ErrAcceptedContextUnavailable", err)
				}
				if len(accepted.candidateBytes) != 0 {
					t.Fatal("non-success outcome produced a populated accepted context")
				}
			}
		})
	}
}

// TestFailureInjectionHarnessRetryDetection proves that completeRawCommit
// itself never retries an ambiguous outcome. Retrying an ambiguous Commit is
// the caller's decision (a fresh operation with a fresh operation_id, per the
// ADR-043 protocol), never something this function does on its own.
func TestFailureInjectionHarnessRetryDetection(t *testing.T) {
	t.Parallel()
	operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))
	client := &fakeRawCommitClient{err: status.Error(codes.Unavailable, "ignored")}

	_, first, firstErr := completeRawCommit(
		context.Background(), client, &spannerpb.CommitRequest{}, operation, nil,
	)
	if client.calls != 1 {
		t.Fatalf("after first ambiguous attempt, client.calls = %d, want 1", client.calls)
	}
	if first.Outcome != protocol.AmbiguousCommitOutcome || firstErr == nil {
		t.Fatalf("first attempt classification = %+v, err = %v", first, firstErr)
	}

	// A second, independent call is the CALLER retrying — completeRawCommit
	// has no memory of the first attempt and performs exactly one more Commit,
	// never more. This is what distinguishes caller-orchestrated retry (fine,
	// and out of this function's scope) from automatic internal retry
	// (forbidden).
	_, second, secondErr := completeRawCommit(
		context.Background(), client, &spannerpb.CommitRequest{}, operation, nil,
	)
	if client.calls != 2 {
		t.Fatalf("after second explicit attempt, client.calls = %d, want 2", client.calls)
	}
	if second.Outcome != protocol.AmbiguousCommitOutcome || secondErr == nil {
		t.Fatalf("second attempt classification = %+v, err = %v", second, secondErr)
	}
}

// TestFailureInjectionHarnessNeverConstructsContextWithoutSuccess is a final,
// explicit cross-check: across every ambiguous and unambiguous-not-committed
// scenario in this harness, no accepted context is ever observable outside a
// direct, unambiguous success. There is no exported accessor for
// acceptedRotationContext's fields; this test only confirms completeRawCommit
// returns the reported error whenever it does not return a usable context.
func TestFailureInjectionHarnessNeverConstructsContextWithoutSuccess(t *testing.T) {
	t.Parallel()
	notCommittedOrAmbiguous := []error{
		status.Error(codes.Aborted, "ignored"),
		status.Error(codes.DeadlineExceeded, "ignored"),
		status.Error(codes.Unavailable, "ignored"),
		errors.New("non-status transport error"),
	}
	for _, injectedErr := range notCommittedOrAmbiguous {
		injectedErr := injectedErr
		operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))
		client := &fakeRawCommitClient{err: injectedErr}
		accepted, classification, err := completeRawCommit(
			context.Background(), client, &spannerpb.CommitRequest{}, operation, nil,
		)
		if classification.Outcome == protocol.UnambiguousSuccess {
			t.Fatalf("injected error %v classified as UnambiguousSuccess", injectedErr)
		}
		if err == nil {
			t.Fatalf("injected error %v produced a nil error from completeRawCommit", injectedErr)
		}
		if len(accepted.candidateBytes) != 0 || len(accepted.preparedBytes) != 0 {
			t.Fatalf("injected error %v produced a non-empty accepted context", injectedErr)
		}
	}
}
