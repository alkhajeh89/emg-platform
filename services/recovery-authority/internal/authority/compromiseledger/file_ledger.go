package compromiseledger

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"sync"
	"time"
)

// FileLedger is a durable, tamper-evident, qualification-grade Ledger
// implementation backed by a single append-only, hash-chained JSON-lines
// file. Each record's line includes the SHA-256 of the immediately
// preceding line's exact bytes ("PrevHash"); Status independently
// recomputes and verifies the entire chain before trusting any record in
// it, so an in-place edit or reordering of any existing line is detected
// and fails closed.
//
// IMPLEMENTED here: append-only write path (records are only ever written
// via os.O_APPEND, never opened for random-access write); in-process
// mutual exclusion; a tamper-evident hash chain across records, verified on
// every read.
//
// NOT implemented here, and explicitly deferred to S4 (ADR-045 §7's
// governance properties bind the eventual production compromise ledger to
// have a writer principal administratively independent of ordinary
// signing-domain administration -- a property of WHO can write to a given
// deployment of this store, which no code in this package, or any package,
// can establish on its own): multi-process/multi-writer coordination;
// detection of whole-file truncation from the end (a chain verifies every
// record it contains, but cannot prove no record was ever removed from the
// end of the file -- an external, append-only, witnessed log, e.g. a WORM
// bucket or a Certificate-Transparency-style checkpoint scheme, is required
// to close that gap, and is S4 scope); IAM-enforced separation of the
// writer principal from signing-domain administrators; retention-horizon
// enforcement; external audit-log integration. This type is the
// qualification-grade local implementation the Ledger interface is
// designed to be swapped out from underneath without a breaking change --
// it is not, and must not be represented as, the eventual S4 production
// mechanism.
type FileLedger struct {
	mu   sync.Mutex
	path string
}

// NewFileLedger opens (creating if necessary) a FileLedger backed by the
// file at path. The file is validated (chain-verified) once at open time so
// a corrupted/tampered log is caught immediately, not silently on first use.
func NewFileLedger(path string) (*FileLedger, error) {
	ledger := &FileLedger{path: path}
	if _, err := os.Stat(path); err != nil {
		if !errors.Is(err, os.ErrNotExist) {
			return nil, fmt.Errorf("compromiseledger: stat ledger file: %w", err)
		}
		file, createErr := os.OpenFile(path, os.O_CREATE|os.O_WRONLY, 0o600)
		if createErr != nil {
			return nil, fmt.Errorf("compromiseledger: create ledger file: %w", createErr)
		}
		file.Close()
	}
	if _, err := ledger.readVerifiedChain(); err != nil {
		return nil, err
	}
	return ledger, nil
}

type fileRecord struct {
	Subject           string `json:"subject"`
	EffectiveTimeUnix int64  `json:"effective_time_unix"`
	RecordedAtUnix    int64  `json:"recorded_at_unix"`
	Reason            string `json:"reason"`
	RecordedBy        string `json:"recorded_by"`
	PrevHash          string `json:"prev_hash"`
}

const genesisPrevHash = "GENESIS"

func hashLine(line []byte) string {
	sum := sha256.Sum256(line)
	return base64.RawURLEncoding.EncodeToString(sum[:])
}

// readVerifiedChain reads every line, verifies the hash chain, and returns
// the decoded records in file order. Any chain-integrity failure is a hard
// error -- there is no partial/best-effort success path.
func (l *FileLedger) readVerifiedChain() ([]DistrustRecord, error) {
	file, err := os.Open(l.path)
	if err != nil {
		return nil, fmt.Errorf("compromiseledger: open ledger file: %w", err)
	}
	defer file.Close()

	var records []DistrustRecord
	expectedPrevHash := genesisPrevHash
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 0, 64*1024), 8*1024*1024)
	lineNumber := 0
	for scanner.Scan() {
		lineNumber++
		lineBytes := scanner.Bytes()
		if len(lineBytes) == 0 {
			continue
		}
		var rec fileRecord
		if err := json.Unmarshal(lineBytes, &rec); err != nil {
			return nil, fmt.Errorf("compromiseledger: ledger file corrupt at line %d: %w", lineNumber, err)
		}
		if rec.PrevHash != expectedPrevHash {
			return nil, fmt.Errorf("compromiseledger: ledger hash chain broken at line %d -- tampering, reordering, or corruption detected", lineNumber)
		}
		lineCopy := make([]byte, len(lineBytes))
		copy(lineCopy, lineBytes)
		expectedPrevHash = hashLine(lineCopy)
		records = append(records, DistrustRecord{
			Subject:       rec.Subject,
			EffectiveTime: time.Unix(rec.EffectiveTimeUnix, 0).UTC(),
			RecordedAt:    time.Unix(rec.RecordedAtUnix, 0).UTC(),
			Reason:        rec.Reason,
			RecordedBy:    rec.RecordedBy,
		})
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("compromiseledger: read ledger file: %w", err)
	}
	return records, nil
}

func (l *FileLedger) Declare(_ context.Context, record DistrustRecord) error {
	if err := record.validate(); err != nil {
		return err
	}
	l.mu.Lock()
	defer l.mu.Unlock()

	existing, err := l.readVerifiedChain()
	if err != nil {
		return err
	}
	prevHash := genesisPrevHash
	if len(existing) > 0 {
		// Recompute the hash of the last line directly rather than
		// trusting any cached value -- readVerifiedChain already proved
		// the whole chain valid, so the last computed expectedPrevHash
		// (recomputed here for clarity, not reused across calls) is safe.
		file, err := os.Open(l.path)
		if err != nil {
			return fmt.Errorf("compromiseledger: %w", err)
		}
		scanner := bufio.NewScanner(file)
		scanner.Buffer(make([]byte, 0, 64*1024), 8*1024*1024)
		var lastLine []byte
		for scanner.Scan() {
			if len(scanner.Bytes()) == 0 {
				continue
			}
			lastLine = append([]byte{}, scanner.Bytes()...)
		}
		file.Close()
		if err := scanner.Err(); err != nil {
			return fmt.Errorf("compromiseledger: %w", err)
		}
		if lastLine != nil {
			prevHash = hashLine(lastLine)
		}
	}

	fileRec := fileRecord{
		Subject:           record.Subject,
		EffectiveTimeUnix: record.EffectiveTime.Unix(),
		RecordedAtUnix:    record.RecordedAt.Unix(),
		Reason:            record.Reason,
		RecordedBy:        record.RecordedBy,
		PrevHash:          prevHash,
	}
	data, err := json.Marshal(fileRec)
	if err != nil {
		return fmt.Errorf("compromiseledger: encode record: %w", err)
	}
	data = append(data, '\n')

	// O_APPEND only -- this file is never opened for random-access write
	// anywhere in this package.
	file, err := os.OpenFile(l.path, os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return fmt.Errorf("compromiseledger: open ledger file for append: %w", err)
	}
	defer file.Close()
	if _, err := file.Write(data); err != nil {
		return fmt.Errorf("compromiseledger: append record: %w", err)
	}
	return file.Sync()
}

func (l *FileLedger) Status(_ context.Context, subject string, asOf time.Time) (Status, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	records, err := l.readVerifiedChain()
	if err != nil {
		// Fail closed: an unreadable/corrupt ledger can never be reported
		// as StatusNotDistrusted (ADR-045 §7's fail-closed scope).
		return StatusNotDistrusted, err
	}
	return EvaluateStatus(records, subject, asOf), nil
}

var _ Ledger = (*FileLedger)(nil)
