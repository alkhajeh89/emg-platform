//go:build realcloud_iam

// Real-cloud IAM/administrative-boundary qualification (ADR-045 Wave 2
// Track C, Phase 9). Gated behind the realcloud_iam build tag so it never
// runs as part of `go test ./...`, CI, or any other normal invocation --
// it impersonates real, narrowly-scoped, disposable qualification service
// accounts (never a runtime credential) against real Cloud KMS and real
// GCS, proving the actual allow/deny behavior the S4 IAM manifest
// (internal/authority/iam/manifest.json) declares.
//
// Placed in package kmsverifier_test (external) specifically so it can
// import kmssigner, keypinning, compromiseledger, and kmsverifier together
// without any import-cycle concern.
//
// Impersonation here is TEST/QUALIFICATION INFRASTRUCTURE ONLY: the human
// operator's own account is granted roles/iam.serviceAccountTokenCreator
// on each disposable qualification service account purely so this test
// harness can obtain a short-lived access token scoped to that SA's own
// narrow permissions -- this is not, and must never be represented as, a
// runtime credential-acquisition pattern for any production principal.
package kmsverifier_test

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	iampb "cloud.google.com/go/iam/apiv1/iampb"
	kms "cloud.google.com/go/kms/apiv1"
	"cloud.google.com/go/kms/apiv1/kmspb"
	"cloud.google.com/go/storage"
	"golang.org/x/oauth2"
	"google.golang.org/api/option"
	"google.golang.org/protobuf/types/known/fieldmaskpb"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/compromiseledger"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/kmssigner"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

func impersonatedToken(t *testing.T, serviceAccount string) string {
	t.Helper()
	out, err := exec.Command("gcloud", "auth", "print-access-token", "--impersonate-service-account="+serviceAccount).Output()
	if err != nil {
		t.Fatalf("gcloud auth print-access-token --impersonate-service-account=%s: %v", serviceAccount, err)
	}
	token := strings.TrimSpace(string(out))
	if token == "" {
		t.Fatal("empty impersonated token")
	}
	return token
}

func tokenOption(token string) option.ClientOption {
	return option.WithTokenSource(oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token}))
}

func iamEnv(t *testing.T) (keyVersion, cryptoKey, pinBucket, ledgerBucket string) {
	t.Helper()
	keyVersion = os.Getenv("EMG_REALCLOUD_KMS_KEY_VERSION")
	cryptoKey = os.Getenv("EMG_REALCLOUD_KMS_CRYPTO_KEY")
	pinBucket = os.Getenv("EMG_REALCLOUD_PIN_BUCKET")
	ledgerBucket = os.Getenv("EMG_REALCLOUD_LEDGER_BUCKET")
	if keyVersion == "" || cryptoKey == "" || pinBucket == "" || ledgerBucket == "" {
		t.Skip("EMG_REALCLOUD_KMS_KEY_VERSION / EMG_REALCLOUD_KMS_CRYPTO_KEY / EMG_REALCLOUD_PIN_BUCKET / EMG_REALCLOUD_LEDGER_BUCKET not all set -- skipping real-cloud IAM qualification")
	}
	return
}

// realCloudIAMEnvSA reads the four qualification service account emails
// from environment variables, set by the operator running this suite --
// these are disposable, session-specific identities with no stable
// long-term name.
func realCloudIAMEnvSA(t *testing.T) (signer, pinCapture, ledgerWriter, verifier string) {
	t.Helper()
	signer = os.Getenv("EMG_REALCLOUD_IAM_SIGNER_SA")
	pinCapture = os.Getenv("EMG_REALCLOUD_IAM_PINCAPTURE_SA")
	ledgerWriter = os.Getenv("EMG_REALCLOUD_IAM_LEDGERWRITER_SA")
	verifier = os.Getenv("EMG_REALCLOUD_IAM_VERIFIER_SA")
	if signer == "" || pinCapture == "" || ledgerWriter == "" || verifier == "" {
		t.Skip("EMG_REALCLOUD_IAM_*_SA env vars not all set -- skipping real-cloud IAM qualification")
	}
	return
}

