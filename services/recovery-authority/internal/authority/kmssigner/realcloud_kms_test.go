//go:build realcloud_kms

// Real-cloud Cloud KMS signer qualification (ADR-045 Wave 2 Track C).
// Gated behind the realcloud_kms build tag so it never runs as part of
// `go test ./...`, CI, or any other normal invocation -- it invokes real
// AsymmetricSign against a real, disposable Cloud KMS CryptoKeyVersion and
// requires credentials/resource identifiers supplied entirely through
// environment variables.
//
// SCOPE: qualifies the real, unmodified production kmssigner.Signer against
// genuine Cloud KMS. It does not touch keypinning/compromiseledger (Phase
// 6/8, separate files) and does not modify kmssigner's production code in
// any way -- every property below is proven by calling the real, exported
// Signer type exactly as production code does.
package kmssigner_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"encoding/pem"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	kms "cloud.google.com/go/kms/apiv1"
	"cloud.google.com/go/kms/apiv1/kmspb"
	"golang.org/x/oauth2"
	"google.golang.org/api/option"
	"google.golang.org/protobuf/types/known/fieldmaskpb"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/kmssigner"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

func realCloudKMSToken(t *testing.T) string {
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

func realCloudKeyVersion(t *testing.T) string {
	t.Helper()
	v := os.Getenv("EMG_REALCLOUD_KMS_KEY_VERSION")
	if v == "" {
		t.Skip("EMG_REALCLOUD_KMS_KEY_VERSION not set -- skipping real-cloud KMS signer qualification")
	}
	return v
}

func realKMSClient(t *testing.T) *kms.KeyManagementClient {
	t.Helper()
	token := realCloudKMSToken(t)
	tokenSource := oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})
	client, err := kms.NewKeyManagementClient(context.Background(), option.WithTokenSource(tokenSource))
	if err != nil {
		t.Fatalf("kms.NewKeyManagementClient: %v", err)
	}
	t.Cleanup(func() { client.Close() })
	return client
}

func realTestDigest(fill byte) protocol.Digest32 {
	raw := make([]byte, 32)
	for i := range raw {
		raw[i] = fill
	}
	digest, _ := protocol.NewDigest32(raw)
	return digest
}

