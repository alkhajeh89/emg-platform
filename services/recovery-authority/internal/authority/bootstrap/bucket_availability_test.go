//go:build emulator

package bootstrap

// Caller-level regression coverage for the P0 GCS bucket-vs-object-404
// collapse (Wave 2 Track C): proves CheckWitnessPreconditions correctly
// fails closed when the witness bucket itself does not exist, against a
// REAL gcswitness.Adapter backed by fake-gcs-server -- not a hand-written
// fake witness. No code change was required in this package: the fix in
// gcswitness.Adapter.Exists is sufficient, since CheckWitnessPreconditions
// (preconditions.go) already wraps any non-nil Exists error as
// ErrWitnessTargetUnavailable and never treats it as "safe, empty witness
// namespace." This file exists to prove that end-to-end, not to change
// behavior.

import (
	"context"
	"errors"
	"net/http"
	"testing"

	"google.golang.org/api/option"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
)

const nonexistentWitnessBucket = "bootstrap-witness-nonexistent-bucket-never-created"

func realGCSWitnessForBootstrap(t *testing.T, bucket string) gcswitness.ImmutableWitness {
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

// Item 8 (positive control): a valid, existing, empty witness bucket ->
// Exists reports false, nil (ordinary "genesis has not happened yet")
// against the REAL Adapter/emulator.
func TestRealAdapterWitnessExistsFalseWhenBucketExistsButKeyDoesNot(t *testing.T) {
	witness := realGCSWitnessForBootstrap(t, "adr043-witness-test")
	alreadyExists, err := CheckWitnessPreconditions(context.Background(), WitnessPreconditions{Witness: witness}, "genesis/never-created-"+t.Name()+".json")
	if err != nil {
		t.Fatalf("CheckWitnessPreconditions against an existing bucket with no witness object must not error, got: %v", err)
	}
	if alreadyExists {
		t.Fatal("expected alreadyExists=false for a witness key that was never created")
	}
}

// Item 9/10: a nonexistent witness bucket must fail CheckWitnessPreconditions
// closed (non-nil error, wrapping ErrWitnessTargetUnavailable) -- it must
// NEVER be treated as "safe empty witness namespace, proceed with genesis."
// This is the direct bootstrap-level regression test for the P0 finding.
func TestRealAdapterWitnessPreconditionsFailClosedWhenBucketMissing(t *testing.T) {
	witness := realGCSWitnessForBootstrap(t, nonexistentWitnessBucket)
	alreadyExists, err := CheckWitnessPreconditions(context.Background(), WitnessPreconditions{Witness: witness}, "genesis/any-key.json")
	if err == nil {
		t.Fatalf("expected CheckWitnessPreconditions to fail when the witness bucket does not exist, got alreadyExists=%v err=nil -- bootstrap must never treat a missing bucket as a safe empty witness namespace", alreadyExists)
	}
	if !errors.Is(err, ErrWitnessTargetUnavailable) {
		t.Fatalf("expected ErrWitnessTargetUnavailable, got: %v", err)
	}
	t.Logf("EVIDENCE: CheckWitnessPreconditions against a nonexistent bucket correctly failed closed: %v", err)
}
