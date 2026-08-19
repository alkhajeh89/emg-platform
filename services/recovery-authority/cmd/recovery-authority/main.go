// Command recovery-authority is the production Recovery Authority
// authority/witness runtime (ADR-044 §5/§6, ADR-044 §15's
// "recovery-authority-runtime" principal). It composes the S2 raw
// Spanner Commit boundary (spannercommit), the GCS witness adapter
// (gcswitness), and -- for independent historical verification -- the S3
// pinning/compromise/verifier stack (keypinning, compromiseledger,
// kmsverifier), together with a remote signerrpc.Client standing in for
// direct signing capability.
//
// It holds NO Cloud KMS credential and imports no KMS package at all
// (enforced by this package's boundary test): signing, when eventually
// wired to a live mutation path, is only ever reachable through the
// separately-deployed recovery-signer process over signerrpc (ADR-045
// §4/§5's administrative independence, S5 process-role analysis).
//
// SCOPE NOTE (S5 Phase 2 classification): this binary composes and holds
// a live spannercommit.Client and signerrpc.Client, proving the
// production dependency graph wires correctly and holds exactly the
// right (and no more) capability -- but exposes no HTTP endpoint that
// triggers a Spanner Commit yet. Doing so would additionally require
// production Spanner-mutation-construction logic (building the
// authority_head/authority_transition_history Mutation protos from a
// caller's requested rotation) that does not exist anywhere in this
// codebase today -- only a test/emulator-only twin does
// (conformance/spanneradapter.TransitionMutations, itself documented as
// "necessarily new harness code... [that] does not exist in production").
// ADR-044 itself describes that PREPARE/mutation-construction
// orchestration layer as deliberately not yet designed. Building it now
// would mean inventing new, unreviewed production data-plane logic under
// the guise of "composition" -- exactly the kind of scope this task's own
// instructions guard against. It is intentionally left as a distinct,
// separately-scoped follow-on task, not begun here.
//
// What this binary DOES fully implement end to end, using only already-
// exported, already-tested S1-S3 primitives: read-only historical
// verification of an existing witness record (the "recovery-verification-
// read" S4 principal), exposed as POST /v1/verify.
package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/compromiseledger"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/kmsverifier"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/lifecycle"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/recovery"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/runtimeconfig"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/signerrpc"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/spannercommit"
)

const shutdownTimeout = 20 * time.Second

type config struct {
	listenAddr               string
	environmentID            string
	spannerDatabase          string
	witnessBucket            string
	signerEndpoint           string
	signerAudience           string
	signerCAFile             string
	approvedSigningCryptoKey string
	pinnedKeyStoreDir        string
	compromiseLedgerFile     string
	allowInsecure            bool
}

func loadConfig() (config, error) {
	var cfg config
	var err error

	if cfg.listenAddr, err = runtimeconfig.RequireString("RECOVERY_AUTHORITY_LISTEN_ADDR"); err != nil {
		return config{}, err
	}
	if cfg.environmentID, err = runtimeconfig.RequireString("RECOVERY_AUTHORITY_ENVIRONMENT_ID"); err != nil {
		return config{}, err
	}
	if _, err = protocol.NewEnvironmentID(cfg.environmentID); err != nil {
		return config{}, fmt.Errorf("RECOVERY_AUTHORITY_ENVIRONMENT_ID: %w", err)
	}
	if cfg.spannerDatabase, err = runtimeconfig.RequireStringMatching(
		"RECOVERY_AUTHORITY_SPANNER_DATABASE", runtimeconfig.SpannerDatabasePattern, "Cloud Spanner database resource name",
	); err != nil {
		return config{}, err
	}
	if cfg.witnessBucket, err = runtimeconfig.RequireString("RECOVERY_AUTHORITY_WITNESS_BUCKET"); err != nil {
		return config{}, err
	}
	if cfg.signerEndpoint, err = runtimeconfig.RequireString("RECOVERY_AUTHORITY_SIGNER_ENDPOINT"); err != nil {
		return config{}, err
	}
	if cfg.signerAudience, err = runtimeconfig.RequireString("RECOVERY_AUTHORITY_SIGNER_AUDIENCE"); err != nil {
		return config{}, err
	}
	// Optional: an explicit CA certificate file to trust for the signer
	// TLS connection, for deployments whose signer certificate is not
	// issued by a publicly-trusted CA already in the platform's default
	// trust store. Empty (the default) means: trust only the platform's
	// own default CA pool, exactly as any ordinary Go HTTPS client would.
	// This is never a security-critical value in the RequireString sense
	// -- its absence does not weaken verification, it only narrows which
	// already-legitimate certificate authorities are accepted.
	cfg.signerCAFile = runtimeconfig.OptionalString("RECOVERY_AUTHORITY_SIGNER_CA_FILE", "")
	if cfg.approvedSigningCryptoKey, err = runtimeconfig.RequireStringMatching(
		"RECOVERY_AUTHORITY_APPROVED_SIGNING_CRYPTO_KEY", runtimeconfig.CryptoKeyPattern, "Cloud KMS CryptoKey resource name",
	); err != nil {
		return config{}, err
	}
	if cfg.pinnedKeyStoreDir, err = runtimeconfig.RequireString("RECOVERY_AUTHORITY_PINNED_KEY_STORE_DIR"); err != nil {
		return config{}, err
	}
	if cfg.compromiseLedgerFile, err = runtimeconfig.RequireString("RECOVERY_AUTHORITY_COMPROMISE_LEDGER_FILE"); err != nil {
		return config{}, err
	}
	if cfg.allowInsecure, err = runtimeconfig.OptionalBool("RECOVERY_AUTHORITY_ALLOW_INSECURE", false); err != nil {
		return config{}, err
	}
	return cfg, nil
}

