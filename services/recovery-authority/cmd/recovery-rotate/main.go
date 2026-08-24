// Command recovery-rotate is the production entry point for ONE governed,
// ordinary (non-genesis) Recovery Authority rotation (ADR-044 §17 items 1
// and 3's closure, S8). It composes the real S2 raw Spanner Commit boundary
// (the same spannerpb.SpannerClient stub spannercommit already dials), the
// real GCS witness adapter (gcswitness), the real S3+ signing boundary (a
// remote signerrpc.Client, exactly as cmd/recovery-authority already uses
// for verification), and the new S8 PREPARE/orchestration layer
// (rotationprepare, rotationexecute) to perform exactly one rotation and
// exit.
//
// AUTHORIZATION BOUNDARY -- READ BEFORE DEPLOYING OR INVOKING.
//
// This repository has no established caller-authentication contract for a
// network-facing administrative mutation endpoint: verification
// (cmd/recovery-authority's POST /v1/verify) is deliberately unprivileged
// (ADR-045 §5, "public verification is independent of signing permission"),
// and signerrpc's Google-ID-token bearer scheme authenticates a specific
// known WORKLOAD (recovery-authority calling recovery-signer), not an
// arbitrary human or service requesting an arbitrary rotation. Genesis
// itself (bootstrap.ExecuteGenesis) has never been exposed over any network
// endpoint either -- every real genesis performed by this repository's own
// qualification work invoked it as a direct Go call from an operator-run
// binary, with dual control enforced entirely in-process, before
// ExecuteGenesis was ever reached (bootstrap.NewGenesisRequest +
// bootstrap.Approval).
//
// Per this task's own explicit instruction, this binary does NOT invent a
// new network authentication/authorization contract to fill that gap. It is
// a CLI, not an HTTP service: its authorization boundary is entirely the
// invoking operator's own Google Cloud credentials (Application Default
// Credentials / workload identity) and whatever operational access control
// (who may exec into this binary's deployment, who may run it locally
// against a real project) the deploying environment enforces -- the same
// boundary this repository's own iam/manifest.json already models for the
// "recovery-authority-runtime" and "recovery-bootstrap-deployment"
// principals.
//
// UNLIKE GENESIS, ORDINARY ROTATION HAS NO ADR-DEFINED DUAL-CONTROL
// REQUIREMENT. bootstrap.GenesisRequest requires two independent
// Approval values before ExecuteGenesis will run; no equivalent
// Approval/dual-control mechanism exists in ADR-044, ADR-045, or anywhere
// in this codebase for an ordinary rotation. This binary does not invent
// one. Whether ordinary rotations require dual control, single-operator
// authority, or some other governance model is an open question for human
// governance review (see the accompanying Track G decision package) --
// this binary intentionally leaves it open rather than silently deciding it
// by omission.
package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"time"

	"cloud.google.com/go/spanner/apiv1/spannerpb"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/lifecycle"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationexecute"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationprepare"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/runtimeconfig"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/signerrpc"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/spannercommit"
)

type config struct {
	spannerDatabase     string
	witnessBucket       string
	signerEndpoint      string
	signerAudience      string
	signerCAFile        string
	allowInsecure       bool
	environmentID       string
	authorityEpoch      string
	resourceIncarnation string
	operationID         string
	expectedRevision    uint64
	predecessorDigest   string
	candidateBytesHex   string
}

