package lifecycle

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"io"
	"log/slog"
	"math/big"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

// testCertBundle is an ephemeral, dynamically-generated (never committed,
// never hardcoded) ECDSA P-256 certificate chain: a self-signed test CA
// and a leaf certificate it issues for dnsName, written to a fresh
// t.TempDir(). It exists solely to exercise this package's real
// certificate-loading and TLS-handshake code paths against genuine X.509
// material -- nothing here is a production credential, and nothing here
// is ever written outside a test's own temporary directory.
type testCertBundle struct {
	certFile string
	keyFile  string
	caPool   *x509.CertPool
}

func generateTestCertBundle(t *testing.T, dnsName string) testCertBundle {
	t.Helper()
	dir := t.TempDir()

	caKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	caTemplate := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "lifecycle-test-ca"},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(time.Hour),
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature,
		BasicConstraintsValid: true,
		IsCA:                  true,
	}
	caDER, err := x509.CreateCertificate(rand.Reader, caTemplate, caTemplate, &caKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	caCert, err := x509.ParseCertificate(caDER)
	if err != nil {
		t.Fatal(err)
	}

	leafKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	leafTemplate := &x509.Certificate{
		SerialNumber: big.NewInt(2),
		Subject:      pkix.Name{CommonName: dnsName},
		DNSNames:     []string{dnsName},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	leafDER, err := x509.CreateCertificate(rand.Reader, leafTemplate, caCert, &leafKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}

	certFile := filepath.Join(dir, "tls.crt")
	keyFile := filepath.Join(dir, "tls.key")
	writePEM(t, certFile, "CERTIFICATE", leafDER)
	keyDER, err := x509.MarshalECPrivateKey(leafKey)
	if err != nil {
		t.Fatal(err)
	}
	writePEM(t, keyFile, "EC PRIVATE KEY", keyDER)

	pool := x509.NewCertPool()
	pool.AddCert(caCert)

	return testCertBundle{certFile: certFile, keyFile: keyFile, caPool: pool}
}

func writePEM(t *testing.T, path, blockType string, der []byte) {
	t.Helper()
	file, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	if err := pem.Encode(file, &pem.Block{Type: blockType, Bytes: der}); err != nil {
		t.Fatal(err)
	}
}

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// --- A/J: valid TLS config loads and a real handshake with the correct
// CA/server name succeeds. ---

func TestServerTLSConfigLoadsValidCertificate(t *testing.T) {
	t.Parallel()
	bundle := generateTestCertBundle(t, "localhost")
	cfg, err := ServerTLSConfig(bundle.certFile, bundle.keyFile)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.MinVersion != tls.VersionTLS12 {
		t.Fatalf("MinVersion = %v, want TLS 1.2", cfg.MinVersion)
	}
	if len(cfg.Certificates) != 1 {
		t.Fatalf("len(Certificates) = %d, want 1", len(cfg.Certificates))
	}
}

// --- B/C: missing certificate/key file paths fail startup. ---

func TestServerTLSConfigFailsOnEmptyPaths(t *testing.T) {
	t.Parallel()
	if _, err := ServerTLSConfig("", "somekey"); err == nil {
		t.Fatal("expected an error for an empty certificate path")
	}
	if _, err := ServerTLSConfig("somecert", ""); err == nil {
		t.Fatal("expected an error for an empty key path")
	}
}

func TestServerTLSConfigFailsOnMissingFiles(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	_, err := ServerTLSConfig(filepath.Join(dir, "does-not-exist.crt"), filepath.Join(dir, "does-not-exist.key"))
	if err == nil {
		t.Fatal("expected an error when the certificate/key files do not exist")
	}
}

// --- D: malformed certificate fails startup. ---

func TestServerTLSConfigFailsOnMalformedCertificate(t *testing.T) {
	t.Parallel()
	bundle := generateTestCertBundle(t, "localhost")
	dir := t.TempDir()
	garbageCert := filepath.Join(dir, "garbage.crt")
	if err := os.WriteFile(garbageCert, []byte("this is not a certificate"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := ServerTLSConfig(garbageCert, bundle.keyFile); err == nil {
		t.Fatal("expected an error for a malformed certificate file")
	}
}

func TestServerTLSConfigFailsOnMismatchedKey(t *testing.T) {
	t.Parallel()
	bundleA := generateTestCertBundle(t, "localhost")
	bundleB := generateTestCertBundle(t, "localhost")
	if _, err := ServerTLSConfig(bundleA.certFile, bundleB.keyFile); err == nil {
		t.Fatal("expected an error when the certificate and key do not match")
	}
}

// --- E/H/I/J: real end-to-end handshake behavior. ---

func startTLSTestServer(t *testing.T, bundle testCertBundle) (addr string, stop func()) {
	t.Helper()
	tlsConfig, err := ServerTLSConfig(bundle.certFile, bundle.keyFile)
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)

	// Use a fixed loopback port so the test client can dial it by the same
	// hostname the certificate's SAN names ("localhost"); RunTLS's own
	// addr argument is what net/http binds to.
	listenerAddr := "127.0.0.1:0"
	server := &http.Server{Addr: listenerAddr, Handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}), TLSConfig: tlsConfig}
	realListener, err := net.Listen("tcp", listenerAddr)
	if err != nil {
		t.Fatal(err)
	}
	go func() {
		err := server.ServeTLS(realListener, "", "")
		if err != nil && err != http.ErrServerClosed {
			done <- err
			return
		}
		done <- nil
	}()

	stop = func() {
		shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer shutdownCancel()
		_ = server.Shutdown(shutdownCtx)
		<-done
	}
	return realListener.Addr().String(), stop
}

