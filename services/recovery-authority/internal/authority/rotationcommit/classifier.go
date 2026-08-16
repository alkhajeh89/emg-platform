package rotationcommit

import (
	"errors"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type SessionMode uint8

const (
	RegularSession SessionMode = iota
	MultiplexedSession
)

type ClassificationReason uint8

const (
	ReasonUnknown ClassificationReason = iota
	ReasonCommitNotInvoked
	ReasonSuccessfulResponse
	ReasonExplicitlyAborted
	ReasonPrecommitToken
	ReasonNonPositiveCommitTimestamp
)

type CommitClassification struct {
	Outcome            protocol.CommitOutcome
	Reason             ClassificationReason
	UnsupportedProfile bool
}

var ErrAcceptedContextUnavailable = errors.New("accepted rotation context unavailable")

// ClassifyCommit defaults to ambiguity unless an allowed positive proof is present.
func ClassifyCommit(
	invoked bool,
	response *spannerpb.CommitResponse,
	commitErr error,
	mode SessionMode,
) CommitClassification {
	if !invoked {
		return CommitClassification{
			Outcome: protocol.UnambiguousNotCommitted,
			Reason:  ReasonCommitNotInvoked,
		}
	}
	if commitErr == nil && response != nil && response.GetPrecommitToken() != nil {
		return CommitClassification{
			Outcome:            protocol.UnambiguousNotCommitted,
			Reason:             ReasonPrecommitToken,
			UnsupportedProfile: true,
		}
	}
	if commitErr != nil && status.Code(commitErr) == codes.Aborted {
		return CommitClassification{
			Outcome: protocol.UnambiguousNotCommitted,
			Reason:  ReasonExplicitlyAborted,
		}
	}
	if commitErr == nil && response != nil && response.GetCommitTimestamp() != nil &&
		response.GetCommitTimestamp().CheckValid() == nil {
		// A structurally valid protobuf Timestamp still admits the zero value
		// (the Unix epoch) and negative values. Spanner's TrueTime-assigned
		// commit timestamps are never legitimately at or before the epoch for
		// this system; official Spanner documentation does not state that a
		// zero or non-positive commit timestamp is a valid successful Commit
		// value, so one is never treated as proof of success. This is a
		// deliberate security decision, not an oversight: only a strictly
		// positive, structurally valid timestamp counts as unambiguous proof.
		if response.GetCommitTimestamp().GetSeconds() > 0 {
			return CommitClassification{
				Outcome: protocol.UnambiguousSuccess,
				Reason:  ReasonSuccessfulResponse,
			}
		}
		return CommitClassification{
			Outcome: protocol.AmbiguousCommitOutcome,
			Reason:  ReasonNonPositiveCommitTimestamp,
		}
	}
	return CommitClassification{Outcome: protocol.AmbiguousCommitOutcome, Reason: ReasonUnknown}
}