// runtime holds every composed production dependency. Its shape is the
// direct evidence for S5 Phase 3's composition proofs: the only Spanner
// type is spannercommit.Client (never conformance/spanneradapter), the
// only signing-adjacent type is a signerrpc.Client (never kmssigner.Signer
// or conformance/localsigner), and verification is wired from keypinning
// + compromiseledger + kmsverifier exactly as S3 defines.
type runtime struct {
	environment    protocol.EnvironmentID
	spannerClient  *spannercommit.Client
	witnessAdapter *gcswitness.Adapter
	remoteSigner   *signerrpc.Client
	verifier       *kmsverifier.Verifier
	lineage        recovery.ApprovedSigningLineage
	logger         *slog.Logger
}

func main() {
	logger := lifecycle.NewLogger()
	if err := run(logger); err != nil {
		logger.Error("recovery-authority: fatal startup or runtime error", "error", err)
		os.Exit(1)
	}
}

func run(logger *slog.Logger) error {
	cfg, err := loadConfig()
	if err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	if cfg.allowInsecure {
		logger.Warn("recovery-authority: RECOVERY_AUTHORITY_ALLOW_INSECURE=true -- this configuration must never be used in production")
	}

	ctx := context.Background()
	rt, err := compose(ctx, cfg, logger)
	if err != nil {
		return fmt.Errorf("dependency composition (fail-closed on misconfiguration): %w", err)
	}

	readiness := &lifecycle.Readiness{}
	mux := http.NewServeMux()
	lifecycle.RegisterRoutes(mux, readiness)
	mux.HandleFunc("POST /v1/verify", rt.handleVerify)

	readiness.SetReady()
	logger.Info("recovery-authority: ready",
		"environment", cfg.environmentID,
		"spanner_database", cfg.spannerDatabase,
		"witness_bucket", cfg.witnessBucket,
	)

	return lifecycle.Run(ctx, logger, cfg.listenAddr, mux, shutdownTimeout)
}

func compose(ctx context.Context, cfg config, logger *slog.Logger) (*runtime, error) {
	environment, err := protocol.NewEnvironmentID(cfg.environmentID)
	if err != nil {
		return nil, err
	}

	// The ONLY Spanner client this binary ever constructs -- always the
	// S2 raw Commit boundary, never the high-level client or the
	// test-only conformance/spanneradapter.
	spannerConn, err := spannercommit.Dial(ctx)
	if err != nil {
		return nil, fmt.Errorf("dial Spanner: %w", err)
	}
	spannerClient := spannercommit.New(spannerConn)

	storageClient, err := gcswitness.NewClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("construct GCS client: %w", err)
	}
	witnessAdapter := gcswitness.New(storageClient, cfg.witnessBucket)

	tokenSource, err := signerrpc.NewGoogleIDTokenSource(ctx, cfg.signerAudience)
	if err != nil {
		return nil, fmt.Errorf("construct signer ID token source: %w", err)
	}
	signerHTTPClient, err := newSignerHTTPClient(cfg.signerCAFile)
	if err != nil {
		return nil, fmt.Errorf("construct signer TLS trust configuration (fail-closed): %w", err)
	}
	remoteSigner, err := signerrpc.NewClient(signerHTTPClient, cfg.signerEndpoint, tokenSource, cfg.allowInsecure)
	if err != nil {
		return nil, fmt.Errorf("construct remote signer client: %w", err)
	}

	lineage, err := keypinning.CryptoKeyLineage(cfg.approvedSigningCryptoKey)
	if err != nil {
		return nil, fmt.Errorf("construct approved signing lineage: %w", err)
	}
	pinStore, err := keypinning.NewFileStore(cfg.pinnedKeyStoreDir)
	if err != nil {
		return nil, fmt.Errorf("construct pinned-key store: %w", err)
	}
	ledger, err := compromiseledger.NewFileLedger(cfg.compromiseLedgerFile)
	if err != nil {
		return nil, fmt.Errorf("construct compromise ledger: %w", err)
	}
	verifier, err := kmsverifier.New(pinStore, ledger)
	if err != nil {
		return nil, fmt.Errorf("construct verifier: %w", err)
	}

	return &runtime{
		environment:    environment,
		spannerClient:  spannerClient,
		witnessAdapter: witnessAdapter,
		remoteSigner:   remoteSigner,
		verifier:       verifier,
		lineage:        lineage,
		logger:         logger,
	}, nil
}