func loadConfig() (config, error) {
	var cfg config
	var err error
	if cfg.spannerDatabase, err = runtimeconfig.RequireStringMatching(
		"RECOVERY_ROTATE_SPANNER_DATABASE", runtimeconfig.SpannerDatabasePattern, "Cloud Spanner database resource name",
	); err != nil {
		return config{}, err
	}
	if cfg.witnessBucket, err = runtimeconfig.RequireString("RECOVERY_ROTATE_WITNESS_BUCKET"); err != nil {
		return config{}, err
	}
	if cfg.signerEndpoint, err = runtimeconfig.RequireString("RECOVERY_ROTATE_SIGNER_ENDPOINT"); err != nil {
		return config{}, err
	}
	if cfg.signerAudience, err = runtimeconfig.RequireString("RECOVERY_ROTATE_SIGNER_AUDIENCE"); err != nil {
		return config{}, err
	}
	cfg.signerCAFile = runtimeconfig.OptionalString("RECOVERY_ROTATE_SIGNER_CA_FILE", "")
	if cfg.allowInsecure, err = runtimeconfig.OptionalBool("RECOVERY_ROTATE_ALLOW_INSECURE", false); err != nil {
		return config{}, err
	}
	if cfg.environmentID, err = runtimeconfig.RequireString("RECOVERY_ROTATE_ENVIRONMENT_ID"); err != nil {
		return config{}, err
	}
	if cfg.authorityEpoch, err = runtimeconfig.RequireString("RECOVERY_ROTATE_AUTHORITY_EPOCH"); err != nil {
		return config{}, err
	}
	if cfg.resourceIncarnation, err = runtimeconfig.RequireString("RECOVERY_ROTATE_RESOURCE_INCARNATION"); err != nil {
		return config{}, err
	}
	if cfg.operationID, err = runtimeconfig.RequireString("RECOVERY_ROTATE_OPERATION_ID"); err != nil {
		return config{}, err
	}
	expectedRevisionStr, err := runtimeconfig.RequireString("RECOVERY_ROTATE_EXPECTED_REVISION")
	if err != nil {
		return config{}, err
	}
	if _, err := fmt.Sscanf(expectedRevisionStr, "%d", &cfg.expectedRevision); err != nil {
		return config{}, fmt.Errorf("RECOVERY_ROTATE_EXPECTED_REVISION: %w", err)
	}
	if cfg.predecessorDigest, err = runtimeconfig.RequireString("RECOVERY_ROTATE_PREDECESSOR_DIGEST_HEX"); err != nil {
		return config{}, err
	}
	if cfg.candidateBytesHex, err = runtimeconfig.RequireString("RECOVERY_ROTATE_CANDIDATE_BYTES_HEX"); err != nil {
		return config{}, err
	}
	return cfg, nil
}

func main() {
	logger := lifecycle.NewLogger()
	if err := run(logger); err != nil {
		logger.Error("recovery-rotate: fatal error", "error", err)
		os.Exit(1)
	}
}

func run(logger *slog.Logger) error {
	cfg, err := loadConfig()
	if err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	if cfg.allowInsecure {
		logger.Warn("recovery-rotate: RECOVERY_ROTATE_ALLOW_INSECURE=true -- this configuration must never be used in production")
	}

	candidate, err := buildCandidate(cfg)
	if err != nil {
		return fmt.Errorf("candidate: %w", err)
	}

	ctx := context.Background()
	deps, closeFn, err := compose(ctx, cfg)
	if err != nil {
		return fmt.Errorf("dependency composition (fail-closed on misconfiguration): %w", err)
	}
	defer closeFn()

	result, err := rotationexecute.ExecuteRotation(ctx, deps, candidate)
	logger.Info("recovery-rotate: result",
		"outcome", result.Outcome.String(),
		"epoch_state", result.EpochState.String(),
		"new_epoch_required", result.EpochState.NewEpochRequired(),
		"witness_create", result.WitnessCreate.String(),
		"operation_id", result.OperationID,
		"session_name", result.SessionName,
	)
	if err != nil {
		return err
	}
	if result.Outcome != rotationexecute.OutcomeCompleted {
		return fmt.Errorf("recovery-rotate: rotation did not complete: outcome=%s", result.Outcome)
	}
	return nil
}

