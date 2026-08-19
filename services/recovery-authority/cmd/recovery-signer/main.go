// Command recovery-signer is the production Recovery Authority signing
// service (ADR-045 §4/§5). It holds the ONLY credential in this codebase
// capable of Cloud KMS AsymmetricSign, deployed as its own process so
// that a compromise of the Recovery Authority authority/witness runtime
// (cmd/recovery-authority) cannot reach signing capability, and vice
// versa (S5 process-role analysis; see
// internal/authority/signerrpc's package doc for why this is a separate
// process, not merely a separate credential in the same process).
//
// It never mutates Spanner, never administers GCS, never administers
// Cloud KMS keys, and exposes exactly two authenticated RPCs
// (signerrpc.Server: ActiveKeyID, SignCommittedDigest) plus health/
// readiness endpoints. No production KMS key, IAM binding, or GCP
// resource is created by running this binary -- it only invokes
// AsymmetricSign against an already-provisioned, already-authorized
// CryptoKeyVersion supplied via configuration.
//
// It serves natively over TLS (lifecycle.RunTLS) by default -- a
// certificate/key file path pair is mandatory startup configuration
// unless RECOVERY_SIGNER_ALLOW_INSECURE=true, which this binary logs
// loudly and which must never be set in production (the corresponding
// symmetric requirement already exists client-side in
// signerrpc.NewClient). Certificate/key material is never embedded in
// this binary or committed to this repository -- only file paths,
// resolved at runtime against whatever volume mount the deployment
// supplies (see infra/kubernetes/base/recovery-signer.yaml).
package main

import (
	"context"
	"crypto/tls"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"time"

	kms "cloud.google.com/go/kms/apiv1"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/kmssigner"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/lifecycle"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/runtimeconfig"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/signerrpc"
)

const shutdownTimeout = 20 * time.Second

type config struct {
	listenAddr          string
	keyVersion          string
	algorithm           keypinning.Algorithm
	serviceAudience     string
	allowedCallerEmails []string
	allowInsecure       bool
	tlsCertFile         string
	tlsKeyFile          string
}

func loadConfig() (config, error) {
	var cfg config
	var err error

	if cfg.listenAddr, err = runtimeconfig.RequireString("RECOVERY_SIGNER_LISTEN_ADDR"); err != nil {
		return config{}, err
	}
	if cfg.keyVersion, err = runtimeconfig.RequireStringMatching(
		"RECOVERY_SIGNER_KEY_VERSION", runtimeconfig.CryptoKeyVersionPattern, "Cloud KMS CryptoKeyVersion resource name",
	); err != nil {
		return config{}, err
	}
	algorithmValue, err := runtimeconfig.RequireString("RECOVERY_SIGNER_ALGORITHM")
	if err != nil {
		return config{}, err
	}
	cfg.algorithm = keypinning.Algorithm(algorithmValue)
	if !cfg.algorithm.Supported() {
		return config{}, fmt.Errorf("RECOVERY_SIGNER_ALGORITHM=%q is not a supported algorithm", algorithmValue)
	}
	if cfg.serviceAudience, err = runtimeconfig.RequireString("RECOVERY_SIGNER_SERVICE_AUDIENCE"); err != nil {
		return config{}, err
	}
	if cfg.allowedCallerEmails, err = runtimeconfig.RequireStringList("RECOVERY_SIGNER_ALLOWED_CALLER_EMAILS"); err != nil {
		return config{}, err
	}
	if cfg.allowInsecure, err = runtimeconfig.OptionalBool("RECOVERY_SIGNER_ALLOW_INSECURE", false); err != nil {
		return config{}, err
	}
	// TLS is mandatory unless the caller has explicitly opted into
	// RECOVERY_SIGNER_ALLOW_INSECURE=true (non-production, local-development
	// use only -- see the loud warning logged below when it is set). This
	// reuses the existing allowInsecure toggle rather than introducing a
	// second, parallel "skip security" flag: allowInsecure already governs
	// the equivalent decision on the client side (signerrpc.NewClient), and
	// giving the server its own separate switch would let the two configs
	// disagree with each other by accident.
	if !cfg.allowInsecure {
		if cfg.tlsCertFile, err = runtimeconfig.RequireString("RECOVERY_SIGNER_TLS_CERT_FILE"); err != nil {
			return config{}, fmt.Errorf("TLS is required unless RECOVERY_SIGNER_ALLOW_INSECURE=true: %w", err)
		}
		if cfg.tlsKeyFile, err = runtimeconfig.RequireString("RECOVERY_SIGNER_TLS_KEY_FILE"); err != nil {
			return config{}, fmt.Errorf("TLS is required unless RECOVERY_SIGNER_ALLOW_INSECURE=true: %w", err)
		}
	}
	return cfg, nil
}

