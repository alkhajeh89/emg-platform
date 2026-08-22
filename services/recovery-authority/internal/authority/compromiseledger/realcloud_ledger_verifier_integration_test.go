//go:build realcloud_ledger

// Real-cloud full-pipeline verification integration (ADR-045 §7A Wave 2
// Track C, Phase 8, items 10-11). External test package
// (compromiseledger_test) deliberately, to avoid an import cycle:
// kmsverifier imports compromiseledger, so a test needing both types
// cannot live inside the internal compromiseledger package. Gated behind
// the realcloud_ledger build tag; never runs as part of `go test ./...` or
// CI.
package compromiseledger_test

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	kms "cloud.google.com/go/kms/apiv1"
	"golang.org/x/oauth2"
	"google.golang.org/api/option"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/compromiseledger"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/kmssigner"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/kmsverifier"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

func realCloudToken(t *testing.T) string {
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

func realWitness(t *testing.T, bucket, token string) gcswitness.ImmutableWitness {
	t.Helper()
	client, err := gcswitness.NewClient(context.Background(), option.WithTokenSource(oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})))
	if err != nil {
		t.Fatalf("gcswitness.NewClient: %v", err)
	}
	t.Cleanup(func() { client.Close() })
	return gcswitness.New(client, bucket)
}

func integrationDigest(fill byte) protocol.Digest32 {
	raw := make([]byte, 32)
	for i := range raw {
		raw[i] = fill
	}
	digest, _ := protocol.NewDigest32(raw)
	return digest
}

