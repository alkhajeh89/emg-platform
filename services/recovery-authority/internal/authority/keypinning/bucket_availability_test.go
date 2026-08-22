//go:build emulator

package keypinning

// Caller-level regression coverage for the P0 GCS bucket-vs-object-404
// collapse (Wave 2 Track C): proves the gcswitness.Adapter fix propagates
// correctly through GCSStore against a REAL Adapter backed by
// fake-gcs-server.

import (
	"context"
	"errors"
	"net/http"
	"testing"

	"google.golang.org/api/option"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

const nonexistentPinBucket = "keypinning-nonexistent-bucket-never-created"

func realGCSWitnessForPin(t *testing.T, bucket string) gcswitness.ImmutableWitness {
	t.Helper()
	client, err := gcswitness.NewClient(context.Background(),
		option.WithEndpoint("http://localhost:4443/storage/v1/"),
		option.WithoutAuthentication(),
		option.WithHTTPClient(&http.Client{}),
	)
	if err != nil {
		t.Fatalf("gcswitness.NewClient: %v", err)
	}
	t.Cleanup(func() { client.Close() })
	return gcswitness.New(client, bucket)
}

func pinTestKeyID(t *testing.T) protocol.SigningKeyID {
	t.Helper()
	id, err := protocol.NewSigningKeyID("projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	if err != nil {
		t.Fatal(err)
	}
	return id
}

// Item 5 (positive control): existing bucket + missing pin -> ordinary
// ErrPinNotFound, against the REAL Adapter/emulator.
func TestRealAdapterGetReturnsOrdinaryNotFoundWhenBucketExists(t *testing.T) {
	store, err := NewGCSStore(realGCSWitnessForPin(t, "adr043-witness-test"))
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.Get(context.Background(), pinTestKeyID(t))
	if !errors.Is(err, ErrPinNotFound) {
		t.Fatalf("expected ErrPinNotFound for a missing pin in an existing bucket, got: %v", err)
	}
}

// Item 6: a nonexistent/unavailable pin-store bucket must return a
// provider/storage error, NEVER the ordinary ErrPinNotFound -- conflating
// the two would let a misconfigured or deleted pin-store bucket be
// silently treated as "this key was simply never pinned," which is exactly
// the kind of governance-container-unavailability-as-empty-state confusion
// this remediation exists to close.
func TestRealAdapterGetFailsClosedWhenBucketMissing(t *testing.T) {
	store, err := NewGCSStore(realGCSWitnessForPin(t, nonexistentPinBucket))
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.Get(context.Background(), pinTestKeyID(t))
	if err == nil {
		t.Fatal("expected a non-nil error when the pin store's bucket does not exist")
	}
	if errors.Is(err, ErrPinNotFound) {
		t.Fatalf("a missing bucket must NEVER be classified as ErrPinNotFound (ordinary unpinned key) -- got: %v", err)
	}
	t.Logf("EVIDENCE: GCSStore.Get against a nonexistent bucket correctly failed closed, distinct from ErrPinNotFound: %v", err)
}

// Item 7: kmsverifier (this package's downstream consumer via
// keypinning.Store) must never be able to treat a missing-pin-bucket error
// as an ordinary unpinned key that would weaken the authorization/
// verification boundary -- kmsverifier.VerifyCommittedSignature's own code
// (unmodified by this task) wraps ANY non-nil error from pins.Get as
// ErrNoPinnedKey and returns immediately, never distinguishing "genuinely
// unpinned" from "store unavailable" as a reason to proceed differently --
// both fail closed identically. Re-confirmed here structurally: Get's
// error is non-nil and not ErrPinNotFound in the missing-bucket case
// (proven above), which is sufficient for kmsverifier's own
// wrap-and-return-immediately contract to hold.
func TestRealAdapterMissingBucketNeverWeakensVerificationBoundary(t *testing.T) {
	store, err := NewGCSStore(realGCSWitnessForPin(t, nonexistentPinBucket))
	if err != nil {
		t.Fatal(err)
	}
	_, getErr := store.Get(context.Background(), pinTestKeyID(t))
	if getErr == nil {
		t.Fatal("a nil error here would let kmsverifier proceed as if a public key were available when it is not")
	}
}
