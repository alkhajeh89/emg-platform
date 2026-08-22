//go:build realcloud_pin

// Real-cloud public-key pinning qualification (ADR-045 §7C Wave 2 Track C,
// Phase 6). Gated behind the realcloud_pin build tag so it never runs as
// part of `go test ./...`, CI, or any other normal invocation -- it calls
// real Cloud KMS (GetCryptoKeyVersion/GetPublicKey, read-only) and writes
// real objects to a real, disposable GCS bucket in the signing-domain
// qualification project, with credentials/resource identifiers supplied
// entirely through environment variables.
//
// SCOPE: qualifies the real, unmodified production keypinning.CaptureFromKMS
// and keypinning.GCSStore against genuine Cloud KMS and genuine GCS. The
// GCS bucket used here lives in the SAME disposable project as the signing
// key (emg-ra-signing-qual-*), matching the approved placement-governance
// decision that the pin store belongs in the signing administrative domain,
// not the authority/witness domain -- see
// docs/runbooks/RECOVERY_AUTHORITY_PLACEMENT_AND_BILLING_GOVERNANCE_DECISION.md
// §9. This is disposable qualification only; it does not itself prove
// ADR-045 production administrative independence (that requires a
// genuinely separate Cloud Identity/Workspace domain, not yet realized).
package keypinning

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

	kms "cloud.google.com/go/kms/apiv1"
	"golang.org/x/oauth2"
	"google.golang.org/api/option"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

func realCloudPinToken(t *testing.T) string {
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

func realCloudPinEnv(t *testing.T) (keyVersion, cryptoKey, bucket string) {
	t.Helper()
	keyVersion = os.Getenv("EMG_REALCLOUD_KMS_KEY_VERSION")
	cryptoKey = os.Getenv("EMG_REALCLOUD_KMS_CRYPTO_KEY")
	bucket = os.Getenv("EMG_REALCLOUD_PIN_BUCKET")
	if keyVersion == "" || cryptoKey == "" || bucket == "" {
		t.Skip("EMG_REALCLOUD_KMS_KEY_VERSION / EMG_REALCLOUD_KMS_CRYPTO_KEY / EMG_REALCLOUD_PIN_BUCKET not all set -- skipping real-cloud pin-store qualification")
	}
	return keyVersion, cryptoKey, bucket
}

func generateForeignPEM(t *testing.T) string {
	t.Helper()
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	der, err := x509.MarshalPKIXPublicKey(&priv.PublicKey)
	if err != nil {
		t.Fatal(err)
	}
	return string(pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der}))
}

func fingerprintOf(publicKeyPEM string) [32]byte {
	return sha256.Sum256([]byte(publicKeyPEM))
}

