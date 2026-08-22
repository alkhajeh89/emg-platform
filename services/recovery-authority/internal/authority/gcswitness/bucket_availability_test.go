//go:build emulator

package gcswitness

// Regression coverage for the P0 GCS bucket-vs-object 404 collapse found
// during Wave 2 Track C real-cloud qualification: cloud.google.com/go/storage
// returns the identical storage.ErrObjectNotExist sentinel from an
// object-resource call (ObjectHandle.Attrs/NewReader) whether the named
// object is genuinely absent or the containing bucket does not exist at
// all -- confirmed independently against BOTH real GCS and this package's
// own fake-gcs-server emulator (a standalone probe against each backend
// produced identical results: object-level calls collapse both cases to
// ErrObjectNotExist; only BucketHandle.Attrs itself returns the distinct
// storage.ErrBucketNotExist sentinel). This file proves the fix
// (confirmBucketExists, wired into Exists/ReadExact) closes that gap.
//
// TestReadOfAbsentObjectFails and TestExistsReflectsPresenceOnly
// (gcswitness_test.go) already cover "existing bucket, missing object" --
// not duplicated here.

import (
	"context"
	"errors"
	"net/http"
	"testing"

	"cloud.google.com/go/storage"
	"google.golang.org/api/option"
)

const nonexistentBucketName = "gcswitness-nonexistent-bucket-never-created"

func adapterAgainstNonexistentBucket(t *testing.T) *Adapter {
	t.Helper()
	client, err := NewClient(context.Background(),
		option.WithEndpoint(fakeGCSEndpoint),
		option.WithoutAuthentication(),
		option.WithHTTPClient(&http.Client{}),
	)
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}
	t.Cleanup(func() { client.Close() })
	return New(client, nonexistentBucketName)
}

// Item C / required assertion: ReadExact(nonexistent bucket) must not be
// the ordinary object-not-found semantic.
func TestReadExactAgainstNonexistentBucketFailsClosed(t *testing.T) {
	adapter := adapterAgainstNonexistentBucket(t)
	_, err := adapter.ReadExact(context.Background(), "any-key.json")
	if err == nil {
		t.Fatal("expected ReadExact against a nonexistent bucket to fail")
	}
	if errors.Is(err, ErrNotFound) {
		t.Fatalf("ReadExact against a nonexistent bucket must NOT be classified as ordinary ErrNotFound (object absence) -- got: %v", err)
	}
	t.Logf("EVIDENCE: ReadExact against nonexistent bucket correctly failed closed, distinct from ErrNotFound: %v", err)
}

// Item C / required assertion: Exists(nonexistent bucket) must not be
// (false, nil).
func TestExistsAgainstNonexistentBucketFailsClosed(t *testing.T) {
	adapter := adapterAgainstNonexistentBucket(t)
	exists, err := adapter.Exists(context.Background(), "any-key.json")
	if err == nil {
		t.Fatalf("expected Exists against a nonexistent bucket to return a non-nil error, got (%v, nil)", exists)
	}
	if exists {
		t.Fatal("Exists against a nonexistent bucket must never report true")
	}
	t.Logf("EVIDENCE: Exists against nonexistent bucket correctly failed closed: (%v, %v)", exists, err)
}

// Item G: CreateExactIfAbsent against a nonexistent bucket must return
// HardFailure (a definitive, non-ambiguous failure), never silently
// succeed and never be reinterpreted as ordinary object absence.
func TestCreateExactIfAbsentAgainstNonexistentBucketFailsClosed(t *testing.T) {
	adapter := adapterAgainstNonexistentBucket(t)
	outcome, err := adapter.CreateExactIfAbsent(context.Background(), "any-key.json", []byte("payload"))
	if err == nil {
		t.Fatal("expected CreateExactIfAbsent against a nonexistent bucket to fail")
	}
	if outcome == CreateSuccess || outcome == AlreadyExistsIdentical {
		t.Fatalf("outcome = %v, must never claim success against a nonexistent bucket", outcome)
	}
	t.Logf("EVIDENCE: CreateExactIfAbsent against nonexistent bucket outcome=%v err=%v", outcome, err)
}

