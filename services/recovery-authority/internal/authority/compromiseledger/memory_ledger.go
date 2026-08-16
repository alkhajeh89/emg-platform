package compromiseledger

import (
	"context"
	"sync"
	"time"
)

// MemoryLedger is a non-durable, append-only Ledger for unit tests only.
// Not suitable for qualification or production use -- see FileLedger.
type MemoryLedger struct {
	mu      sync.Mutex
	records []DistrustRecord
}

func NewMemoryLedger() *MemoryLedger {
	return &MemoryLedger{}
}

func (l *MemoryLedger) Declare(_ context.Context, record DistrustRecord) error {
	if err := record.validate(); err != nil {
		return err
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	// Append-only: copy, never reference the caller's record, and never
	// provide any way to reach back into l.records for mutation.
	l.records = append(l.records, record)
	return nil
}

func (l *MemoryLedger) Status(_ context.Context, subject string, asOf time.Time) (Status, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	snapshot := make([]DistrustRecord, len(l.records))
	copy(snapshot, l.records)
	return EvaluateStatus(snapshot, subject, asOf), nil
}

var _ Ledger = (*MemoryLedger)(nil)