// TestRealCloudPublicKeyPinningQualification exercises Phase 6 / ADR-045
// §7C's S3 qualification checklist items 1-3 and 6-8 against real Cloud KMS
// and real GCS: the pinned public key can be retrieved while ENABLED, is
// durably pinned indexed by SigningKeyID, independently round-trip-verifies
// (item 3 is exercised together with kmssigner's own real signature in
// Phase 5 -- this test proves the pin itself is correct and durable, not
// signature verification a second time), and integrity/conflict/no-overwrite
// properties hold against the real provider.
func TestRealCloudPublicKeyPinningQualification(t *testing.T) {
	keyVersion, cryptoKey, bucket := realCloudPinEnv(t)
	ctx := context.Background()
	token := realCloudPinToken(t)

	kmsClient, err := kms.NewKeyManagementClient(ctx, option.WithTokenSource(oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})))
	if err != nil {
		t.Fatalf("kms.NewKeyManagementClient: %v", err)
	}
	t.Cleanup(func() { kmsClient.Close() })

	gcsClient, err := gcswitness.NewClient(ctx, option.WithTokenSource(oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})))
	if err != nil {
		t.Fatalf("gcswitness.NewClient: %v", err)
	}
	t.Cleanup(func() { gcsClient.Close() })

	witness := gcswitness.New(gcsClient, bucket)
	store, err := NewGCSStore(witness)
	if err != nil {
		t.Fatal(err)
	}

	lineage, err := CryptoKeyLineage(cryptoKey)
	if err != nil {
		t.Fatalf("CryptoKeyLineage: %v", err)
	}
	keyID, err := protocol.NewSigningKeyID(keyVersion)
	if err != nil {
		t.Fatal(err)
	}

	// Item 1/2 (§7C): retrieve the public key while ENABLED, via the real,
	// unmodified production CaptureFromKMS path, and durably pin it.
	pin, err := CaptureFromKMS(ctx, kmsClient, keyVersion, lineage, "realcloud-pin-qualification")
	if err != nil {
		t.Fatalf("CaptureFromKMS: %v", err)
	}
	if pin.SigningKeyID != keyID {
		t.Fatalf("captured pin SigningKeyID = %q, want %q", pin.SigningKeyID.String(), keyID.String())
	}
	if pin.PublicKeyPEM == "" {
		t.Fatal("captured pin has empty PublicKeyPEM")
	}

	if err := store.Pin(ctx, pin); err != nil {
		t.Fatalf("GCSStore.Pin (real GCS): %v", err)
	}

	// Read-back verifies identical material; fingerprint independently
	// recomputed by GCSStore.Get itself (decodePinRecord), not trusted from
	// storage.
	got, err := store.Get(ctx, keyID)
	if err != nil {
		t.Fatalf("GCSStore.Get (real GCS): %v", err)
	}
	if got.PublicKeyPEM != pin.PublicKeyPEM {
		t.Fatal("read-back public key material does not match captured material")
	}
	if got.Fingerprint != pin.Fingerprint {
		t.Fatal("read-back fingerprint does not match captured fingerprint")
	}

	// Identical duplicate pin is idempotent (real create-if-absent
	// AlreadyExistsIdentical path, exercised through GCSStore.Pin's own
	// fingerprint-comparison branch).
	if err := store.Pin(ctx, pin); err != nil {
		t.Fatalf("duplicate GCSStore.Pin (real GCS): %v", err)
	}

	// Conflicting duplicate (different public key material under the SAME
	// SigningKeyID) must fail closed -- never silently replace the pinned
	// material (Attack 22, ADR-045 §13).
	foreignPEM := generateForeignPEM(t)
	conflicting := pin
	conflicting.PublicKeyPEM = foreignPEM
	conflicting.Fingerprint = fingerprintOf(foreignPEM)
	conflictErr := store.Pin(ctx, conflicting)
	if conflictErr == nil {
		t.Fatal("expected a conflicting pin under the same SigningKeyID to fail closed")
	}
	if !errors.Is(conflictErr, ErrPinConflict) {
		t.Fatalf("expected ErrPinConflict, got: %v", conflictErr)
	}

	// No overwrite: read back again, confirm the ORIGINAL material still
	// governs -- the conflicting attempt above must never have replaced it.
	afterConflict, err := store.Get(ctx, keyID)
	if err != nil {
		t.Fatalf("GCSStore.Get (post-conflict, real GCS): %v", err)
	}
	if afterConflict.PublicKeyPEM != pin.PublicKeyPEM {
		t.Fatal("pinned material changed after a rejected conflicting Pin attempt -- overwrite occurred")
	}

	t.Logf("EVIDENCE: SigningKeyID=%q pinned, idempotent duplicate accepted, conflicting duplicate rejected (ErrPinConflict), no overwrite occurred, read-back fingerprint matches", keyID.String())
}

// TestRealCloudPinBucketAvailabilityDistinction is the Phase 9 (P0
// remediation) real-cloud regression test: proves, against real GCS, that
// GCSStore.Get correctly distinguishes "existing bucket, key never pinned"
// (ordinary ErrPinNotFound) from "the pin-store bucket itself does not
// exist" (a provider/storage error, never ErrPinNotFound) -- items 3 and 4
// of the Phase 9 real-cloud regression plan.
func TestRealCloudPinBucketAvailabilityDistinction(t *testing.T) {
	_, _, bucket := realCloudPinEnv(t)
	ctx := context.Background()
	token := realCloudPinToken(t)

	newStore := func(t *testing.T, bucketName string) *GCSStore {
		t.Helper()
		client, err := gcswitness.NewClient(ctx, option.WithTokenSource(oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})))
		if err != nil {
			t.Fatalf("gcswitness.NewClient: %v", err)
		}
		t.Cleanup(func() { client.Close() })
		store, err := NewGCSStore(gcswitness.New(client, bucketName))
		if err != nil {
			t.Fatal(err)
		}
		return store
	}

	neverPinnedKeyID, err := protocol.NewSigningKeyID("projects/p/locations/l/keyRings/r/cryptoKeys/never-pinned/cryptoKeyVersions/1")
	if err != nil {
		t.Fatal(err)
	}

	// Item 3: existing bucket + missing key -> ordinary ErrPinNotFound.
	existingStore := newStore(t, bucket)
	if _, err := existingStore.Get(ctx, neverPinnedKeyID); !errors.Is(err, ErrPinNotFound) {
		t.Fatalf("expected ErrPinNotFound for a never-pinned key in the real, existing pin bucket, got: %v", err)
	}

	// Item 4: nonexistent bucket -> non-nil provider error, NEVER
	// ErrPinNotFound -- the exact P0 fail-open condition this remediation
	// closes (a misconfigured/deleted pin-store bucket must never be
	// silently treated as "this key was simply never pinned").
	brokenStore := newStore(t, bucket+"-does-not-exist-for-pin-availability-test")
	_, err = brokenStore.Get(ctx, neverPinnedKeyID)
	if err == nil {
		t.Fatal("expected a non-nil error against a nonexistent pin bucket")
	}
	if errors.Is(err, ErrPinNotFound) {
		t.Fatalf("a nonexistent bucket must NEVER be classified as ErrPinNotFound, got: %v", err)
	}
	t.Logf("EVIDENCE: real GCS correctly distinguishes missing-key (ErrPinNotFound) from missing-bucket (%v)", err)
}
