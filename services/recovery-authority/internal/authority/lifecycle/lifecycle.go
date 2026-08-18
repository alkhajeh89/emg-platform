// Package lifecycle provides the shared production-service lifecycle
// shell both Recovery Authority binaries use: a readiness flag that
// starts false and is only ever set true after mandatory startup
// validation succeeds, a liveness endpoint that reports process health
// only (never semantic readiness), and graceful SIGTERM/SIGINT shutdown
// with a bounded deadline.
package lifecycle

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"sync/atomic"
	"syscall"
	"time"
)

// Readiness is a thread-safe, monotonic-until-reset readiness flag.
// Starts false. Production code sets it true exactly once, after every
// mandatory dependency/configuration check has already succeeded --
// never before.
type Readiness struct {
	ready atomic.Bool
}

func (r *Readiness) SetReady()     { r.ready.Store(true) }
func (r *Readiness) SetNotReady()  { r.ready.Store(false) }
func (r *Readiness) IsReady() bool { return r.ready.Load() }

// Handler returns a health-check http.Handler exposing:
//   - GET /healthz -- liveness only: 200 whenever the process can answer
//     HTTP at all. It never reports semantic readiness (S5 Phase 5: "liveness
//     that does not falsely report semantic readiness").
//   - GET /readyz -- 200 only once readiness.IsReady() is true, 503
//     otherwise.
func Handler(readiness *Readiness) http.Handler {
	mux := http.NewServeMux()
	RegisterRoutes(mux, readiness)
	return mux
}

// RegisterRoutes mounts /healthz and /readyz onto a caller-supplied mux,
// so a binary that also serves its own routes (e.g. signerrpc.Server) can
// combine them onto one listener without path-pattern duplication.
func RegisterRoutes(mux *http.ServeMux, readiness *Readiness) {
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, _ *http.Request) {
		if !readiness.IsReady() {
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = w.Write([]byte("not ready"))
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ready"))
	})
}

// Run starts an HTTP server on addr serving handler, blocks until a
// SIGTERM/SIGINT is received or the server fails, then shuts down
// gracefully within shutdownTimeout. It returns a non-nil error only for
// a genuine startup or shutdown failure -- a clean SIGTERM/SIGINT-driven
// shutdown returns nil, and main is expected to os.Exit(1) itself on a
// non-nil return (Run never calls os.Exit).
//
// There is no retry loop here: a failed ListenAndServe is reported once
// and Run returns -- masking a fail-closed startup failure behind a
// retry loop is explicitly prohibited (S5 Phase 5).
func Run(ctx context.Context, logger *slog.Logger, addr string, handler http.Handler, shutdownTimeout time.Duration) error {
	server := &http.Server{Addr: addr, Handler: handler}

	signalCtx, stop := signal.NotifyContext(ctx, syscall.SIGTERM, syscall.SIGINT)
	defer stop()

	serveErr := make(chan error, 1)
	go func() {
		logger.Info("lifecycle: listening", "addr", addr)
		err := server.ListenAndServe()
		if errors.Is(err, http.ErrServerClosed) {
			serveErr <- nil
			return
		}
		serveErr <- err
	}()

	select {
	case err := <-serveErr:
		if err != nil {
			return fmt.Errorf("lifecycle: server failed: %w", err)
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
	// Drain the goroutine's result so it never leaks, but the shutdown
	// outcome above is authoritative.
	<-serveErr
	logger.Info("lifecycle: shutdown complete")
	return nil
}

// NewLogger returns the structured logger every Recovery Authority binary
// uses: JSON, no secret fields ever attached by this package itself.
func NewLogger() *slog.Logger {
	return slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
}
