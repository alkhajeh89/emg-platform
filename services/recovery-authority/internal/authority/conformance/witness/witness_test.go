package witness

import (
	"context"
	"errors"
	"os"
	"testing"
)

func newTestRepository(t *testing.T) *Repository {
	t.Helper()
	repo, err := NewRepository(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	return repo
}

func TestCreateOnlyIfAbsentSucceedsOnFirstWrite(t *testing.T) {
	repo := newTestRepository(t)
	ctx := context.Background()
	if err := repo.CreateOnlyIfAbsent(ctx, "prepared/op-1", []byte("payload")); err != nil {
		t.Fatal(err)
	}
	content, err := repo.Read(ctx, "prepared/op-1")
	if err != nil {
		t.Fatal(err)
	}
	if string(content) != "payload" {
		t.Fatalf("content = %q, want %q", content, "payload")
	}
}

func TestCreateOnlyIfAbsentIsIdempotentForIdenticalContent(t *testing.T) {
	repo := newTestRepository(t)
	ctx := context.Background()
	if err := repo.CreateOnlyIfAbsent(ctx, "prepared/op-1", []byte("payload")); err != nil {
		t.Fatal(err)
	}
	// A client retrying its own successful create must see success, not an
	// error -- this is what ifGenerationMatch=0 + identical bytes yields
	// against real GCS on a client-side retry of an already-applied write.
	if err := repo.CreateOnlyIfAbsent(ctx, "prepared/op-1", []byte("payload")); err != nil {
		t.Fatalf("idempotent retry failed: %v", err)
	}
}

func TestCreateOnlyIfAbsentRejectsConflictingContentAtSameKey(t *testing.T) {
	repo := newTestRepository(t)
	ctx := context.Background()
	if err := repo.CreateOnlyIfAbsent(ctx, "prepared/op-1", []byte("payload-a")); err != nil {
		t.Fatal(err)
	}
	err := repo.CreateOnlyIfAbsent(ctx, "prepared/op-1", []byte("payload-b"))
	if !errors.Is(err, ErrConflictingContent) {
		t.Fatalf("err = %v, want ErrConflictingContent", err)
	}
	// The original content must be unchanged.
	content, readErr := repo.Read(ctx, "prepared/op-1")
	if readErr != nil {
		t.Fatal(readErr)
	}
	if string(content) != "payload-a" {
		t.Fatalf("content = %q, want original %q (must not be overwritten)", content, "payload-a")
	}
}

func TestReadOfAbsentKeyFails(t *testing.T) {
	repo := newTestRepository(t)
	_, err := repo.Read(context.Background(), "prepared/nonexistent")
	if !errors.Is(err, ErrObjectNotFound) {
		t.Fatalf("err = %v, want ErrObjectNotFound", err)
	}
}

func TestReadIsExactKeyOnly(t *testing.T) {
	repo := newTestRepository(t)
	ctx := context.Background()
	if err := repo.CreateOnlyIfAbsent(ctx, "prepared/op-1", []byte("payload")); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.Read(ctx, "prepared/op-2"); !errors.Is(err, ErrObjectNotFound) {
		t.Fatalf("a different key must not be found: err = %v", err)
	}
	if _, err := repo.Read(ctx, "prepared/op-1/"); !errors.Is(err, ErrObjectNotFound) {
		t.Fatalf("a key differing only by trailing slash must not match: err = %v", err)
	}
}

func TestObjectIsImmutableAfterCreateEvenAtTheFilesystemLevel(t *testing.T) {
	repo := newTestRepository(t)
	ctx := context.Background()
	if err := repo.CreateOnlyIfAbsent(ctx, "prepared/op-1", []byte("payload")); err != nil {
		t.Fatal(err)
	}
	// This package exposes no mutation API at all -- the only way to prove
	// immutability beyond "the API doesn't offer it" is to show that even a
	// direct filesystem write is refused by the OS, because the object was
	// created read-only.
	err := os.WriteFile(repo.path("prepared/op-1"), []byte("tampered"), 0o600)
	if err == nil {
		t.Fatal("expected the filesystem itself to refuse writing over an immutable witness object")
	}
	content, readErr := repo.Read(ctx, "prepared/op-1")
	if readErr != nil {
		t.Fatal(readErr)
	}
	if string(content) != "payload" {
		t.Fatalf("content = %q, want unchanged %q", content, "payload")
	}
}

func TestExistsDoesNotExposeContent(t *testing.T) {
	repo := newTestRepository(t)
	ctx := context.Background()
	found, err := repo.Exists(ctx, "prepared/op-1")
	if err != nil {
		t.Fatal(err)
	}
	if found {
		t.Fatal("expected not found before create")
	}
	if err := repo.CreateOnlyIfAbsent(ctx, "prepared/op-1", []byte("payload")); err != nil {
		t.Fatal(err)
	}
	found, err = repo.Exists(ctx, "prepared/op-1")
	if err != nil {
		t.Fatal(err)
	}
	if !found {
		t.Fatal("expected found after create")
	}
}