func main() {
	logger := lifecycle.NewLogger()
	if err := run(logger); err != nil {
		logger.Error("recovery-signer: fatal startup or runtime error", "error", err)
		os.Exit(1)
	}
}

func run(logger *slog.Logger) error {
	cfg, err := loadConfig()
	if err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	if cfg.allowInsecure {
		logger.Warn("recovery-signer: RECOVERY_SIGNER_ALLOW_INSECURE=true -- this configuration must never be used in production")
	}

	ctx := context.Background()

	// The ONLY Cloud KMS client this binary ever constructs. It is
	// authenticated via Application Default Credentials / Workload
	// Identity Federation -- no credential file path is read anywhere in
	// this file, and kms.NewKeyManagementClient never accepts a static
	// key by default.
	kmsClient, err := kms.NewKeyManagementClient(ctx)
	if err != nil {
		return fmt.Errorf("construct Cloud KMS client: %w", err)
	}
	defer kmsClient.Close()

	signer, err := kmssigner.New(kmsClient, cfg.keyVersion, cfg.algorithm)
	if err != nil {
		return fmt.Errorf("construct signer (fail-closed on misconfiguration): %w", err)
	}

	verifier, err := signerrpc.NewGoogleIDTokenVerifier(cfg.serviceAudience, cfg.allowedCallerEmails)
	if err != nil {
		return fmt.Errorf("construct caller identity verifier: %w", err)
	}

	rpcServer, err := signerrpc.NewServer(signer, verifier, logger)
	if err != nil {
		return fmt.Errorf("construct signing RPC server: %w", err)
	}

	// TLS configuration is resolved (and, on any failure, fails startup)
	// BEFORE readiness is ever set true -- a certificate/key problem must
	// never be observable as "ready" for even one probe interval.
	var tlsConfig *tls.Config
	if !cfg.allowInsecure {
		tlsConfig, err = lifecycle.ServerTLSConfig(cfg.tlsCertFile, cfg.tlsKeyFile)
		if err != nil {
			return fmt.Errorf("TLS configuration (fail-closed): %w", err)
		}
	}

	readiness := &lifecycle.Readiness{}
	mux := http.NewServeMux()
	lifecycle.RegisterRoutes(mux, readiness)
	rpcServer.RegisterRoutes(mux)

	// Startup validation above already fail-closed on any misconfiguration
	// or construction failure -- reaching here means the signer, verifier,
	// RPC server, and (unless allowInsecure) TLS configuration are all
	// known-good, so readiness may now be true.
	readiness.SetReady()
	logger.Info("recovery-signer: ready", "key_version", cfg.keyVersion, "algorithm", string(cfg.algorithm), "tls", !cfg.allowInsecure)

	if cfg.allowInsecure {
		return lifecycle.Run(ctx, logger, cfg.listenAddr, mux, shutdownTimeout)
	}
	return lifecycle.RunTLS(ctx, logger, cfg.listenAddr, mux, tlsConfig, shutdownTimeout)
}
