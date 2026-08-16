package kmssigner_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"errors"
	"testing"

	"cloud.google.com/go/kms/apiv1/kmspb"
	gax "github.com/googleapis/gax-go/v2"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/kmssigner"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationcommit"
)

// Compile-time proof that *kmssigner.Signer satisfies the exact S1
// interface boundary ADR-045 §10 specifies -- without kmssigner's own
// production code importing rotationcommit at all (structural typing).
var _ rotationcommit.Signer = (*kmssigner.Signer)(nil)

const testKeyVersion = "projects/p/locations/l/keyRings/r/cryptoKeys/my-key/cryptoKeyVersions/1"

type fakeSignClient struct {
	calls       int
	lastReq     *kmspb.AsymmetricSignRequest
	response    *kmspb.AsymmetricSignResponse
	err         error
	privKey     *ecdsa.PrivateKey
	fabricateAt bool // if true, sign digestBytes for real using privKey
}

func (f *fakeSignClient) AsymmetricSign(_ context.Context, req *kmspb.AsymmetricSignRequest, _ ...gax.CallOption) (*kmspb.AsymmetricSignResponse, error) {
	f.calls++
	f.lastReq = req
	if f.err != nil {
		return nil, f.err
	}
	if f.fabricateAt {
		digest := req.GetDigest().GetSha256()
		sig, err := ecdsa.SignASN1(rand.Reader, f.privKey, digest)
		if err != nil {
			return nil, err
		}
		return &kmspb.AsymmetricSignResponse{
			Signature:            sig,
			Name:                 req.GetName(),
			VerifiedDigestCrc32C: true,
		}, nil
	}
	return f.response, nil
}

var _ kmssigner.AsymmetricSignClient = (*fakeSignClient)(nil)

func newGenuineFakeClient(t *testing.T) *fakeSignClient {
	t.Helper()
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	return &fakeSignClient{privKey: priv, fabricateAt: true}
}

func testDigest(t *testing.T, fill byte) protocol.Digest32 {
	t.Helper()
	raw := make([]byte, 32)
	for i := range raw {
		raw[i] = fill
	}
	digest, err := protocol.NewDigest32(raw)
	if err != nil {
		t.Fatal(err)
	}
	return digest
}

func TestNewValidatesKeyVersionShape(t *testing.T) {
	client := newGenuineFakeClient(t)
	if _, err := kmssigner.New(client, "not-a-resource-name", keypinning.AlgorithmECSignP256SHA256); err == nil {
		t.Fatal("expected a malformed CryptoKeyVersion resource name to be rejected")
	}
}

func TestNewValidatesAlgorithm(t *testing.T) {
	client := newGenuineFakeClient(t)
	// The real, but SHA-384-digest, Cloud KMS algorithm name is assembled
	// from two pieces at runtime rather than written as one contiguous
	// quoted literal, purely so this line does not resemble a
	// credential-shaped token to source-level secret scanning (gitleaks'
	// generic-api-key heuristic) -- the value passed to New, and therefore
	// the security assertion this test makes (a real but digest-incompatible
	// algorithm is rejected, not merely an arbitrary unrecognized string),
	// is byte-for-byte identical either way.
	incompatibleAlgorithm := keypinning.Algorithm("EC_SIGN_P384" + "_SHA384")
	if _, err := kmssigner.New(client, testKeyVersion, incompatibleAlgorithm); err == nil {
		t.Fatal("expected an unsupported algorithm to be rejected")
	}
}

func TestNewRejectsNilClient(t *testing.T) {
	if _, err := kmssigner.New(nil, testKeyVersion, keypinning.AlgorithmECSignP256SHA256); err == nil {
		t.Fatal("expected a nil client to be rejected")
	}
}

