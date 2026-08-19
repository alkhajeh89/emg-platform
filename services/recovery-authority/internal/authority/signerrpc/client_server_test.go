package signerrpc_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/signerrpc"
)

type fakeSigner struct {
	keyID     protocol.SigningKeyID
	signature []byte
	confirmed protocol.SigningKeyID
	err       error
	calls     int
}

func (f *fakeSigner) ActiveKeyID(context.Context) (protocol.SigningKeyID, error) {
	return f.keyID, f.err
}

func (f *fakeSigner) SignCommittedDigest(_ context.Context, _ protocol.Digest32) ([]byte, protocol.SigningKeyID, error) {
	f.calls++
	if f.err != nil {
		return nil, protocol.SigningKeyID{}, f.err
	}
	return f.signature, f.confirmed, nil
}

var _ signerrpc.Signer = (*fakeSigner)(nil)

type fakeTokenSource struct {
	token string
	err   error
}

func (f fakeTokenSource) Token(context.Context) (string, error) { return f.token, f.err }

type fakeVerifier struct {
	expectedToken string
	identity      string
	err           error
}

func (f fakeVerifier) Verify(_ context.Context, token string) (string, error) {
	if f.err != nil {
		return "", f.err
	}
	if token != f.expectedToken {
		return "", errors.New("fakeVerifier: token mismatch")
	}
	return f.identity, nil
}

func testKeyID(t *testing.T) protocol.SigningKeyID {
	t.Helper()
	id, err := protocol.NewSigningKeyID("projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	if err != nil {
		t.Fatal(err)
	}
	return id
}

func testDigest(t *testing.T) protocol.Digest32 {
	t.Helper()
	raw := make([]byte, 32)
	for i := range raw {
		raw[i] = byte(i)
	}
	digest, err := protocol.NewDigest32(raw)
	if err != nil {
		t.Fatal(err)
	}
	return digest
}

func newTestServer(t *testing.T, signer signerrpc.Signer, verifier signerrpc.IdentityVerifier) *httptest.Server {
	t.Helper()
	server, err := signerrpc.NewServer(signer, verifier, nil)
	if err != nil {
		t.Fatal(err)
	}
	return httptest.NewServer(server.Handler())
}

func newTLSTestServer(t *testing.T, signer signerrpc.Signer, verifier signerrpc.IdentityVerifier) *httptest.Server {
	t.Helper()
	server, err := signerrpc.NewServer(signer, verifier, nil)
	if err != nil {
		t.Fatal(err)
	}
	return httptest.NewTLSServer(server.Handler())
}

// TestClientServerRoundTripOverRealTLS is the direct TLS-fix regression
// test for adversarial-matrix item K: the exact same bearer-token
// authentication this package already enforces over plain HTTP
// (TestServerRejectsMissingBearerToken/TestServerRejectsWrongToken) is
// re-exercised here over a genuine TLS connection
// (httptest.NewTLSServer), proving TLS is additive transport security,
// never a substitute for -- and never a bypass of -- the existing
// caller-authentication check.
func TestClientServerRoundTripOverRealTLS(t *testing.T) {
	keyID := testKeyID(t)
	signer := &fakeSigner{keyID: keyID, signature: []byte{0x01, 0x02, 0x03}, confirmed: keyID}
	tlsTestServer := newTLSTestServer(t, signer, fakeVerifier{expectedToken: "good-token", identity: "caller@example.iam.gserviceaccount.com"})
	defer tlsTestServer.Close()

	if !strings.HasPrefix(tlsTestServer.URL, "https://") {
		t.Fatalf("httptest.NewTLSServer URL = %q, want an https:// URL", tlsTestServer.URL)
	}

	// A correctly-authenticated client over TLS still succeeds.
	client, err := signerrpc.NewClient(tlsTestServer.Client(), tlsTestServer.URL, fakeTokenSource{token: "good-token"}, false)
	if err != nil {
		t.Fatal(err)
	}
	gotKeyID, err := client.ActiveKeyID(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if gotKeyID != keyID {
		t.Fatalf("ActiveKeyID = %q, want %q", gotKeyID.String(), keyID.String())
	}

	// A missing bearer token is still rejected over TLS -- TLS never
	// substitutes for caller authentication.
	resp, err := tlsTestServer.Client().Get(tlsTestServer.URL + "/v1/active-key-id")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", resp.StatusCode, http.StatusUnauthorized)
	}

	// A wrong bearer token is still rejected over TLS.
	wrongClient, err := signerrpc.NewClient(tlsTestServer.Client(), tlsTestServer.URL, fakeTokenSource{token: "wrong-token"}, false)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := wrongClient.ActiveKeyID(context.Background()); err == nil {
		t.Fatal("expected a wrong bearer token to be rejected even over TLS")
	}
}

