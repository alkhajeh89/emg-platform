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
package main

import (
	"context"
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

	readiness := &lifecycle.Readiness{}
	mux := http.NewServeMux()
	lifecycle.RegisterRoutes(mux, readiness)
	rpcServer.RegisterRoutes(mux)

	// Startup validation above already fail-closed on any misconfiguration
	// or construction failure -- reaching here means the signer, verifier,
	// and RPC server are all known-good, so readiness may now be true.
	readiness.SetReady()
	logger.Info("recovery-signer: ready", "key_version", cfg.keyVersion, "algorithm", string(cfg.algorithm))

	return lifecycle.Run(ctx, logger, cfg.listenAddr, mux, shutdownTimeout)
}
