package kmsverifier_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/rand"
	"errors"

	"cloud.google.com/go/kms/apiv1/kmspb"
	gax "github.com/googleapis/gax-go/v2"
)

var errAssertNeverCalled = errors.New("kmsverifier_test: this call must never happen")

// fakeSignClient implements kmssigner.AsymmetricSignClient, fabricating
// genuine ECDSA P-256 signatures with privKey when fabricateAt is true --
// this is a real, cryptographically meaningful signer for test purposes,
// not a stub that returns fixed bytes.
type fakeSignClient struct {
	privKey     *ecdsa.PrivateKey
	fabricateAt bool
	err         error
}

func (f *fakeSignClient) AsymmetricSign(_ context.Context, req *kmspb.AsymmetricSignRequest, _ ...gax.CallOption) (*kmspb.AsymmetricSignResponse, error) {
	if f.err != nil {
		return nil, f.err
	}
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

// fakePublicKeyClient implements keypinning.PublicKeyClient.
type fakePublicKeyClient struct {
	version   *kmspb.CryptoKeyVersion
	publicKey *kmspb.PublicKey
}

func (f *fakePublicKeyClient) GetCryptoKeyVersion(_ context.Context, _ *kmspb.GetCryptoKeyVersionRequest, _ ...gax.CallOption) (*kmspb.CryptoKeyVersion, error) {
	return f.version, nil
}

func (f *fakePublicKeyClient) GetPublicKey(_ context.Context, _ *kmspb.GetPublicKeyRequest, _ ...gax.CallOption) (*kmspb.PublicKey, error) {
	return f.publicKey, nil
}

func version(name string) *kmspb.CryptoKeyVersion {
	return &kmspb.CryptoKeyVersion{
		Name:      name,
		State:     kmspb.CryptoKeyVersion_ENABLED,
		Algorithm: kmspb.CryptoKeyVersion_EC_SIGN_P256_SHA256,
	}
}

func publicKey(name, pem string) *kmspb.PublicKey {
	return &kmspb.PublicKey{
		Name:      name,
		Pem:       pem,
		Algorithm: kmspb.CryptoKeyVersion_EC_SIGN_P256_SHA256,
	}
}