func iamDigest(fill byte) protocol.Digest32 {
	raw := make([]byte, 32)
	for i := range raw {
		raw[i] = fill
	}
	digest, _ := protocol.NewDigest32(raw)
	return digest
}

// gcsLedgerKeyForSubject mirrors compromiseledger's own unexported
// gcsLedgerKey derivation exactly (sha256(subject), base64 URL-safe,
// "distrust/" prefix, ".json" suffix) -- duplicated here rather than
// exported from that package, since this is test-only, one-directional
// tooling (computing the key an already-declared subject was stored
// under, to attempt an unauthorized delete against it), not a second
// production call site.
func gcsLedgerKeyForSubject(subject string) string {
	sum := sha256.Sum256([]byte(subject))
	return "distrust/" + base64.RawURLEncoding.EncodeToString(sum[:]) + ".json"
}

// TestRealCloudSignerIAMBoundary: SIGNER principal (roles/cloudkms.signer
// on the CryptoKey only). Proves: sign allowed; GetPublicKey, key
// administration, pin-store write, ledger write, and IAM mutation all
// denied.
func TestRealCloudSignerIAMBoundary(t *testing.T) {
	keyVersion, cryptoKey, pinBucket, ledgerBucket := iamEnv(t)
	signerSA, _, _, _ := realCloudIAMEnvSA(t)
	ctx := context.Background()
	token := impersonatedToken(t, signerSA)

	kmsClient, err := kms.NewKeyManagementClient(ctx, tokenOption(token))
	if err != nil {
		t.Fatalf("kms.NewKeyManagementClient: %v", err)
	}
	defer kmsClient.Close()

	signer, err := kmssigner.New(kmsClient, keyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := signer.SignCommittedDigest(ctx, iamDigest(0x11)); err != nil {
		t.Fatalf("SIGNER: AsymmetricSign must succeed, got: %v", err)
	}

	if _, err := kmsClient.GetPublicKey(ctx, &kmspb.GetPublicKeyRequest{Name: keyVersion}); err == nil {
		t.Fatal("SIGNER: GetPublicKey must be denied")
	} else {
		t.Logf("SIGNER: GetPublicKey correctly denied: %v", err)
	}

	if _, err := kmsClient.UpdateCryptoKeyVersion(ctx, &kmspb.UpdateCryptoKeyVersionRequest{
		CryptoKeyVersion: &kmspb.CryptoKeyVersion{Name: keyVersion, State: kmspb.CryptoKeyVersion_DISABLED},
		UpdateMask:       &fieldmaskpb.FieldMask{Paths: []string{"state"}},
	}); err == nil {
		t.Fatal("SIGNER: key administration (UpdateCryptoKeyVersion) must be denied")
	} else {
		t.Logf("SIGNER: key administration correctly denied: %v", err)
	}

	gcsClient, err := gcswitness.NewClient(ctx, tokenOption(token))
	if err != nil {
		t.Fatalf("gcswitness.NewClient: %v", err)
	}
	defer gcsClient.Close()
	pinWitness := gcswitness.New(gcsClient, pinBucket)
	if outcome, err := pinWitness.CreateExactIfAbsent(ctx, "iam-qual/signer-write-attempt.json", []byte("x")); err == nil {
		t.Fatalf("SIGNER: pin-store write must be denied, got outcome=%v err=nil", outcome)
	} else {
		t.Logf("SIGNER: pin-store write correctly denied: %v", err)
	}
	ledgerWitness := gcswitness.New(gcsClient, ledgerBucket)
	if outcome, err := ledgerWitness.CreateExactIfAbsent(ctx, "iam-qual/signer-write-attempt.json", []byte("x")); err == nil {
		t.Fatalf("SIGNER: ledger write must be denied, got outcome=%v err=nil", outcome)
	} else {
		t.Logf("SIGNER: ledger write correctly denied: %v", err)
	}

	if _, err := kmsClient.SetIamPolicy(ctx, &iampb.SetIamPolicyRequest{
		Resource: cryptoKey,
		Policy: &iampb.Policy{
			Bindings: []*iampb.Binding{{Role: "roles/cloudkms.admin", Members: []string{"user:nobody-qualification-probe@example.com"}}},
		},
	}); err == nil {
		t.Fatal("SIGNER: SetIamPolicy on the CryptoKey must be denied")
	} else {
		t.Logf("SIGNER: IAM mutation correctly denied: %v", err)
	}

	t.Log("EVIDENCE: SIGNER principal -- sign allowed; GetPublicKey, key admin, pin write, ledger write, IAM mutation all denied")
}

// TestRealCloudPinCaptureIAMBoundary: PIN-CAPTURE principal
// (roles/cloudkms.viewer + roles/cloudkms.publicKeyViewer on the
// CryptoKey; roles/storage.objectCreator on the pin bucket only). Proves:
// GetPublicKey/capture allowed; signing denied; pin create allowed;
// delete/bucket-IAM-read denied; ledger write denied (no cross-project
// binding).
func TestRealCloudPinCaptureIAMBoundary(t *testing.T) {
	keyVersion, cryptoKey, pinBucket, ledgerBucket := iamEnv(t)
	_, pinCaptureSA, _, _ := realCloudIAMEnvSA(t)
	ctx := context.Background()
	token := impersonatedToken(t, pinCaptureSA)

	kmsClient, err := kms.NewKeyManagementClient(ctx, tokenOption(token))
	if err != nil {
		t.Fatal(err)
	}
	defer kmsClient.Close()

	lineage, err := keypinning.CryptoKeyLineage(cryptoKey)
	if err != nil {
		t.Fatal(err)
	}
	pin, err := keypinning.CaptureFromKMS(ctx, kmsClient, keyVersion, lineage, "realcloud-iam-qualification")
	if err != nil {
		t.Fatalf("PIN_CAPTURE: CaptureFromKMS (GetCryptoKeyVersion + GetPublicKey) must succeed, got: %v", err)
	}

	if _, err := kmsClient.AsymmetricSign(ctx, &kmspb.AsymmetricSignRequest{
		Name:   keyVersion,
		Digest: &kmspb.Digest{Digest: &kmspb.Digest_Sha256{Sha256: iamDigest(0x22).Bytes()}},
	}); err == nil {
		t.Fatal("PIN_CAPTURE: AsymmetricSign must be denied")
	} else {
		t.Logf("PIN_CAPTURE: signing correctly denied: %v", err)
	}

	gcsClient, err := gcswitness.NewClient(ctx, tokenOption(token))
	if err != nil {
		t.Fatal(err)
	}
	defer gcsClient.Close()
	pinWitness := gcswitness.New(gcsClient, pinBucket)
	store, err := keypinning.NewGCSStore(pinWitness)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Pin(ctx, pin); err != nil {
		t.Fatalf("PIN_CAPTURE: Pin create must succeed, got: %v", err)
	}

	// Delete/bucket-IAM-read denied -- via the raw storage client (never
	// through gcswitness.Adapter, which structurally cannot call these).
	rawClient, err := storage.NewClient(ctx, tokenOption(token))
	if err != nil {
		t.Fatal(err)
	}
	defer rawClient.Close()
	probeKey := "iam-qual/pincapture-delete-attempt-" + time.Now().UTC().Format("150405") + ".json"
	if _, err := pinWitness.CreateExactIfAbsent(ctx, probeKey, []byte("probe")); err != nil {
		t.Fatalf("test setup: create probe object: %v", err)
	}
	if err := rawClient.Bucket(pinBucket).Object(probeKey).Delete(ctx); err == nil {
		t.Fatal("PIN_CAPTURE: object delete must be denied")
	} else {
		t.Logf("PIN_CAPTURE: delete correctly denied: %v", err)
	}
	if _, err := rawClient.Bucket(pinBucket).IAM().Policy(ctx); err == nil {
		t.Fatal("PIN_CAPTURE: reading the bucket's IAM policy must be denied")
	} else {
		t.Logf("PIN_CAPTURE: bucket IAM read correctly denied: %v", err)
	}

	ledgerWitness := gcswitness.New(gcsClient, ledgerBucket)
	if outcome, err := ledgerWitness.CreateExactIfAbsent(ctx, "iam-qual/pincapture-write-attempt.json", []byte("x")); err == nil {
		t.Fatalf("PIN_CAPTURE: ledger write must be denied, got outcome=%v err=nil", outcome)
	} else {
		t.Logf("PIN_CAPTURE: ledger write correctly denied (no cross-project binding): %v", err)
	}

	t.Log("EVIDENCE: PIN_CAPTURE principal -- capture/pin-create allowed; sign, delete, bucket-IAM-read, ledger write all denied")
}

// TestRealCloudLedgerWriterIAMBoundary: LEDGER-WRITER principal
// (roles/storage.objectCreator on the ledger bucket only). Proves: ledger
// declare allowed; signing denied; pin-store write denied (no
// cross-project binding); prior-record delete denied; bucket-IAM read
// denied.
func TestRealCloudLedgerWriterIAMBoundary(t *testing.T) {
	keyVersion, _, pinBucket, ledgerBucket := iamEnv(t)
	_, _, ledgerWriterSA, _ := realCloudIAMEnvSA(t)
	ctx := context.Background()
	token := impersonatedToken(t, ledgerWriterSA)

	gcsClient, err := gcswitness.NewClient(ctx, tokenOption(token))
	if err != nil {
		t.Fatal(err)
	}
	defer gcsClient.Close()
	ledgerWitness := gcswitness.New(gcsClient, ledgerBucket)
	ledger, err := compromiseledger.NewGCSLedger(ledgerWitness)
	if err != nil {
		t.Fatal(err)
	}
	subject := "iam-qual-ledgerwriter-subject-" + time.Now().UTC().Format("20060102T150405.000000000")
	now := time.Now().UTC()
	if err := ledger.Declare(ctx, compromiseledger.DistrustRecord{
		Subject: subject, EffectiveTime: now, RecordedAt: now,
		Reason: "iam qualification", RecordedBy: "realcloud-iam-qualification",
	}); err != nil {
		t.Fatalf("LEDGER_WRITER: Declare must succeed, got: %v", err)
	}

	kmsClient, err := kms.NewKeyManagementClient(ctx, tokenOption(token))
	if err != nil {
		t.Fatal(err)
	}
	defer kmsClient.Close()
	if _, err := kmsClient.AsymmetricSign(ctx, &kmspb.AsymmetricSignRequest{
		Name:   keyVersion,
		Digest: &kmspb.Digest{Digest: &kmspb.Digest_Sha256{Sha256: iamDigest(0x33).Bytes()}},
	}); err == nil {
		t.Fatal("LEDGER_WRITER: AsymmetricSign must be denied")
	} else {
		t.Logf("LEDGER_WRITER: signing correctly denied: %v", err)
	}

	pinWitness := gcswitness.New(gcsClient, pinBucket)
	if outcome, err := pinWitness.CreateExactIfAbsent(ctx, "iam-qual/ledgerwriter-write-attempt.json", []byte("x")); err == nil {
		t.Fatalf("LEDGER_WRITER: pin-store write must be denied, got outcome=%v err=nil", outcome)
	} else {
		t.Logf("LEDGER_WRITER: pin-store write correctly denied (no cross-project binding): %v", err)
	}

	rawClient, err := storage.NewClient(ctx, tokenOption(token))
	if err != nil {
		t.Fatal(err)
	}
	defer rawClient.Close()
	distrustKey := gcsLedgerKeyForSubject(subject)
	if err := rawClient.Bucket(ledgerBucket).Object(distrustKey).Delete(ctx); err == nil {
		t.Fatal("LEDGER_WRITER: prior-record delete must be denied")
	} else {
		t.Logf("LEDGER_WRITER: prior-record delete correctly denied: %v", err)
	}
	if _, err := rawClient.Bucket(ledgerBucket).IAM().Policy(ctx); err == nil {
		t.Fatal("LEDGER_WRITER: reading the bucket's IAM policy must be denied")
	} else {
		t.Logf("LEDGER_WRITER: bucket IAM read correctly denied: %v", err)
	}

	t.Log("EVIDENCE: LEDGER_WRITER principal -- declare allowed; sign, pin write, prior-record delete, bucket-IAM-read all denied")
}

// TestRealCloudVerifierIAMBoundary: VERIFIER principal
// (roles/storage.objectViewer on BOTH the pin and ledger buckets, nothing
// else). Proves: required reads succeed; all writes and signing denied.
func TestRealCloudVerifierIAMBoundary(t *testing.T) {
	keyVersion, _, pinBucket, ledgerBucket := iamEnv(t)
	_, _, _, verifierSA := realCloudIAMEnvSA(t)
	ctx := context.Background()
	token := impersonatedToken(t, verifierSA)

	gcsClient, err := gcswitness.NewClient(ctx, tokenOption(token))
	if err != nil {
		t.Fatal(err)
	}
	defer gcsClient.Close()
	pinWitness := gcswitness.New(gcsClient, pinBucket)
	ledgerWitness := gcswitness.New(gcsClient, ledgerBucket)

	// Required reads succeed: Exists is sufficient to prove read access
	// without depending on another test's specific object key or run order.
	if _, err := pinWitness.Exists(ctx, "iam-qual/verifier-read-probe.json"); err != nil {
		t.Fatalf("VERIFIER: Exists (read) on the pin bucket must succeed, got: %v", err)
	}
	if _, err := ledgerWitness.Exists(ctx, "iam-qual/verifier-read-probe.json"); err != nil {
		t.Fatalf("VERIFIER: Exists (read) on the ledger bucket must succeed, got: %v", err)
	}

	if outcome, err := pinWitness.CreateExactIfAbsent(ctx, "iam-qual/verifier-write-attempt.json", []byte("x")); err == nil {
		t.Fatalf("VERIFIER: pin-store write must be denied, got outcome=%v err=nil", outcome)
	} else {
		t.Logf("VERIFIER: pin-store write correctly denied: %v", err)
	}
	if outcome, err := ledgerWitness.CreateExactIfAbsent(ctx, "iam-qual/verifier-write-attempt.json", []byte("x")); err == nil {
		t.Fatalf("VERIFIER: ledger write must be denied, got outcome=%v err=nil", outcome)
	} else {
		t.Logf("VERIFIER: ledger write correctly denied: %v", err)
	}

	kmsClient, err := kms.NewKeyManagementClient(ctx, tokenOption(token))
	if err != nil {
		t.Fatal(err)
	}
	defer kmsClient.Close()
	if _, err := kmsClient.AsymmetricSign(ctx, &kmspb.AsymmetricSignRequest{
		Name:   keyVersion,
		Digest: &kmspb.Digest{Digest: &kmspb.Digest_Sha256{Sha256: iamDigest(0x44).Bytes()}},
	}); err == nil {
		t.Fatal("VERIFIER: AsymmetricSign must be denied")
	} else {
		t.Logf("VERIFIER: signing correctly denied: %v", err)
	}

	t.Log("EVIDENCE: VERIFIER principal -- required reads (Exists) allowed on both buckets; all writes and signing denied")
}
