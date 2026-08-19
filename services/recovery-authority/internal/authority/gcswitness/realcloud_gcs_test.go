//go:build realcloud_gcs

// Real-cloud GCS witness qualification (ADR-044 §17 item 7 / S7
// pre-qualification, Wave 1 Track B). Gated behind the realcloud_gcs build
// tag so it can never run as part of `go test ./...`, CI, or any other
// normal invocation -- it writes real objects to a real, disposable GCS
// bucket and requires credentials supplied entirely through environment
// variables.
//
// SCOPE: qualifies the real production gcswitness.Adapter (create-if-absent
// / ReadExact / Exists) and, composed directly over the same real Adapter,
// keypinning.GCSStore and compromiseledger.GCSLedger -- unmodified
// production code, exercising the exact code path bootstrap.ExecuteGenesis
// and CheckSigningPreconditions use, minus KMS (a local key pair stands in
// for a real pinned signing key, exactly as Track A's fakeGenesisSigner
// stands in for real KMS signing -- both are explicitly out of scope for
// this wave). Bucket Lock retention lifecycle (set/verify-enforced/lock/
// verify-irreversible) is driven directly via `gcloud storage` from the
// calling shell, not from this test, because gcswitness deliberately
// exposes no Delete/Update/Retention capability at all -- there is no
// production code path to exercise for those operations, only ground-truth
// enforcement to observe.
package gcswitness_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"cloud.google.com/go/storage"
	"golang.org/x/oauth2"
	"google.golang.org/api/option"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/compromiseledger"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

func realCloudGCSToken(t *testing.T) string {
	t.Helper()
	out, err := exec.Command("gcloud", "auth", "print-access-token").Output()
	if err != nil {
		t.Fatalf("gcloud auth print-access-token: %v", err)
	}
	token := strings.TrimSpace(string(out))
	if token == "" {
		t.Fatal("gcloud auth print-access-token returned an empty token")
	}
	return token
}

func realCloudGCSBucket(t *testing.T) string {
	t.Helper()
	bucket := os.Getenv("EMG_REALCLOUD_GCS_BUCKET")
	if bucket == "" {
		t.Skip("EMG_REALCLOUD_GCS_BUCKET not set -- skipping real-cloud GCS witness qualification")
	}
	return bucket
}

func realCloudAdapter(t *testing.T) *gcswitness.Adapter {
	t.Helper()
	bucket := realCloudGCSBucket(t)
	token := realCloudGCSToken(t)
	tokenSource := oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})
	client, err := gcswitness.NewClient(context.Background(), option.WithTokenSource(tokenSource))
	if err != nil {
		t.Fatalf("gcswitness.NewClient (real GCS): %v", err)
	}
	t.Cleanup(func() { client.Close() })
	return gcswitness.New(client, bucket)
}

func freshRealKey(t *testing.T, prefix string) string {
	t.Helper()
	id, err := protocol_NewOperationIDLike()
	if err != nil {
		t.Fatal(err)
	}
	return prefix + "/" + id + ".json"
}

// protocol_NewOperationIDLike mints a fresh, sufficiently-unique suffix for
// object keys without importing google/uuid directly into this file --
// reuses the already-qualified crypto/rand-backed randomness this test file
// already imports transitively via ecdsa key generation, keeping the
// dependency list minimal.
func protocol_NewOperationIDLike() (string, error) {
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(priv.D.Bytes())
	return time.Now().UTC().Format("20060102T150405.000000000") + "-" + hexEncode(sum[:8]), nil
}

func hexEncode(b []byte) string {
	const hextable = "0123456789abcdef"
	out := make([]byte, len(b)*2)
	for i, v := range b {
		out[i*2] = hextable[v>>4]
		out[i*2+1] = hextable[v&0x0f]
	}
	return string(out)
}

