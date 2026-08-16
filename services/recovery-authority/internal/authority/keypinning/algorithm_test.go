package keypinning

import (
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/pem"
	"testing"
)

func generateECDSATestKey(t *testing.T) (*ecdsa.PrivateKey, string) {
	t.Helper()
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	der, err := x509.MarshalPKIXPublicKey(&priv.PublicKey)
	if err != nil {
		t.Fatal(err)
	}
	pemBytes := pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der})
	return priv, string(pemBytes)
}

func generateRSATestKey(t *testing.T) (*rsa.PrivateKey, string) {
	t.Helper()
	priv, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	der, err := x509.MarshalPKIXPublicKey(&priv.PublicKey)
	if err != nil {
		t.Fatal(err)
	}
	pemBytes := pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der})
	return priv, string(pemBytes)
}

func TestECDSASignVerifyRoundTrip(t *testing.T) {
	priv, pemStr := generateECDSATestKey(t)
	digest := sha256.Sum256([]byte("test message"))
	sig, err := ecdsa.SignASN1(rand.Reader, priv, digest[:])
	if err != nil {
		t.Fatal(err)
	}
	pub, err := ParsePEMPublicKey([]byte(pemStr))
	if err != nil {
		t.Fatal(err)
	}
	if err := AlgorithmECSignP256SHA256.VerifyDigestSignature(pub, digest[:], sig); err != nil {
		t.Fatalf("genuine signature rejected: %v", err)
	}
}

func TestECDSAVerifyRejectsTamperedDigest(t *testing.T) {
	priv, pemStr := generateECDSATestKey(t)
	digest := sha256.Sum256([]byte("test message"))
	sig, err := ecdsa.SignASN1(rand.Reader, priv, digest[:])
	if err != nil {
		t.Fatal(err)
	}
	pub, err := ParsePEMPublicKey([]byte(pemStr))
	if err != nil {
		t.Fatal(err)
	}
	other := sha256.Sum256([]byte("different message"))
	if err := AlgorithmECSignP256SHA256.VerifyDigestSignature(pub, other[:], sig); err == nil {
		t.Fatal("expected verification against a different digest to fail")
	}
}

func TestRSAPSSSignVerifyRoundTrip(t *testing.T) {
	priv, pemStr := generateRSATestKey(t)
	digest := sha256.Sum256([]byte("test message"))
	sig, err := rsa.SignPSS(rand.Reader, priv, crypto.SHA256, digest[:], &rsa.PSSOptions{SaltLength: rsa.PSSSaltLengthEqualsHash})
	if err != nil {
		t.Fatal(err)
	}
	pub, err := ParsePEMPublicKey([]byte(pemStr))
	if err != nil {
		t.Fatal(err)
	}
	if err := AlgorithmRSASignPSS2048SHA256.VerifyDigestSignature(pub, digest[:], sig); err != nil {
		t.Fatalf("genuine PSS signature rejected: %v", err)
	}
}

func TestRSAPKCS1SignVerifyRoundTrip(t *testing.T) {
	priv, pemStr := generateRSATestKey(t)
	digest := sha256.Sum256([]byte("test message"))
	sig, err := rsa.SignPKCS1v15(rand.Reader, priv, crypto.SHA256, digest[:])
	if err != nil {
		t.Fatal(err)
	}
	pub, err := ParsePEMPublicKey([]byte(pemStr))
	if err != nil {
		t.Fatal(err)
	}
	if err := AlgorithmRSASignPKCS1_2048SHA256.VerifyDigestSignature(pub, digest[:], sig); err != nil {
		t.Fatalf("genuine PKCS1 signature rejected: %v", err)
	}
}

func TestVerifyRejectsAlgorithmKeyTypeMismatch(t *testing.T) {
	_, ecPEM := generateECDSATestKey(t)
	pub, err := ParsePEMPublicKey([]byte(ecPEM))
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256([]byte("x"))
	if err := AlgorithmRSASignPSS2048SHA256.VerifyDigestSignature(pub, digest[:], []byte("sig")); err == nil {
		t.Fatal("expected an RSA algorithm applied to an EC public key to fail")
	}
}

func TestAlgorithmSupported(t *testing.T) {
	supported := []Algorithm{
		AlgorithmECSignP256SHA256, AlgorithmECSignSecp256k1SHA256,
		AlgorithmRSASignPSS2048SHA256, AlgorithmRSASignPSS3072SHA256, AlgorithmRSASignPSS4096SHA256,
		AlgorithmRSASignPKCS1_2048SHA256, AlgorithmRSASignPKCS1_3072SHA256, AlgorithmRSASignPKCS1_4096SHA256,
	}
	for _, alg := range supported {
		if !alg.Supported() {
			t.Errorf("%s should be supported", alg)
		}
	}
	unsupported := []Algorithm{"EC_SIGN_P384_SHA384", "EC_SIGN_ED25519", "RSA_SIGN_RAW_PKCS1_2048", "bogus"}
	for _, alg := range unsupported {
		if alg.Supported() {
			t.Errorf("%s must not be supported -- incompatible with this protocol's SHA-256-only digests", alg)
		}
	}
}

func TestParsePEMPublicKeyRejectsPrivateKeyBlock(t *testing.T) {
	priv, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	der := x509.MarshalPKCS1PrivateKey(priv)
	block := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: der})
	if _, err := ParsePEMPublicKey(block); err == nil {
		t.Fatal("expected a private key PEM block to be rejected")
	}
}

func TestParsePEMPublicKeyRejectsGarbage(t *testing.T) {
	if _, err := ParsePEMPublicKey([]byte("not a pem block")); err == nil {
		t.Fatal("expected garbage input to fail")
	}
}