func buildCandidate(cfg config) (rotationprepare.Candidate, error) {
	env, err := protocol.NewEnvironmentID(cfg.environmentID)
	if err != nil {
		return rotationprepare.Candidate{}, fmt.Errorf("environment_id: %w", err)
	}
	epochID, err := protocol.NewAuthorityEpoch(cfg.authorityEpoch)
	if err != nil {
		return rotationprepare.Candidate{}, fmt.Errorf("authority_epoch: %w", err)
	}
	resource, err := protocol.NewResourceIncarnationID(cfg.resourceIncarnation)
	if err != nil {
		return rotationprepare.Candidate{}, fmt.Errorf("resource_incarnation: %w", err)
	}
	operationID, err := protocol.NewOperationID(cfg.operationID)
	if err != nil {
		return rotationprepare.Candidate{}, fmt.Errorf("operation_id: %w", err)
	}
	predecessorDigest, err := protocol.ParseDigest32(cfg.predecessorDigest)
	if err != nil {
		return rotationprepare.Candidate{}, fmt.Errorf("predecessor_digest_hex: %w", err)
	}
	candidateBytes, err := hex.DecodeString(cfg.candidateBytesHex)
	if err != nil {
		return rotationprepare.Candidate{}, fmt.Errorf("candidate_bytes_hex: %w", err)
	}
	return rotationprepare.Candidate{
		EnvironmentID:       env,
		AuthorityEpoch:      epochID,
		ResourceIncarnation: resource,
		OperationID:         operationID,
		ExpectedRevision:    protocol.NewRevisionNumber(cfg.expectedRevision),
		PredecessorDigest:   predecessorDigest,
		CandidateBytes:      candidateBytes,
		PreparedBytes:       candidateBytes,
	}, nil
}

// rawSpannerConn is the only Spanner connection this binary ever opens --
// the same spannercommit.Dial (real TLS + ADC, no static keys) every other
// production Spanner boundary in this codebase already uses. It is wrapped
// directly as the raw generated spannerpb.SpannerClient stub, which already
// satisfies both rotationprepare.RotationSpannerClient and
// rotationcommit.RawCommitClient (rotationexecute.SpannerClient's exact
// embedding) -- no second connection type, no GAX/high-level transaction
// helper, exactly as spannercommit's own package doc requires.
func compose(ctx context.Context, cfg config) (rotationexecute.Dependencies, func(), error) {
	conn, err := spannercommit.Dial(ctx)
	if err != nil {
		return rotationexecute.Dependencies{}, nil, fmt.Errorf("dial Spanner: %w", err)
	}
	rawClient := spannerpb.NewSpannerClient(conn)

	storageClient, err := gcswitness.NewClient(ctx)
	if err != nil {
		conn.Close()
		return rotationexecute.Dependencies{}, nil, fmt.Errorf("construct GCS client: %w", err)
	}
	witnessAdapter := gcswitness.New(storageClient, cfg.witnessBucket)

	tokenSource, err := signerrpc.NewGoogleIDTokenSource(ctx, cfg.signerAudience)
	if err != nil {
		conn.Close()
		return rotationexecute.Dependencies{}, nil, fmt.Errorf("construct signer ID token source: %w", err)
	}
	signerHTTPClient, err := newSignerHTTPClient(cfg.signerCAFile)
	if err != nil {
		conn.Close()
		return rotationexecute.Dependencies{}, nil, fmt.Errorf("construct signer TLS trust configuration (fail-closed): %w", err)
	}
	remoteSigner, err := signerrpc.NewClient(signerHTTPClient, cfg.signerEndpoint, tokenSource, cfg.allowInsecure)
	if err != nil {
		conn.Close()
		return rotationexecute.Dependencies{}, nil, fmt.Errorf("construct remote signer client: %w", err)
	}

	deps := rotationexecute.Dependencies{
		Spanner:         rawClient,
		SpannerDatabase: cfg.spannerDatabase,
		Witness:         witnessAdapter,
		Signer:          remoteSigner,
	}
	return deps, func() { conn.Close() }, nil
}

// newSignerHTTPClient is identical in behavior and reasoning to
// cmd/recovery-authority's own function of the same name (see that
// binary's doc comment for the full trust-model explanation) --
// deliberately duplicated rather than shared across cmd/ binaries, matching
// this codebase's established preference for small, security-relevant
// duplication over a shared dependency between independently-deployed
// processes.
func newSignerHTTPClient(caFile string) (*http.Client, error) {
	if caFile == "" {
		return &http.Client{Timeout: 10 * time.Second}, nil
	}
	pemBytes, err := os.ReadFile(caFile)
	if err != nil {
		return nil, fmt.Errorf("read signer CA file: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(pemBytes) {
		return nil, fmt.Errorf("signer CA file %q contains no usable certificate", caFile)
	}
	return &http.Client{
		Timeout: 10 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{
				RootCAs:    pool,
				MinVersion: tls.VersionTLS12,
			},
		},
	}, nil
}
