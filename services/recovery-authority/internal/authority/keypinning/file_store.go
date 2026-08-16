package keypinning

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// FileStore is a durable, integrity-protected, qualification-grade Store
// implementation backed by one write-once file per SigningKeyID. It is
// suitable for S3 qualification and single-node testing.
//
// IMPLEMENTED here: durability across process restarts; write-once
// filesystem semantics (O_EXCL) giving the same fail-closed-on-conflict
// guarantee as Store.Pin requires, enforced by the OS, not merely by
// in-process bookkeeping; independent fingerprint re-verification on every
// read.
//
// NOT implemented here, and explicitly deferred to S4 (ADR-045 §7C's
// governance properties for the pinned-key storage mechanism -- integrity
// protection, auditability, durability for the full evidence-retention
// horizon, independent verifiability -- ultimately require a provider-backed,
// administratively-governed store with its own access-controlled principal,
// not a local filesystem directory): multi-node replication; administrative
// access control distinct from whatever process account can read this
// directory; retention-horizon enforcement; external audit-log integration.
// This type is not, and must not be represented as, that eventual S4
// mechanism -- it is the qualification-grade local implementation the S3
// interface is designed to be swapped out from underneath without a
// breaking change.
type FileStore struct {
	dir string
}

// NewFileStore opens (creating if necessary) a FileStore rooted at dir. dir
// must already exist or be creatable by the calling process; no ambient
// default location is assumed.
func NewFileStore(dir string) (*FileStore, error) {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, fmt.Errorf("keypinning: create store directory: %w", err)
	}
	return &FileStore{dir: dir}, nil
}

type pinRecord struct {
	SigningKeyID string `json:"signing_key_id"`
	Algorithm    string `json:"algorithm"`
	PublicKeyPEM string `json:"public_key_pem"`
	Fingerprint  string `json:"fingerprint_sha256"`
	PinnedAtUnix int64  `json:"pinned_at_unix"`
	Provenance   string `json:"provenance"`
}

// filenameFor derives a filesystem-safe, content-addressed filename from a
// SigningKeyID. SigningKeyID values (Cloud KMS resource names) contain '/'
// and are too long/variable for direct use as a filename component, so the
// filename is SHA-256(keyID) -- a collision here would require a SHA-256
// preimage/collision, at which point far more than this store is broken.
// The full original keyID string is still recorded inside the file content
// and re-checked on every read (Get), so the filename is purely a lookup
// convenience, never itself a trust decision.
func filenameFor(keyID protocol.SigningKeyID) string {
	sum := sha256.Sum256([]byte(keyID.String()))
	return base64.RawURLEncoding.EncodeToString(sum[:]) + ".json"
}

func (s *FileStore) Pin(_ context.Context, pin PinnedKey) error {
	if pin.SigningKeyID.IsZero() {
		return ErrPinRequiresSigningKeyID
	}
	record := pinRecord{
		SigningKeyID: pin.SigningKeyID.String(),
		Algorithm:    string(pin.Algorithm),
		PublicKeyPEM: pin.PublicKeyPEM,
		Fingerprint:  base64.StdEncoding.EncodeToString(pin.Fingerprint[:]),
		PinnedAtUnix: pin.PinnedAt.Unix(),
		Provenance:   pin.Provenance,
	}
	data, err := json.MarshalIndent(record, "", "  ")
	if err != nil {
		return fmt.Errorf("keypinning: encode pin: %w", err)
	}
	path := filepath.Join(s.dir, filenameFor(pin.SigningKeyID))

	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o400)
	if err == nil {
		defer file.Close()
		if _, writeErr := file.Write(data); writeErr != nil {
			return fmt.Errorf("keypinning: write pin: %w", writeErr)
		}
		return nil
	}
	if !errors.Is(err, os.ErrExist) {
		return fmt.Errorf("keypinning: create pin file: %w", err)
	}

	// A file already exists for this SigningKeyID -- this is only ever
	// safe if it holds byte-identical material (idempotent re-pin).
	// Reading it back through Get (not raw bytes) ensures the same
	// integrity check applies here as everywhere else.
	existing, getErr := s.Get(context.Background(), pin.SigningKeyID)
	if getErr != nil {
		return fmt.Errorf("keypinning: existing pin for this SigningKeyID failed its own integrity check: %w", getErr)
	}
	if existing.Fingerprint != pin.Fingerprint {
		return ErrPinConflict
	}
	return nil
}

func (s *FileStore) Get(_ context.Context, keyID protocol.SigningKeyID) (PinnedKey, error) {
	path := filepath.Join(s.dir, filenameFor(keyID))
	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return PinnedKey{}, ErrPinNotFound
		}
		return PinnedKey{}, fmt.Errorf("keypinning: read pin: %w", err)
	}
	var record pinRecord
	if err := json.Unmarshal(data, &record); err != nil {
		return PinnedKey{}, fmt.Errorf("keypinning: decode pin: %w", err)
	}
	if record.SigningKeyID != keyID.String() {
		return PinnedKey{}, fmt.Errorf("keypinning: stored pin's SigningKeyID %q does not match requested %q -- integrity check failed", record.SigningKeyID, keyID.String())
	}
	storedFingerprint, err := base64.StdEncoding.DecodeString(record.Fingerprint)
	if err != nil || len(storedFingerprint) != 32 {
		return PinnedKey{}, errors.New("keypinning: stored pin has a malformed fingerprint")
	}
	recomputed := computeFingerprint(record.PublicKeyPEM)
	var storedArray [32]byte
	copy(storedArray[:], storedFingerprint)
	if recomputed != storedArray {
		return PinnedKey{}, errors.New("keypinning: stored pin failed integrity check -- fingerprint does not match material")
	}
	return PinnedKey{
		SigningKeyID: keyID,
		Algorithm:    Algorithm(record.Algorithm),
		PublicKeyPEM: record.PublicKeyPEM,
		Fingerprint:  storedArray,
		PinnedAt:     time.Unix(record.PinnedAtUnix, 0).UTC(),
		Provenance:   record.Provenance,
	}, nil
}

var _ Store = (*FileStore)(nil)