// TestRealCloudKMSSignerQualification exercises the real, unmodified
// production kmssigner.Signer against a genuine Cloud KMS CryptoKeyVersion.
func TestRealCloudKMSSignerQualification(t *testing.T) {
	keyVersion := realCloudKeyVersion(t)
	client := realKMSClient(t)
	ctx := context.Background()

	signer, err := kmssigner.New(client, keyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatalf("kmssigner.New: %v", err)
	}

	// Item 1: ActiveKeyID resolves to the configured exact CryptoKeyVersion.
	activeKeyID, err := signer.ActiveKeyID(ctx)
	if err != nil {
		t.Fatalf("ActiveKeyID: %v", err)
	}
	if activeKeyID.String() != keyVersion {
		t.Fatalf("ActiveKeyID = %q, want %q", activeKeyID.String(), keyVersion)
	}

	// Items 2-4: SignCommittedDigest uses that exact version and a real
	// digest signs successfully.
	digest := realTestDigest(0x42)
	signature, confirmedKeyID, err := signer.SignCommittedDigest(ctx, digest)
	if err != nil {
		t.Fatalf("SignCommittedDigest: %v", err)
	}
	if len(signature) == 0 {
		t.Fatal("expected a non-empty real signature")
	}

	// Item 3: returned confirming key ID matches the pre-bound key ID.
	if confirmedKeyID != activeKeyID {
		t.Fatalf("confirmedKeyID = %q, want %q (pre-bound ActiveKeyID)", confirmedKeyID.String(), activeKeyID.String())
	}

	// Item 10: no private key material is ever returned or captured --
	// structural: kmssigner.Signer's exported surface has no method or
	// field capable of holding private key bytes (see signer.go: only
	// client/keyVersion/keyID/algorithm fields, all public-identifier or
	// interface-typed), and the *kmspb.AsymmetricSignResponse this test
	// receives indirectly (via SignCommittedDigest's return values) has no
	// private-key field in its wire schema at all -- confirmed by
	// independent GCP documentation review (Phase 11), not re-verified at
	// runtime here since there is no private-key field to assert absent.

	// Real public key retrieval (needed for items 5-7), via the same real
	// client, raw GetPublicKey call -- mirrors keypinning.CaptureFromKMS's
	// own call shape without importing that package here (kept minimal;
	// Phase 6's own file exercises CaptureFromKMS directly).
	pubKeyResp, err := client.GetPublicKey(ctx, &kmspb.GetPublicKeyRequest{Name: keyVersion})
	if err != nil {
		t.Fatalf("GetPublicKey: %v", err)
	}
	pub, err := keypinning.ParsePEMPublicKey([]byte(pubKeyResp.GetPem()))
	if err != nil {
		t.Fatalf("ParsePEMPublicKey: %v", err)
	}

	// Item 5: signature verifies against the corresponding public key.
	if err := keypinning.AlgorithmECSignP256SHA256.VerifyDigestSignature(pub, digest.Bytes(), signature); err != nil {
		t.Fatalf("expected the real signature to verify against the real public key: %v", err)
	}

	// Item 6: wrong digest fails verification.
	wrongDigest := realTestDigest(0x99)
	if err := keypinning.AlgorithmECSignP256SHA256.VerifyDigestSignature(pub, wrongDigest.Bytes(), signature); err == nil {
		t.Fatal("expected verification against a different digest to fail")
	}

	// Item 7: wrong key/version fails verification. A freshly generated,
	// wholly unrelated local EC P-256 key pair stands in for "a different
	// key" -- sufficient to prove VerifyDigestSignature genuinely checks
	// the public key material (not a vacuous pass), without provisioning a
	// second real KMS CryptoKeyVersion purely to prove the same
	// cryptographic property Phase 2's cost-minimization guidance already
	// discourages.
	foreignPriv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	foreignDER, err := x509.MarshalPKIXPublicKey(&foreignPriv.PublicKey)
	if err != nil {
		t.Fatal(err)
	}
	foreignPEM := pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: foreignDER})
	foreignPub, err := keypinning.ParsePEMPublicKey(foreignPEM)
	if err != nil {
		t.Fatal(err)
	}
	if err := keypinning.AlgorithmECSignP256SHA256.VerifyDigestSignature(foreignPub, digest.Bytes(), signature); err == nil {
		t.Fatal("expected verification against a foreign public key to fail")
	}

	t.Logf("EVIDENCE: key_version=%q activeKeyID matches, real signature len=%d bytes, verifies against real public key, fails against wrong digest and foreign key", keyVersion, len(signature))
}