func TestTLSHandshakeSucceedsWithCorrectCAAndServerName(t *testing.T) {
	t.Parallel()
	bundle := generateTestCertBundle(t, "localhost")
	addr, stop := startTLSTestServer(t, bundle)
	defer stop()

	client := &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{RootCAs: bundle.caPool, MinVersion: tls.VersionTLS12}}}
	// Dial by hostname "localhost", not the listener's raw IP -- the
	// certificate's SAN names "localhost", not an IP address, exactly
	// matching how signerrpc.Client dials by the signer's DNS name in
	// production.
	resp, err := client.Get("https://localhost:" + portOf(t, addr) + "/")
	if err != nil {
		t.Fatalf("expected a successful handshake and request, got: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
}

func portOf(t *testing.T, addr string) string {
	t.Helper()
	_, port, err := net.SplitHostPort(addr)
	if err != nil {
		t.Fatal(err)
	}
	return port
}

func TestTLSHandshakeFailsWithWrongCA(t *testing.T) {
	t.Parallel()
	bundle := generateTestCertBundle(t, "localhost")
	otherBundle := generateTestCertBundle(t, "localhost") // a different, unrelated CA
	addr, stop := startTLSTestServer(t, bundle)
	defer stop()

	client := &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{RootCAs: otherBundle.caPool, MinVersion: tls.VersionTLS12}}}
	_, err := client.Get("https://localhost:" + portOf(t, addr) + "/")
	if err == nil {
		t.Fatal("expected the handshake to fail against a CA pool that did not issue the server certificate")
	}
}

func TestTLSHandshakeFailsWithWrongServerName(t *testing.T) {
	t.Parallel()
	bundle := generateTestCertBundle(t, "signer.example.internal") // cert is NOT valid for "localhost"
	addr, stop := startTLSTestServer(t, bundle)
	defer stop()

	client := &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{RootCAs: bundle.caPool, MinVersion: tls.VersionTLS12}}}
	_, err := client.Get("https://localhost:" + portOf(t, addr) + "/")
	if err == nil {
		t.Fatal("expected the handshake to fail: connecting via 'localhost' but the certificate is only valid for 'signer.example.internal'")
	}
}

func TestPlaintextHTTPClientRejectedByTLSServer(t *testing.T) {
	t.Parallel()
	bundle := generateTestCertBundle(t, "localhost")
	addr, stop := startTLSTestServer(t, bundle)
	defer stop()

	// A plain HTTP client speaking cleartext to a TLS-only listener must
	// never receive the actual handler's response. net/http's server
	// specifically detects this case and returns a plaintext 4xx advising
	// HTTPS, rather than erroring the TCP connection outright -- so the
	// correct assertion is "never a successful 200 from the real handler",
	// not merely "err != nil".
	resp, err := http.Get("http://" + addr + "/")
	if err == nil {
		defer resp.Body.Close()
		if resp.StatusCode == http.StatusOK {
			t.Fatal("expected a plaintext HTTP request to a TLS-only listener to never reach the real handler")
		}
	}
}

// --- M: graceful shutdown under TLS (direct RunTLS counterpart to
// TestRunGracefulShutdownOnSignal). ---

func TestRunTLSGracefulShutdownOnSignal(t *testing.T) {
	bundle := generateTestCertBundle(t, "localhost")
	tlsConfig, err := ServerTLSConfig(bundle.certFile, bundle.keyFile)
	if err != nil {
		t.Fatal(err)
	}
	r := &Readiness{}
	r.SetReady()
	logger := NewLogger()

	done := make(chan error, 1)
	go func() {
		done <- RunTLS(context.Background(), logger, "127.0.0.1:0", Handler(r), tlsConfig, 2*time.Second)
	}()

	time.Sleep(50 * time.Millisecond)
	if err := syscall.Kill(syscall.Getpid(), syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("RunTLS returned an error on graceful shutdown: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("RunTLS did not return within the bounded shutdown window")
	}
}

func TestRunTLSFailsClosedWithoutFallingBackToPlaintext(t *testing.T) {
	t.Parallel()
	r := &Readiness{}
	logger := discardLogger()
	// A nil tlsConfig (no certificate configured at all) must fail --
	// RunTLS never silently serves plaintext as a fallback.
	err := RunTLS(context.Background(), logger, "127.0.0.1:0", Handler(r), nil, time.Second)
	if err == nil {
		t.Fatal("expected RunTLS to fail closed when tlsConfig has no certificate configured")
	}
}

// --- N: no certificate/private-key bytes are ever logged. ---

func TestRunTLSNeverLogsCertificateOrKeyMaterial(t *testing.T) {
	bundle := generateTestCertBundle(t, "localhost")
	tlsConfig, err := ServerTLSConfig(bundle.certFile, bundle.keyFile)
	if err != nil {
		t.Fatal(err)
	}
	var logBuf strings.Builder
	logger := slog.New(slog.NewTextHandler(&logBuf, nil))
	r := &Readiness{}
	r.SetReady()

	done := make(chan error, 1)
	go func() {
		done <- RunTLS(context.Background(), logger, "127.0.0.1:0", Handler(r), tlsConfig, 2*time.Second)
	}()
	time.Sleep(50 * time.Millisecond)
	if err := syscall.Kill(syscall.Getpid(), syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}

	logged := logBuf.String()
	for _, marker := range []string{"BEGIN CERTIFICATE", "BEGIN EC PRIVATE KEY", "PRIVATE KEY"} {
		if strings.Contains(logged, marker) {
			t.Fatalf("log output contains forbidden marker %q:\n%s", marker, logged)
		}
	}
	certBytes, err := os.ReadFile(bundle.certFile)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(logged, string(certBytes)) {
		t.Fatal("log output contains the raw certificate file content")
	}
}