// TestRealCloudGCSWitnessQualification exercises B3 items 1-7 against the
// real bucket via the unmodified production gcswitness.Adapter.
func TestRealCloudGCSWitnessQualification(t *testing.T) {
	adapter := realCloudAdapter(t)
	ctx := context.Background()

	key := freshRealKey(t, "realcloud-qualification")
	payload := []byte(`{"realcloud":"qualification","step":"first-create"}`)

	// Item 1: first create succeeds.
	outcome, err := adapter.CreateExactIfAbsent(ctx, key, payload)
	if err != nil {
		t.Fatalf("first create: %v", err)
	}
	if outcome != gcswitness.CreateSuccess {
		t.Fatalf("first create outcome = %v, want CreateSuccess", outcome)
	}

	// Item 2: exact duplicate is idempotent.
	dupOutcome, dupErr := adapter.CreateExactIfAbsent(ctx, key, payload)
	if dupErr != nil {
		t.Fatalf("duplicate create: %v", dupErr)
	}
	if dupOutcome != gcswitness.AlreadyExistsIdentical {
		t.Fatalf("duplicate create outcome = %v, want AlreadyExistsIdentical", dupOutcome)
	}

	// Item 3/4: conflicting bytes fail closed, never overwrite.
	conflictOutcome, conflictErr := adapter.CreateExactIfAbsent(ctx, key, []byte(`{"different":"content"}`))
	if conflictOutcome != gcswitness.AlreadyExistsConflict {
		t.Fatalf("conflicting create outcome = %v, want AlreadyExistsConflict (err=%v)", conflictOutcome, conflictErr)
	}
	if !errors.Is(conflictErr, gcswitness.ErrConflict) {
		t.Fatalf("conflicting create error = %v, want gcswitness.ErrConflict", conflictErr)
	}

	// Item 6: exact-key read succeeds and the object was never overwritten
	// by the conflicting attempt above (item 4, verified here by content).
	readBack, err := adapter.ReadExact(ctx, key)
	if err != nil {
		t.Fatalf("ReadExact: %v", err)
	}
	if string(readBack) != string(payload) {
		t.Fatalf("readBack = %q, want original payload %q -- object must never be overwritten by a conflicting create", readBack, payload)
	}

	// Item 7: Exists behaves correctly for present and absent keys.
	exists, err := adapter.Exists(ctx, key)
	if err != nil {
		t.Fatalf("Exists(present): %v", err)
	}
	if !exists {
		t.Fatal("Exists reported false for a key that was just created")
	}
	absentKey := freshRealKey(t, "realcloud-qualification-absent")
	absentExists, err := adapter.Exists(ctx, absentKey)
	if err != nil {
		t.Fatalf("Exists(absent): %v", err)
	}
	if absentExists {
		t.Fatal("Exists reported true for a key that was never created")
	}

	// Item 5 (no alternate key fallback on conflict) is a structural fact,
	// verified by source inspection of gcswitness.go's
	// CreateExactIfAbsent/classifyCreateError: both operate on exactly the
	// one `key` parameter throughout, with no second Object() call against
	// any other name -- not re-verified by a new runtime test here.

	t.Logf("EVIDENCE: key=%q generation-bearing object created, duplicate idempotent, conflict fail-closed, no overwrite, exact read/exists correct", key)
}

// TestRealCloudGCSStoreAndLedgerComposition exercises keypinning.GCSStore
// and compromiseledger.GCSLedger wired directly to the same real,
// unmodified gcswitness.Adapter -- proving the composition (not just the
// underlying primitive, already qualified above) against real GCS.
func TestRealCloudGCSStoreAndLedgerComposition(t *testing.T) {
	adapter := realCloudAdapter(t)
	ctx := context.Background()

	store, err := keypinning.NewGCSStore(adapter)
	if err != nil {
		t.Fatal(err)
	}
	ledger, err := compromiseledger.NewGCSLedger(adapter)
	if err != nil {
		t.Fatal(err)
	}

	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	der, err := x509.MarshalPKIXPublicKey(&priv.PublicKey)
	if err != nil {
		t.Fatal(err)
	}
	pemBytes := pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der})

	suffix, err := protocol_NewOperationIDLike()
	if err != nil {
		t.Fatal(err)
	}
	keyID, err := protocol.NewSigningKeyID("projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/" + strings.ReplaceAll(suffix, ".", "") + "1")
	if err != nil {
		t.Fatal(err)
	}

	pin := keypinning.PinnedKey{
		SigningKeyID: keyID,
		Algorithm:    keypinning.AlgorithmECSignP256SHA256,
		PublicKeyPEM: string(pemBytes),
		Fingerprint:  sha256.Sum256(pemBytes),
		PinnedAt:     time.Now().UTC(),
		Provenance:   "realcloud-gcs-qualification",
	}
	if err := store.Pin(ctx, pin); err != nil {
		t.Fatalf("GCSStore.Pin (real GCS): %v", err)
	}
	got, err := store.Get(ctx, keyID)
	if err != nil {
		t.Fatalf("GCSStore.Get (real GCS): %v", err)
	}
	if got.Fingerprint != pin.Fingerprint {
		t.Fatal("GCSStore.Get returned a pin whose independently recomputed fingerprint does not match")
	}
	// Duplicate Pin of the identical record must be idempotent, exactly
	// like the underlying adapter's AlreadyExistsIdentical contract.
	if err := store.Pin(ctx, pin); err != nil {
		t.Fatalf("GCSStore.Pin (duplicate, real GCS): %v", err)
	}

	subject := "realcloud-gcs-qualification-subject-" + suffix
	now := time.Now().UTC()
	record := compromiseledger.DistrustRecord{
		Subject:       subject,
		EffectiveTime: now,
		RecordedAt:    now,
		Reason:        "realcloud-gcs-qualification",
		RecordedBy:    "realcloud-qualification-harness",
	}
	if err := ledger.Declare(ctx, record); err != nil {
		t.Fatalf("GCSLedger.Declare (real GCS): %v", err)
	}
	status, err := ledger.Status(ctx, subject, now.Add(time.Second))
	if err != nil {
		t.Fatalf("GCSLedger.Status (real GCS): %v", err)
	}
	if status != compromiseledger.StatusRequiresManualReview {
		t.Fatalf("GCSLedger.Status = %v, want StatusRequiresManualReview", status)
	}

	t.Logf("EVIDENCE: keypinning.GCSStore and compromiseledger.GCSLedger both round-tripped correctly against real GCS, composed over the real gcswitness.Adapter")
}

var _ = storage.ErrObjectNotExist // referenced only to document the real SDK error this package's ReadExact/Exists translate; never constructed here.
