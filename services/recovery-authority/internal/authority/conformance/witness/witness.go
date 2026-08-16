// Package witness implements an emulator/local-only, filesystem-backed
// stand-in for the GCS Bucket Lock witness used by PREPARED/COMMITTED
// objects. It exists solely to exercise ADR-043's protocol-state
// conformance -- create-only-if-absent semantics, byte-for-byte
// idempotency, exact-key reads, and immutable-after-create behavior in the
// fake -- against something more real than an in-memory map, without
// touching GCS.
//
// LOCAL_WITNESS != GCS_QUALIFICATION.
//
// This package proves nothing about real GCS Bucket Lock: it does not
// exercise retention policies, IAM, object holds, bucket-level lock
// enforcement, regional durability, or any GCS-specific failure mode (e.g.
// eventual consistency of list operations, real network partitions against
// Google's infrastructure). A passing test in this package is evidence only
// that the PREPARE/COMMITTED protocol logic above the storage layer is
// internally consistent; it is not evidence the real GCS adapter (not yet
// built) will behave the same way, and it must never be cited as such.
package witness

import (
	"bytes"
	"context"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"sync"
)

var (
	// ErrObjectAlreadyExists mirrors GCS's ifGenerationMatch=0 precondition
	// failure: an object already exists at this key.
	ErrObjectAlreadyExists = errors.New("witness object already exists")

	// ErrObjectNotFound mirrors a GCS 404 on an exact-key read.
	ErrObjectNotFound = errors.New("witness object not found")

	// ErrConflictingContent is returned by CreateOnlyIfAbsent when an
	// object already exists at this key with DIFFERENT content -- a
	// non-idempotent conflicting create, which must fail. A create with
	// byte-identical content at an existing key is treated as an
	// idempotent no-op success, exactly as the real create-only-if-absent
	// object write is expected to behave under client-side retry.
	ErrConflictingContent = errors.New("witness object exists with conflicting content")
)

// Repository is a local, single-process, filesystem-backed witness store.
// It is not safe for use by more than one process against the same root
// directory (the real GCS object it stands in for is; this fake does not
// need to be, since nothing in this codebase relies on cross-process
// witness access at this tier).
type Repository struct {
	root string
	mu   sync.Mutex
}

func NewRepository(root string) (*Repository, error) {
	if err := os.MkdirAll(root, 0o700); err != nil {
		return nil, err
	}
	return &Repository{root: root}, nil
}

// path maps a witness key to a flat filename by hex-encoding the raw key
// bytes, rather than treating the key as a filesystem path component. This
// preserves exact-key distinctness (e.g. "a" and "a/" are different GCS
// object names and must be different witness objects here too) and, as a
// side effect, makes any attempt to escape the root directory via "../" or
// similar impossible -- the key never reaches the filesystem as a path.
func (r *Repository) path(key string) string {
	return filepath.Join(r.root, hex.EncodeToString([]byte(key)))
}

// CreateOnlyIfAbsent models the create-only object write GCS performs with
// ifGenerationMatch=0: it fails if an object already exists at key with
// different content, but succeeds idempotently (without error) if an
// object already exists with byte-identical content -- because a client
// retrying its own prior successful create must not be told it failed.
func (r *Repository) CreateOnlyIfAbsent(_ context.Context, key string, content []byte) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	path := r.path(key)
	existing, err := os.ReadFile(path)
	if err == nil {
		if bytes.Equal(existing, content) {
			return nil
		}
		return ErrConflictingContent
	}
	if !os.IsNotExist(err) {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	// Write to a temp file then rename, so a concurrent reader never
	// observes a partially written object -- the closest a local
	// filesystem gets to GCS's atomic object-create semantics.
	tmp, err := os.CreateTemp(filepath.Dir(path), ".witness-tmp-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	if _, err := tmp.Write(content); err != nil {
		tmp.Close()
		os.Remove(tmpName)
		return err
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmpName)
		return err
	}
	// Enforce create-only at rename time too: if another create raced in
	// between our not-exist check and now, refuse to clobber it.
	if _, statErr := os.Stat(path); statErr == nil {
		os.Remove(tmpName)
		raced, readErr := os.ReadFile(path)
		if readErr == nil && bytes.Equal(raced, content) {
			return nil
		}
		return ErrObjectAlreadyExists
	}
	if err := os.Rename(tmpName, path); err != nil {
		os.Remove(tmpName)
		return err
	}
	// os.Chmod(path, 0o400) makes the immutability property explicit and
	// observable: any code path that later tries to open the file for
	// writing (rather than going through this package's own, absent,
	// mutation API) fails at the OS level, not just by convention.
	return os.Chmod(path, 0o400)
}

// Read returns the exact bytes stored at key, or ErrObjectNotFound.
func (r *Repository) Read(_ context.Context, key string) ([]byte, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	content, err := os.ReadFile(r.path(key))
	if os.IsNotExist(err) {
		return nil, ErrObjectNotFound
	}
	if err != nil {
		return nil, err
	}
	return content, nil
}

// Exists reports whether an object is present at key, without exposing its
// content -- used by tests that only need to confirm presence.
func (r *Repository) Exists(ctx context.Context, key string) (bool, error) {
	_, err := r.Read(ctx, key)
	if errors.Is(err, ErrObjectNotFound) {
		return false, nil
	}
	return err == nil, err
}