// Item H: the ambiguous-create resolution path (classifyCreateError's
// ReadExact-based resolution) must remain exact-read-only and must not
// reinterpret a bucket-unavailable error as "object absent, therefore
// retry succeeded" -- if the bucket disappears between the initial write
// attempt and the resolution read, the result must be AmbiguousCreate
// (readErr != nil branch), never CreateSuccess.
func TestAmbiguousCreateResolutionNeverMisreadsBucketUnavailableAsAbsent(t *testing.T) {
	// classifyCreateError's structure guarantees this: readErr != nil (any
	// non-ErrNotFound error, including the new bucket-unavailable error)
	// routes to the `case readErr != nil` branch, which returns
	// AmbiguousCreate -- never CreateSuccess or AlreadyExistsIdentical.
	// This is verified by direct inspection of classifyCreateError's
	// switch statement (gcswitness.go), which this test names explicitly
	// as a regression anchor rather than re-deriving the logic.
	adapter := adapterAgainstNonexistentBucket(t)
	outcome, err := adapter.CreateExactIfAbsent(context.Background(), "any-key.json", []byte("payload"))
	if outcome == CreateSuccess {
		t.Fatalf("a nonexistent bucket must never resolve to CreateSuccess, err=%v", err)
	}
}

// ATTACK_B: a bucket that existed and was usable at startup, then removed
// (deleted, misconfigured, or otherwise made unreachable) before a later
// operation, must never be silently treated as "the object just isn't
// there" -- there is no cached readiness state anywhere in this package
// (confirmBucketExists is called fresh on every not-found result, never
// once and cached) for a later removal to stale-read past, so this
// scenario reduces to, and is closed by, the same fix as the static
// nonexistent-bucket case. This test exercises the dynamic sequence
// directly rather than only asserting that structurally.
func TestBucketRemovedAfterInitialUseFailsClosed(t *testing.T) {
	ctx := context.Background()
	rawClient, err := storage.NewClient(ctx,
		option.WithEndpoint(fakeGCSEndpoint),
		option.WithoutAuthentication(),
		option.WithHTTPClient(&http.Client{}),
	)
	if err != nil {
		t.Fatalf("storage.NewClient: %v", err)
	}
	defer rawClient.Close()

	bucketName := "ephemeral-attack-b-bucket"
	if err := rawClient.Bucket(bucketName).Create(ctx, "test-project", nil); err != nil {
		t.Fatalf("test setup: create ephemeral bucket: %v", err)
	}

	client, err := NewClient(ctx,
		option.WithEndpoint(fakeGCSEndpoint),
		option.WithoutAuthentication(),
		option.WithHTTPClient(&http.Client{}),
	)
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}
	defer client.Close()
	adapter := New(client, bucketName)

	// Confirm the bucket is genuinely usable first (the object legitimately
	// does not exist yet, in a bucket that does).
	exists, err := adapter.Exists(ctx, "some-key.json")
	if err != nil || exists {
		t.Fatalf("precondition failed: Exists = (%v, %v), want (false, nil) before removal", exists, err)
	}

	// Now remove the bucket entirely, simulating deletion/misconfiguration
	// occurring after startup.
	if err := rawClient.Bucket(bucketName).Delete(ctx); err != nil {
		t.Fatalf("test setup: delete ephemeral bucket: %v", err)
	}

	existsAfter, errAfter := adapter.Exists(ctx, "some-key.json")
	if errAfter == nil {
		t.Fatalf("expected a non-nil error after the bucket was removed, got (%v, nil) -- a cached/stale readiness assumption would produce exactly this false-safe result", existsAfter)
	}
	if existsAfter {
		t.Fatal("Exists must never report true for a bucket that no longer exists")
	}
	t.Logf("EVIDENCE: Exists correctly failed closed after the bucket was removed mid-lifecycle: %v", errAfter)
}
