package protocol

// CommitOutcome is the security classification of one Commit invocation.
type CommitOutcome uint8

const (
	AmbiguousCommitOutcome CommitOutcome = iota
	UnambiguousSuccess
	UnambiguousNotCommitted
)

func (outcome CommitOutcome) String() string {
	switch outcome {
	case UnambiguousSuccess:
		return "UNAMBIGUOUS_SUCCESS"
	case UnambiguousNotCommitted:
		return "UNAMBIGUOUS_NOT_COMMITTED"
	default:
		return "AMBIGUOUS_COMMIT_OUTCOME"
	}
}
