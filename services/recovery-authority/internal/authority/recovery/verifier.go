package recovery

import (
	"context"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// CommittedCheckpointVerifier validates already-persisted COMMITTED bytes.
// Recovery has no creation API and no access to acceptedRotationContext.
type CommittedCheckpointVerifier interface {
	VerifyCommitted(context.Context, []byte, protocol.Digest32) error
}