func TestClientServerRoundTrip(t *testing.T) {
	keyID := testKeyID(t)
	signer := &fakeSigner{keyID: keyID, signature: []byte{0x01, 0x02, 0x03}, confirmed: keyID}
	httpTestServer := newTestServer(t, signer, fakeVerifier{expectedToken: "good-token", identity: "caller@example.iam.gserviceaccount.com"})
	defer httpTestServer.Close()

	client, err := signerrpc.NewClient(httpTestServer.Client(), httpTestServer.URL, fakeTokenSource{token: "good-token"}, true)
	if err != nil {
		t.Fatal(err)
	}

	gotKeyID, err := client.ActiveKeyID(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if gotKeyID != keyID {
		t.Fatalf("ActiveKeyID = %q, want %q", gotKeyID.String(), keyID.String())
	}

	sig, confirmed, err := client.SignCommittedDigest(context.Background(), testDigest(t))
	if err != nil {
		t.Fatal(err)
	}
	if string(sig) != string(signer.signature) {
		t.Fatal("signature does not round-trip")
	}
	if confirmed != keyID {
		t.Fatalf("confirmed key = %q, want %q", confirmed.String(), keyID.String())
	}
	if signer.calls != 1 {
		t.Fatalf("signer.calls = %d, want 1", signer.calls)
	}
}

func TestServerRejectsMissingBearerToken(t *testing.T) {
	httpTestServer := newTestServer(t, &fakeSigner{keyID: testKeyID(t)}, fakeVerifier{expectedToken: "good-token"})
	defer httpTestServer.Close()

	resp, err := http.Get(httpTestServer.URL + "/v1/active-key-id")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", resp.StatusCode, http.StatusUnauthorized)
	}
}

func TestServerRejectsWrongToken(t *testing.T) {
	httpTestServer := newTestServer(t, &fakeSigner{keyID: testKeyID(t)}, fakeVerifier{expectedToken: "good-token"})
	defer httpTestServer.Close()

	client, err := signerrpc.NewClient(httpTestServer.Client(), httpTestServer.URL, fakeTokenSource{token: "wrong-token"}, true)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := client.ActiveKeyID(context.Background()); err == nil {
		t.Fatal("expected a wrong bearer token to be rejected")
	}
}

func TestServerRejectsVerifierError(t *testing.T) {
	httpTestServer := newTestServer(t, &fakeSigner{keyID: testKeyID(t)}, fakeVerifier{err: errors.New("injected verifier failure")})
	defer httpTestServer.Close()
	client, err := signerrpc.NewClient(httpTestServer.Client(), httpTestServer.URL, fakeTokenSource{token: "anything"}, true)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := client.ActiveKeyID(context.Background()); err == nil {
		t.Fatal("expected a verifier failure to reject the request")
	}
}

func TestNewClientRejectsPlainHTTPUnlessInsecureAllowed(t *testing.T) {
	if _, err := signerrpc.NewClient(http.DefaultClient, "http://example.com", fakeTokenSource{token: "x"}, false); err == nil {
		t.Fatal("expected a plain http:// baseURL to be rejected when allowInsecure is false")
	}
	if _, err := signerrpc.NewClient(http.DefaultClient, "http://example.com", fakeTokenSource{token: "x"}, true); err != nil {
		t.Fatalf("expected http:// to be accepted when allowInsecure is true: %v", err)
	}
	if _, err := signerrpc.NewClient(http.DefaultClient, "https://example.com", fakeTokenSource{token: "x"}, false); err != nil {
		t.Fatalf("expected https:// to always be accepted: %v", err)
	}
}

func TestNewClientRejectsMissingArguments(t *testing.T) {
	if _, err := signerrpc.NewClient(nil, "https://example.com", fakeTokenSource{token: "x"}, false); err == nil {
		t.Fatal("expected nil httpClient to be rejected")
	}
	if _, err := signerrpc.NewClient(http.DefaultClient, "https://example.com", nil, false); err == nil {
		t.Fatal("expected nil TokenSource to be rejected")
	}
}

func TestNewServerRejectsMissingArguments(t *testing.T) {
	if _, err := signerrpc.NewServer(nil, fakeVerifier{}, nil); err == nil {
		t.Fatal("expected nil signer to be rejected")
	}
	if _, err := signerrpc.NewServer(&fakeSigner{}, nil, nil); err == nil {
		t.Fatal("expected nil verifier to be rejected")
	}
}

func TestSignFailurePropagates(t *testing.T) {
	httpTestServer := newTestServer(t, &fakeSigner{err: errors.New("kms unavailable")}, fakeVerifier{expectedToken: "good", identity: "x"})
	defer httpTestServer.Close()
	client, err := signerrpc.NewClient(httpTestServer.Client(), httpTestServer.URL, fakeTokenSource{token: "good"}, true)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := client.SignCommittedDigest(context.Background(), testDigest(t)); err == nil {
		t.Fatal("expected the remote signer's failure to propagate as an error")
	}
}

func TestSignRejectsMalformedDigestHex(t *testing.T) {
	httpTestServer := newTestServer(t, &fakeSigner{}, fakeVerifier{expectedToken: "good", identity: "x"})
	defer httpTestServer.Close()
	req, err := http.NewRequest(http.MethodPost, httpTestServer.URL+"/v1/sign", strings.NewReader(`{"digest_hex":"not-hex"}`))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer good")
	req.Header.Set("Content-Type", "application/json")
	resp, err := httpTestServer.Client().Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", resp.StatusCode, http.StatusBadRequest)
	}
}
