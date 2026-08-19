package lifecycle

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os/signal"
	"syscall"
	"time"
)

// ErrTLSFilePathsRequired means ServerTLSConfig was called with an empty
// certificate or key file path. Both are mandatory -- there is no
// fallback certificate, no embedded default, and no path this function
// will infer on the caller's behalf.
var ErrTLSFilePathsRequired = errors.New("lifecycle: TLS certificate and key file paths are both required")

// ServerTLSConfig loads a certificate/key pair from the given file paths
// and returns a minimal *tls.Config suitable for RunTLS: exactly one
// server certificate and a minimum negotiated protocol version of TLS
// 1.2, nothing else configured. It never accepts certificate or key
// material inline, only file paths supplied by the caller's own runtime
// configuration (in production, a Kubernetes Secret volume mount -- see
// infra/kubernetes/base/recovery-signer.yaml) -- no material is ever
// committed to this repository, embedded in this package, or read from a
// hardcoded location. A missing file, an unreadable file, a malformed
// certificate, or a key that does not match the certificate all fail
// here, synchronously, before the caller can treat startup as successful.
func ServerTLSConfig(certFile, keyFile string) (*tls.Config, error) {
	if certFile == "" || keyFile == "" {
		return nil, ErrTLSFilePathsRequired
	}
	cert, err := tls.LoadX509KeyPair(certFile, keyFile)
	if err != nil {
		return nil, fmt.Errorf("lifecycle: load TLS certificate/key pair: %w", err)
	}
	return &tls.Config{
		Certificates: []tls.Certificate{cert},
		MinVersion:   tls.VersionTLS12,
	}, nil
}

// RunTLS is the TLS-serving counterpart to Run: it starts an HTTPS server
// on addr using tlsConfig (see ServerTLSConfig), with the same bounded
// graceful-shutdown/signal-handling behavior Run already provides. There
// is no plaintext fallback anywhere in this function -- if tlsConfig has
// no certificate configured, the underlying ListenAndServeTLS call fails
// closed immediately, exactly as an unresolvable startup error, never as
// a silent downgrade to plaintext.
//
// This is a small, deliberately duplicated sibling to Run rather than a
// refactor of it, matching this codebase's established preference (see
// rotationcommit/genesis.go's relationship to the frozen
// buildCommittedPayload) for duplicating a small amount of already-tested
// logic over restructuring a shared function multiple binaries and their
// own existing tests (TestRunGracefulShutdownOnSignal,
// TestRunReturnsErrorOnListenFailure) already depend on.
func RunTLS(ctx context.Context, logger *slog.Logger, addr string, handler http.Handler, tlsConfig *tls.Config, shutdownTimeout time.Duration) error {
	server := &http.Server{Addr: addr, Handler: handler, TLSConfig: tlsConfig}

	signalCtx, stop := signal.NotifyContext(ctx, syscall.SIGTERM, syscall.SIGINT)
	defer stop()

	serveErr := make(chan error, 1)
	go func() {
		logger.Info("lifecycle: listening (TLS)", "addr", addr)
		// Empty certFile/keyFile arguments: server.TLSConfig.Certificates is
		// already populated (ServerTLSConfig), which is the documented
		// net/http signal to use the pre-loaded configuration instead of
		// reading from disk a second time.
		err := server.ListenAndServeTLS("", "")
		if errors.Is(err, http.ErrServerClosed) {
			serveErr <- nil
			return
		}
		serveErr <- err
	}()

	select {
	case err := <-serveErr:
		if err != nil {
			return fmt.Errorf("lifecycle: TLS server failed: %w", err)
		}
		return nil
	case <-signalCtx.Done():
		logger.Info("lifecycle: shutdown signal received, draining", "timeout", shutdownTimeout)
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("lifecycle: graceful shutdown did not complete within %s: %w", shutdownTimeout, err)
	}
	<-serveErr
	logger.Info("lifecycle: shutdown complete")
	return nil
}