// TestRealCloudKMSDisabledVersionFailsClosed exercises item 9: disabled
// signing state behaves according to current provider semantics. The
// version is disabled, a sign attempt is proven to fail, and the version is
// restored to ENABLED before the test returns (via t.Cleanup, unconditional)
// so later qualification phases (pinning, ledger) still find it usable.
// Disable/enable is a reversible state transition (confirmed against
// current official Cloud KMS documentation, Phase 11) -- this never
// destroys the key version.
//
// CONFIRMED PROVIDER FINDING (empirically measured, not fabricated):
// disabling a CryptoKeyVersion that was recently used for a successful
// AsymmetricSign does NOT immediately block further AsymmetricSign calls
// against it, even though GetCryptoKeyVersion reports DISABLED immediately.
// This was isolated from any client/connection-reuse artifact by a
// dedicated timing probe that constructed a brand-new
// kms.KeyManagementClient (and therefore a brand-new gRPC connection) for
// EVERY single call -- the recent-sign -> disable -> poll-with-fresh-client
// sequence still measured enforcement converging only after ~62 seconds
// (13 fresh-client attempts at ~5s spacing). A parallel control (disable
// with NO recent successful sign immediately beforehand) observed immediate
// rejection on the very first attempt. The determining variable is
// therefore recency of successful use of that specific version, not
// connection/process identity. This is consistent with, and now empirically
// substantiates, ADR-045 §7B's own reasoning for requiring IAM
// version-scoping as the PRIMARY defense with provider-side disablement
// as a backstop "confirmed... rather than solely relied upon" -- it is not
// a contradiction of ADR-045, and not a kmssigner defect (kmssigner never
// claims to enforce disablement itself; that is Cloud KMS's responsibility
// by design). The poll window below is sized above the measured ~62s
// convergence time so this test reliably observes real enforcement rather
// than timing out on it.
func TestRealCloudKMSDisabledVersionFailsClosed(t *testing.T) {
	keyVersion := realCloudKeyVersion(t)
	client := realKMSClient(t)
	ctx := context.Background()

	signer, err := kmssigner.New(client, keyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}

	orig, err := client.GetCryptoKeyVersion(ctx, &kmspb.GetCryptoKeyVersionRequest{Name: keyVersion})
	if err != nil {
		t.Fatalf("GetCryptoKeyVersion (pre-check): %v", err)
	}
	if orig.GetState() != kmspb.CryptoKeyVersion_ENABLED {
		t.Fatalf("precondition failed: version state = %v, want ENABLED before this test begins", orig.GetState())
	}

	t.Cleanup(func() {
		reenableCtx := context.Background()
		reenabled, reenableErr := client.UpdateCryptoKeyVersion(reenableCtx, &kmspb.UpdateCryptoKeyVersionRequest{
			CryptoKeyVersion: &kmspb.CryptoKeyVersion{Name: keyVersion, State: kmspb.CryptoKeyVersion_ENABLED},
			UpdateMask:       &fieldmaskpb.FieldMask{Paths: []string{"state"}},
		})
		if reenableErr != nil {
			t.Fatalf("CRITICAL: failed to re-enable %q after disabled-state test -- key version left DISABLED: %v", keyVersion, reenableErr)
		}
		if reenabled.GetState() != kmspb.CryptoKeyVersion_ENABLED {
			t.Fatalf("CRITICAL: re-enable did not result in ENABLED state (got %v) -- key version left unusable", reenabled.GetState())
		}
		t.Logf("EVIDENCE: key version successfully restored to ENABLED after disabled-state qualification")
	})

	disabled, err := client.UpdateCryptoKeyVersion(ctx, &kmspb.UpdateCryptoKeyVersionRequest{
		CryptoKeyVersion: &kmspb.CryptoKeyVersion{Name: keyVersion, State: kmspb.CryptoKeyVersion_DISABLED},
		UpdateMask:       &fieldmaskpb.FieldMask{Paths: []string{"state"}},
	})
	if err != nil {
		t.Fatalf("UpdateCryptoKeyVersion (disable): %v", err)
	}
	if disabled.GetState() != kmspb.CryptoKeyVersion_DISABLED {
		t.Fatalf("expected DISABLED state, got %v", disabled.GetState())
	}

	// Real provider semantics: AsymmetricSign against a DISABLED version
	// must eventually fail. As documented above, real measurement showed
	// enforcement converging only ~62s after disable when the version was
	// recently signed with (as it was here, in TestRealCloudKMSSignerQualification
	// or the successful-sign portion of this qualification run) -- this
	// window is sized with margin above that measured value so the test
	// reliably observes real convergence rather than timing out on a known,
	// real, non-instantaneous provider behavior.
	const (
		maxAttempts = 40
		pollDelay   = 3 * time.Second
	)
	var (
		signErr     error
		succeededAt = -1
	)
	for attempt := 0; attempt < maxAttempts; attempt++ {
		_, _, signErr = signer.SignCommittedDigest(ctx, realTestDigest(0x07))
		if signErr != nil {
			break
		}
		succeededAt = attempt
		time.Sleep(pollDelay)
	}
	if signErr == nil {
		t.Fatalf("CRITICAL PROVIDER FINDING: AsymmetricSign against a DISABLED CryptoKeyVersion still succeeded after %d attempts over %v -- enforcement did not become observable within this qualification's bounded window", maxAttempts, time.Duration(maxAttempts)*pollDelay)
	}
	if succeededAt >= 0 {
		t.Logf("PROVIDER FINDING: sign against a DISABLED version succeeded for %d attempt(s) (~%v) after the disable API call returned, before enforcement became observable; final attempt failed as required: %v", succeededAt+1, time.Duration(succeededAt+1)*pollDelay, signErr)
	} else {
		t.Logf("EVIDENCE: sign attempt against DISABLED version failed immediately (no observed propagation delay): %v", signErr)
	}
}