// TestRealCloudCompromiseLedgerVerifierIntegration exercises items 10-11:
// the FULL real ADR-045 §7A verification pipeline (real Cloud KMS signature
// + real pinned public key + real compromise ledger + kmsverifier), proving
// a genuinely valid signature is rejected/routed to manual review at-or-after
// a declared distrust-effective-time, and remains verifiable strictly
// before it. Also directly demonstrates items 12-13 by construction: this
// test never calls Declare from anything resembling a signing capability,
// and the Verifier constructed here is never given any signing capability
// either (kmsverifier.Verifier has no such dependency at all -- see
// kmsverifier's own boundary_test.go, unmodified by this task).
func TestRealCloudCompromiseLedgerVerifierIntegration(t *testing.T) {
	keyVersion := os.Getenv("EMG_REALCLOUD_KMS_KEY_VERSION")
	cryptoKey := os.Getenv("EMG_REALCLOUD_KMS_CRYPTO_KEY")
	pinBucket := os.Getenv("EMG_REALCLOUD_PIN_BUCKET")
	ledgerBucket := os.Getenv("EMG_REALCLOUD_LEDGER_BUCKET")
	if keyVersion == "" || cryptoKey == "" || pinBucket == "" || ledgerBucket == "" {
		t.Skip("EMG_REALCLOUD_KMS_KEY_VERSION / EMG_REALCLOUD_KMS_CRYPTO_KEY / EMG_REALCLOUD_PIN_BUCKET / EMG_REALCLOUD_LEDGER_BUCKET not all set -- skipping full-pipeline integration")
	}
	ctx := context.Background()
	token := realCloudToken(t)

	kmsClient, err := kms.NewKeyManagementClient(ctx, option.WithTokenSource(oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})))
	if err != nil {
		t.Fatalf("kms.NewKeyManagementClient: %v", err)
	}
	t.Cleanup(func() { kmsClient.Close() })

	pinWitness := realWitness(t, pinBucket, token)
	pinStore, err := keypinning.NewGCSStore(pinWitness)
	if err != nil {
		t.Fatal(err)
	}
	lineage, err := keypinning.CryptoKeyLineage(cryptoKey)
	if err != nil {
		t.Fatal(err)
	}
	keyID, err := protocol.NewSigningKeyID(keyVersion)
	if err != nil {
		t.Fatal(err)
	}
	pin, err := keypinning.CaptureFromKMS(ctx, kmsClient, keyVersion, lineage, "realcloud-ledger-verifier-integration")
	if err != nil {
		t.Fatalf("CaptureFromKMS: %v", err)
	}
	if err := pinStore.Pin(ctx, pin); err != nil {
		t.Fatalf("pinStore.Pin: %v", err)
	}

	ledgerWitness := realWitness(t, ledgerBucket, token)
	ledger, err := compromiseledger.NewGCSLedger(ledgerWitness)
	if err != nil {
		t.Fatal(err)
	}

	verifier, err := kmsverifier.New(pinStore, ledger)
	if err != nil {
		t.Fatal(err)
	}

	signer, err := kmssigner.New(kmsClient, keyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	digest := integrationDigest(0x5a)
	signature, confirmedKeyID, err := signer.SignCommittedDigest(ctx, digest)
	if err != nil {
		t.Fatalf("SignCommittedDigest (real KMS): %v", err)
	}
	if confirmedKeyID != keyID {
		t.Fatalf("confirmedKeyID = %q, want %q", confirmedKeyID.String(), keyID.String())
	}

	now := time.Now().UTC()
	distrustSubject := compromiseledger.SigningKeyIDSubject(keyID)
	if err := ledger.Declare(ctx, compromiseledger.DistrustRecord{
		Subject:       distrustSubject,
		EffectiveTime: now,
		RecordedAt:    now,
		Reason:        "realcloud-ledger-verifier-integration",
		RecordedBy:    "realcloud-qualification-harness",
	}); err != nil {
		t.Fatalf("Declare distrust: %v", err)
	}

	// Item 11: historical signature strictly BEFORE the distrust-effective
	// time remains verifiable via the real pipeline.
	before := now.Add(-time.Minute)
	if err := verifier.VerifyCommittedSignature(ctx, keyID, before, digest, signature); err != nil {
		t.Fatalf("expected a genuinely valid signature timestamped before distrust-effective-time to verify, got: %v", err)
	}

	// Item 10: the SAME cryptographically valid signature, timestamped AT
	// distrust-effective-time or after, must be rejected/routed to manual
	// review -- never auto-accepted merely because the cryptography is
	// genuinely valid.
	atOrAfter := now
	err = verifier.VerifyCommittedSignature(ctx, keyID, atOrAfter, digest, signature)
	if !errors.Is(err, kmsverifier.ErrRequiresManualReview) {
		t.Fatalf("expected ErrRequiresManualReview for a record at/after distrust-effective-time, got: %v", err)
	}

	t.Logf("EVIDENCE: full real pipeline (KMS sign -> pin -> ledger -> kmsverifier) -- pre-distrust signature verifies (item 11), post-distrust identical signature routed to manual review (item 10)")

	// P0 regression, Phase 9 item 7: the SAME genuinely valid signature,
	// timestamped strictly BEFORE the distrust-effective-time (i.e. would
	// otherwise legitimately verify per item 11 above), must NOT verify
	// successfully when the compromise-ledger's bucket is unavailable --
	// missing/unreachable governance-container state must never be
	// silently treated as "not distrusted" anywhere in the real,
	// end-to-end verification pipeline, not just in Status considered in
	// isolation (already proven by TestRealCloudCompromiseLedgerQualification
	// item 9).
	brokenLedgerWitness := realWitness(t, ledgerBucket+"-does-not-exist-for-verifier-integration", token)
	brokenLedger, err := compromiseledger.NewGCSLedger(brokenLedgerWitness)
	if err != nil {
		t.Fatal(err)
	}
	brokenVerifier, err := kmsverifier.New(pinStore, brokenLedger)
	if err != nil {
		t.Fatal(err)
	}
	if err := brokenVerifier.VerifyCommittedSignature(ctx, keyID, before, digest, signature); err == nil {
		t.Fatal("expected VerifyCommittedSignature to fail when the compromise ledger's bucket is unavailable -- got nil error (silent verification success), the exact P0 fail-open condition this remediation closes")
	} else if !errors.Is(err, kmsverifier.ErrCompromiseLedgerUnavailable) {
		t.Fatalf("expected ErrCompromiseLedgerUnavailable, got: %v", err)
	} else {
		t.Logf("EVIDENCE: item 7 -- full real pipeline correctly failed closed (ErrCompromiseLedgerUnavailable) when the ledger bucket was unavailable, even for a signature that would otherwise legitimately verify: %v", err)
	}
}