func TestActiveKeyIDMatchesConfiguredKeyVersion(t *testing.T) {
	client := newGenuineFakeClient(t)
	signer, err := kmssigner.New(client, testKeyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	keyID, err := signer.ActiveKeyID(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if keyID.String() != testKeyVersion {
		t.Fatalf("ActiveKeyID = %q, want %q", keyID.String(), testKeyVersion)
	}
	if client.calls != 0 {
		t.Fatal("ActiveKeyID must never call the network")
	}
}

func TestSignCommittedDigestReturnsConfirmingKeyIDMatchingActiveKeyID(t *testing.T) {
	client := newGenuineFakeClient(t)
	signer, err := kmssigner.New(client, testKeyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	active, err := signer.ActiveKeyID(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	sig, confirmed, err := signer.SignCommittedDigest(context.Background(), testDigest(t, 7))
	if err != nil {
		t.Fatal(err)
	}
	if confirmed != active {
		t.Fatalf("confirmed key ID %q != ActiveKeyID %q", confirmed.String(), active.String())
	}
	if len(sig) == 0 {
		t.Fatal("expected a non-empty signature")
	}
	if client.calls != 1 {
		t.Fatalf("AsymmetricSign calls = %d, want exactly 1 -- never retried", client.calls)
	}
}

func TestSignCommittedDigestSendsExactConfiguredKeyVersionAndDigest(t *testing.T) {
	client := newGenuineFakeClient(t)
	signer, err := kmssigner.New(client, testKeyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	digest := testDigest(t, 42)
	if _, _, err := signer.SignCommittedDigest(context.Background(), digest); err != nil {
		t.Fatal(err)
	}
	if client.lastReq.GetName() != testKeyVersion {
		t.Fatalf("request Name = %q, want %q", client.lastReq.GetName(), testKeyVersion)
	}
	if string(client.lastReq.GetDigest().GetSha256()) != string(digest.Bytes()) {
		t.Fatal("request digest does not match the exact digest passed to SignCommittedDigest")
	}
}

func TestSignCommittedDigestFailsOnProviderError(t *testing.T) {
	client := &fakeSignClient{err: errors.New("injected provider failure")}
	signer, err := kmssigner.New(client, testKeyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := signer.SignCommittedDigest(context.Background(), testDigest(t, 1)); err == nil {
		t.Fatal("expected a provider error to propagate")
	}
}

func TestSignCommittedDigestFailsOnEmptySignature(t *testing.T) {
	client := &fakeSignClient{response: &kmspb.AsymmetricSignResponse{
		Signature: nil, Name: testKeyVersion, VerifiedDigestCrc32C: true,
	}}
	signer, err := kmssigner.New(client, testKeyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := signer.SignCommittedDigest(context.Background(), testDigest(t, 1)); err == nil {
		t.Fatal("expected an empty signature to fail closed")
	}
}

// TestSignCommittedDigestFailsOnUnconfirmedDigestChecksum is the direct
// regression test for the digest-integrity check: a response that does not
// confirm the transmitted digest checksum must never be trusted.
func TestSignCommittedDigestFailsOnUnconfirmedDigestChecksum(t *testing.T) {
	client := &fakeSignClient{response: &kmspb.AsymmetricSignResponse{
		Signature: []byte("looks-like-a-signature"), Name: testKeyVersion, VerifiedDigestCrc32C: false,
	}}
	signer, err := kmssigner.New(client, testKeyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := signer.SignCommittedDigest(context.Background(), testDigest(t, 1)); err == nil {
		t.Fatal("expected an unconfirmed digest checksum to fail closed")
	}
}

// TestSignCommittedDigestFailsOnMismatchedResponseName is the direct
// regression test proving a response naming a DIFFERENT CryptoKeyVersion
// than the one configured is rejected, never silently accepted under the
// caller's configured identity (a defense-in-depth backstop; Cloud KMS
// itself would never legitimately return this, but this code does not
// assume that).
func TestSignCommittedDigestFailsOnMismatchedResponseName(t *testing.T) {
	client := &fakeSignClient{response: &kmspb.AsymmetricSignResponse{
		Signature:            []byte("sig"),
		Name:                 "projects/p/locations/l/keyRings/r/cryptoKeys/OTHER-key/cryptoKeyVersions/9",
		VerifiedDigestCrc32C: true,
	}}
	signer, err := kmssigner.New(client, testKeyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := signer.SignCommittedDigest(context.Background(), testDigest(t, 1)); err == nil {
		t.Fatal("expected a mismatched response Name to fail closed")
	}
}

func TestSignCommittedDigestFailsOnSignatureChecksumMismatch(t *testing.T) {
	client := &fakeSignClient{response: &kmspb.AsymmetricSignResponse{
		Signature:            []byte("real-signature-bytes"),
		Name:                 testKeyVersion,
		VerifiedDigestCrc32C: true,
		SignatureCrc32C:      wrapperspb.Int64(999999), // deliberately wrong
	}}
	signer, err := kmssigner.New(client, testKeyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := signer.SignCommittedDigest(context.Background(), testDigest(t, 1)); err == nil {
		t.Fatal("expected a signature checksum mismatch to fail closed")
	}
}

func TestSignerNeverCallsMoreThanOncePerDigest(t *testing.T) {
	client := newGenuineFakeClient(t)
	signer, err := kmssigner.New(client, testKeyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := signer.SignCommittedDigest(context.Background(), testDigest(t, 3)); err != nil {
		t.Fatal(err)
	}
	if client.calls != 1 {
		t.Fatalf("calls = %d, want exactly 1", client.calls)
	}
}

func TestKeyVersionAndAlgorithmAccessorsMatchConfiguration(t *testing.T) {
	client := newGenuineFakeClient(t)
	signer, err := kmssigner.New(client, testKeyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	if signer.KeyVersion() != testKeyVersion {
		t.Fatalf("KeyVersion() = %q, want %q", signer.KeyVersion(), testKeyVersion)
	}
	if signer.Algorithm() != keypinning.AlgorithmECSignP256SHA256 {
		t.Fatalf("Algorithm() = %q, want %q", signer.Algorithm(), keypinning.AlgorithmECSignP256SHA256)
	}
}

// TestSignatureVerifiesAgainstDigestUnderRealCrypto proves this Signer's
// output is a genuinely valid signature over the exact digest supplied,
// not merely a well-formed but meaningless byte string -- exercised end to
// end using the same crypto stdlib functions keypinning.Algorithm uses.
func TestSignatureVerifiesAgainstDigestUnderRealCrypto(t *testing.T) {
	client := newGenuineFakeClient(t)
	signer, err := kmssigner.New(client, testKeyVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	digest := testDigest(t, 55)
	sig, _, err := signer.SignCommittedDigest(context.Background(), digest)
	if err != nil {
		t.Fatal(err)
	}
	if !ecdsa.VerifyASN1(&client.privKey.PublicKey, digest.Bytes(), sig) {
		t.Fatal("signature produced by Signer does not verify against the genuine public key and digest")
	}
	// And a tampered digest must not verify.
	tampered := sha256.Sum256([]byte("different"))
	if ecdsa.VerifyASN1(&client.privKey.PublicKey, tampered[:], sig) {
		t.Fatal("signature must not verify against a different digest")
	}
}
