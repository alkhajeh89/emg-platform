package keypinning

import (
	"context"
	"testing"

	"cloud.google.com/go/kms/apiv1/kmspb"
	gax "github.com/googleapis/gax-go/v2"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/recovery"
)

type fakePublicKeyClient struct {
	version   *kmspb.CryptoKeyVersion
	publicKey *kmspb.PublicKey
	err       error
}

func (f *fakePublicKeyClient) GetCryptoKeyVersion(_ context.Context, _ *kmspb.GetCryptoKeyVersionRequest, _ ...gax.CallOption) (*kmspb.CryptoKeyVersion, error) {
	if f.err != nil {
		return nil, f.err
	}
	return f.version, nil
}

func (f *fakePublicKeyClient) GetPublicKey(_ context.Context, _ *kmspb.GetPublicKeyRequest, _ ...gax.CallOption) (*kmspb.PublicKey, error) {
	if f.err != nil {
		return nil, f.err
	}
	return f.publicKey, nil
}

var _ PublicKeyClient = (*fakePublicKeyClient)(nil)

const testKeyVersionName = "projects/p/locations/l/keyRings/r/cryptoKeys/my-key/cryptoKeyVersions/1"

func approveMyKeyLineage(t *testing.T) recovery.ApprovedSigningLineage {
	t.Helper()
	lineage, err := CryptoKeyLineage("projects/p/locations/l/keyRings/r/cryptoKeys/my-key")
	if err != nil {
		t.Fatal(err)
	}
	return lineage
}

func TestCaptureFromKMSSucceedsForEnabledApprovedKey(t *testing.T) {
	_, pemStr := generateECDSATestKey(t)
	client := &fakePublicKeyClient{
		version: &kmspb.CryptoKeyVersion{
			Name:      testKeyVersionName,
			State:     kmspb.CryptoKeyVersion_ENABLED,
			Algorithm: kmspb.CryptoKeyVersion_EC_SIGN_P256_SHA256,
		},
		publicKey: &kmspb.PublicKey{
			Name:      testKeyVersionName,
			Pem:       pemStr,
			Algorithm: kmspb.CryptoKeyVersion_EC_SIGN_P256_SHA256,
		},
	}
	pin, err := CaptureFromKMS(context.Background(), client, testKeyVersionName, approveMyKeyLineage(t), "test capture")
	if err != nil {
		t.Fatal(err)
	}
	if pin.PublicKeyPEM != pemStr {
		t.Fatal("captured pin does not carry the retrieved public key material")
	}
	if pin.Algorithm != AlgorithmECSignP256SHA256 {
		t.Fatalf("algorithm = %s, want %s", pin.Algorithm, AlgorithmECSignP256SHA256)
	}
}

func TestCaptureFromKMSRejectsDisabledVersion(t *testing.T) {
	client := &fakePublicKeyClient{
		version: &kmspb.CryptoKeyVersion{
			Name:      testKeyVersionName,
			State:     kmspb.CryptoKeyVersion_DISABLED,
			Algorithm: kmspb.CryptoKeyVersion_EC_SIGN_P256_SHA256,
		},
	}
	_, err := CaptureFromKMS(context.Background(), client, testKeyVersionName, approveMyKeyLineage(t), "")
	if err == nil {
		t.Fatal("expected capture of a DISABLED version's public key to be refused")
	}
}

func TestCaptureFromKMSRejectsDestroyedVersion(t *testing.T) {
	client := &fakePublicKeyClient{
		version: &kmspb.CryptoKeyVersion{
			Name:  testKeyVersionName,
			State: kmspb.CryptoKeyVersion_DESTROYED,
		},
	}
	_, err := CaptureFromKMS(context.Background(), client, testKeyVersionName, approveMyKeyLineage(t), "")
	if err == nil {
		t.Fatal("expected capture of a DESTROYED version to be refused")
	}
}

func TestCaptureFromKMSRejectsKeyOutsideApprovedLineage(t *testing.T) {
	_, pemStr := generateECDSATestKey(t)
	foreignKeyVersion := "projects/p/locations/l/keyRings/r/cryptoKeys/foreign-key/cryptoKeyVersions/1"
	client := &fakePublicKeyClient{
		version: &kmspb.CryptoKeyVersion{
			Name:      foreignKeyVersion,
			State:     kmspb.CryptoKeyVersion_ENABLED,
			Algorithm: kmspb.CryptoKeyVersion_EC_SIGN_P256_SHA256,
		},
		publicKey: &kmspb.PublicKey{Name: foreignKeyVersion, Pem: pemStr, Algorithm: kmspb.CryptoKeyVersion_EC_SIGN_P256_SHA256},
	}
	_, err := CaptureFromKMS(context.Background(), client, foreignKeyVersion, approveMyKeyLineage(t), "")
	if err == nil {
		t.Fatal("expected capture of a key outside the approved lineage to be refused")
	}
}

func TestCaptureFromKMSRequiresApprovedLineage(t *testing.T) {
	_, err := CaptureFromKMS(context.Background(), &fakePublicKeyClient{}, testKeyVersionName, nil, "")
	if err == nil {
		t.Fatal("expected a nil approvedLineage to be rejected")
	}
}

func TestCaptureFromKMSRejectsUnsupportedAlgorithm(t *testing.T) {
	_, pemStr := generateECDSATestKey(t)
	client := &fakePublicKeyClient{
		version: &kmspb.CryptoKeyVersion{
			Name:      testKeyVersionName,
			State:     kmspb.CryptoKeyVersion_ENABLED,
			Algorithm: kmspb.CryptoKeyVersion_EC_SIGN_P384_SHA384,
		},
		publicKey: &kmspb.PublicKey{Name: testKeyVersionName, Pem: pemStr, Algorithm: kmspb.CryptoKeyVersion_EC_SIGN_P384_SHA384},
	}
	_, err := CaptureFromKMS(context.Background(), client, testKeyVersionName, approveMyKeyLineage(t), "")
	if err == nil {
		t.Fatal("expected an unsupported (non-SHA-256) algorithm to be rejected")
	}
}