// verifyRequest deliberately does NOT include environment_id: which
// environment this process verifies against is this deployment's own
// fixed configuration, never inferred from caller-controlled payload
// data (S5 Phase 2 explicit requirement).
type verifyRequest struct {
	WitnessKey          string `json:"witness_key"`
	AuthorityEpoch      string `json:"authority_epoch"`
	ResourceIncarnation string `json:"resource_incarnation"`
	OperationID         string `json:"operation_id"`
	PredecessorRevision uint64 `json:"predecessor_revision"`
	PredecessorDigest   string `json:"predecessor_digest_hex"`
}

type verifyResponse struct {
	Verified bool   `json:"verified"`
	Reason   string `json:"reason,omitempty"`
}

func (rt *runtime) handleVerify(w http.ResponseWriter, r *http.Request) {
	var req verifyRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, verifyResponse{Verified: false, Reason: "malformed request body"})
		return
	}
	expected, err := rt.buildExpectedBinding(req)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, verifyResponse{Verified: false, Reason: err.Error()})
		return
	}

	raw, err := rt.witnessAdapter.ReadExact(r.Context(), req.WitnessKey)
	if err != nil {
		writeJSON(w, http.StatusNotFound, verifyResponse{Verified: false, Reason: "witness object not found or unreadable"})
		return
	}
	payload, err := protocol.UnmarshalCommittedPayloadJSON(raw)
	if err != nil {
		writeJSON(w, http.StatusUnprocessableEntity, verifyResponse{Verified: false, Reason: "witness object is malformed"})
		return
	}

	if err := recovery.VerifyPersistedCommitted(r.Context(), rt.verifier, payload, expected); err != nil {
		rt.logger.Warn("recovery-authority: verification failed", "witness_key", req.WitnessKey, "error", err)
		writeJSON(w, http.StatusOK, verifyResponse{Verified: false, Reason: err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, verifyResponse{Verified: true})
}

func (rt *runtime) buildExpectedBinding(req verifyRequest) (recovery.ExpectedBinding, error) {
	epoch, err := protocol.NewAuthorityEpoch(req.AuthorityEpoch)
	if err != nil {
		return recovery.ExpectedBinding{}, fmt.Errorf("authority_epoch: %w", err)
	}
	resource, err := protocol.NewResourceIncarnationID(req.ResourceIncarnation)
	if err != nil {
		return recovery.ExpectedBinding{}, fmt.Errorf("resource_incarnation: %w", err)
	}
	operationID, err := protocol.NewOperationID(req.OperationID)
	if err != nil {
		return recovery.ExpectedBinding{}, fmt.Errorf("operation_id: %w", err)
	}
	predecessorDigest, err := protocol.ParseDigest32(req.PredecessorDigest)
	if err != nil {
		return recovery.ExpectedBinding{}, fmt.Errorf("predecessor_digest_hex: %w", err)
	}
	return recovery.ExpectedBinding{
		EnvironmentID:          rt.environment,
		AuthorityEpoch:         epoch,
		ResourceIncarnation:    resource,
		OperationID:            operationID,
		PredecessorRevision:    protocol.NewRevisionNumber(req.PredecessorRevision),
		PredecessorDigest:      predecessorDigest,
		ApprovedSigningLineage: rt.lineage,
	}, nil
}

// newSignerHTTPClient builds the *http.Client used exclusively for calls
// to the remote signer (signerrpc.NewClient's httpClient argument). It
// defines exactly what this process trusts when validating the signer's
// TLS server certificate:
//
//   - if caFile is empty, the platform's own default CA trust store is
//     used, unmodified -- Go's standard library behavior for any ordinary
//     HTTPS client, appropriate when the signer's certificate is issued by
//     a publicly-trusted CA (e.g. a cluster cert-manager configuration
//     using a public ACME issuer);
//   - if caFile is set, ONLY that CA (read from a local file path supplied
//     by this process's own runtime configuration -- never from a request,
//     a response, or any other caller-controlled input) is trusted,
//     appropriate for a private/internal CA;
//   - InsecureSkipVerify is never set anywhere in this function, and
//     ServerName is never overridden -- server-name/SAN verification
//     against the request URL's own hostname is standard net/http/crypto/tls
//     behavior and is left entirely to it, not reimplemented here.
//
// This is one-way TLS (server-authenticated) only. Client authentication
// (which caller is allowed to invoke the signer) is already independently
// enforced, over this same TLS connection, by signerrpc's existing
// Google-signed-ID-token bearer authentication
// (GoogleIDTokenSource/GoogleIDTokenVerifier) -- mutual TLS would add a
// second, redundant caller-identity check without closing any gap that
// mechanism leaves open, so it is deliberately not added here.
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

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
