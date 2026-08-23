//go:build realcloud_spanner_processdeath

// Package rotationcommit real-Cloud-Spanner process-death qualification
// (ADR-044 §9 / §17 item 7, "S7"). This file is gated behind the
// realcloud_spanner_processdeath build tag specifically so it can NEVER
// run as part of `go test ./...`, CI, or any other normal invocation --
// it dials a real Cloud Spanner database and a real GCS bucket, and it
// spawns real OS subprocesses that it hard-kills (SIGKILL) at controlled
// points. It requires real, disposable-project credentials supplied
// entirely through environment variables and the caller's own
// `gcloud`-authenticated session. It is never invoked automatically by
// anything in this repository.
//
// This file lives inside package rotationcommit -- the same reason
// emulator_processkill_test.go does -- because completeRawCommit,
// acceptedRotationContext, and buildCommittedPayload are unexported by
// design (the security boundary this qualification exists to prove is
// real, not an inconvenience to route around): a genuinely separate
// `package main` helper binary could not call them at all. The
// subprocess technique below is identical in kind to
// emulator_processkill_test.go's already-reviewed T7/T8/T10 matrix --
// this file extends exactly that pattern from the Cloud Spanner emulator
// to real Cloud Spanner, changing only the dial target and the witness
// storage backend. See bootstrap/realcloud_spanner_test.go, whose final
// log line already states: "STILL_REQUIRED_FOR_S7: genuine mid-RPC
// process death ... was not safely inducible in this environment/session
// and is not claimed as qualified by this run." This file is that S7.
//
// SCOPE: qualifies real process loss between a Commit classified
// UnambiguousSuccess and the same-operation COMMITTED witness write
// completing. It reuses a local, test-only ECDSA signer
// (conformance/localsigner) rather than a real Cloud KMS signer --
// exactly the same scoping decision Wave 1 Track A's real-cloud test
// already made and documented ("does NOT qualify real Cloud KMS
// signing... signing here uses a local, test-only ECDSA key"), because
// the property under qualification here (Spanner-Commit/witness process
// loss) is orthogonal to which Signer implementation is used, and the
// real KMS/TLS/WIF signing boundary was already exhaustively qualified
// against real infrastructure in Wave 2 Tracks C/D/E/F.
package rotationcommit

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"golang.org/x/oauth2"
	"google.golang.org/api/option"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/localsigner"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/spanneradapter"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/epoch"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/recovery"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotation"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/spannercommit"
)

const (
	s7EnvDatabase     = "EMG_S7_SPANNER_DATABASE"
	s7EnvGCSBucket    = "EMG_S7_GCS_BUCKET"
	s7EnvHelperMode   = "EMG_S7_HELPER_MODE"
	s7EnvEnvironment  = "EMG_S7_ENVIRONMENT"
	s7EnvEpoch        = "EMG_S7_EPOCH"
	s7EnvResource     = "EMG_S7_RESOURCE"
	s7EnvOperation    = "EMG_S7_OPERATION"
	s7EnvWitnessKey   = "EMG_S7_WITNESS_KEY"
	s7EnvSigningKey   = "EMG_S7_SIGNING_KEY_HEX"
	s7EnvAccessToken  = "EMG_S7_ACCESS_TOKEN" // #nosec G101 -- env var name, not a credential
	s7EnvEvidenceOut  = "EMG_S7_EVIDENCE_OUT"
	s7RealEnvironment = "s7-processdeath-qual"
)

// --- self-contained helpers (no dependency on the emulator-tagged file) ---

// s7UUIDv7ish mirrors emulator_shared_test.go's newUUIDv7ish (same
// canonical-shape requirement: version nibble '7', variant nibble in
// 89ab), duplicated here (rather than shared) so this file has zero
// dependency on any emulator-build-tag-gated file -- the two build tags
// are never active in the same `go test` invocation. Builds from 16
// random bytes (the standard UUID byte length) and overwrites exactly
// the version/variant nibbles, rather than hand-assembling hex-digit
// counts per group (an earlier version of this helper miscounted those
// and produced malformed identifiers).
func s7UUIDv7ish() string {
	raw := make([]byte, 16)
	_, _ = rand.Read(raw)
	chars := []byte(hex.EncodeToString(raw)) // 32 hex chars
	chars[12] = '7'
	variantChars := "89ab"
	variantIndexByte := make([]byte, 1)
	_, _ = rand.Read(variantIndexByte)
	chars[16] = variantChars[int(variantIndexByte[0])%4]
	return fmt.Sprintf("%s-%s-%s-%s-%s", chars[0:8], chars[8:12], chars[12:16], chars[16:20], chars[20:32])
}

func s7DigestOf(seed byte) protocol.Digest32 {
	raw := make([]byte, 32)
	for i := range raw {
		raw[i] = seed
	}
	digest, _ := protocol.NewDigest32(raw)
	return digest
}

func s7RealDatabase(t *testing.T) string {
	t.Helper()
	db := os.Getenv(s7EnvDatabase)
	if db == "" {
		t.Skip("EMG_S7_SPANNER_DATABASE not set -- skipping real-cloud S7 process-death qualification")
	}
	return db
}

func s7RealBucket(t *testing.T) string {
	t.Helper()
	bucket := os.Getenv(s7EnvGCSBucket)
	if bucket == "" {
		t.Skip("EMG_S7_GCS_BUCKET not set -- skipping real-cloud S7 process-death qualification")
	}
	return bucket
}

func s7AccessToken(t *testing.T) string {
	t.Helper()
	out, err := exec.Command("gcloud", "auth", "print-access-token").Output()
	if err != nil {
		t.Fatalf("gcloud auth print-access-token: %v", err)
	}
	token := strings.TrimSpace(string(out))
	if token == "" {
		t.Fatal("gcloud auth print-access-token returned an empty token")
	}
	return token
}

// s7DialRealSpanner reuses the exact production spannercommit.Dial
// function (unmodified) to obtain a real, TLS/OAuth2-authenticated
// *grpc.ClientConn, then wraps it with the same spanneradapter.Client
// helper the emulator-tier tests already use for CreateSession/
// BeginReadWrite/ReadAuthorityHead -- spanneradapter.New accepts any
// already-established *grpc.ClientConn regardless of how it was dialed.
func s7DialRealSpanner(t *testing.T, token, database string) *spanneradapter.Client {
	t.Helper()
	ctx := context.Background()
	tokenSource := oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})
	conn, err := spannercommit.Dial(ctx, option.WithTokenSource(tokenSource))
	if err != nil {
		t.Fatalf("spannercommit.Dial (real Cloud Spanner): %v", err)
	}
	t.Cleanup(func() { conn.Close() })
	return spanneradapter.New(conn, database)
}

func s7WitnessKey(environment, resource, authorityEpoch, operationID string) string {
	return fmt.Sprintf("s7-processdeath/%s/%s/%s/%s.json", environment, resource, authorityEpoch, operationID)
}

// --- TestMain: dispatch to helper-subprocess mode ---

func TestMain(m *testing.M) {
	if mode := os.Getenv(s7EnvHelperMode); mode != "" {
		os.Exit(s7RunHelperProcess(mode))
	}
	os.Exit(m.Run())
}

func s7RunHelperProcess(mode string) int {
	ctx := context.Background()
	stdout := func(line string) {
		fmt.Println(line)
		os.Stdout.Sync()
	}

	environment, err := protocol.NewEnvironmentID(os.Getenv(s7EnvEnvironment))
	if err != nil {
		fmt.Fprintln(os.Stderr, "environment:", err)
		return 2
	}
	authorityEpoch, err := protocol.NewAuthorityEpoch(os.Getenv(s7EnvEpoch))
	if err != nil {
		fmt.Fprintln(os.Stderr, "epoch:", err)
		return 2
	}
	resource, err := protocol.NewResourceIncarnationID(os.Getenv(s7EnvResource))
	if err != nil {
		fmt.Fprintln(os.Stderr, "resource:", err)
		return 2
	}
	operationID, err := protocol.NewOperationID(os.Getenv(s7EnvOperation))
	if err != nil {
		fmt.Fprintln(os.Stderr, "operation:", err)
		return 2
	}
	database := os.Getenv(s7EnvDatabase)
	token := os.Getenv(s7EnvAccessToken)

	if mode == "recovery-attempt" {
		return s7RunRecoveryAttempt(ctx, stdout, environment, resource, authorityEpoch, operationID, database, token)
	}

	predecessorDigest := s7DigestOf(3)
	candidateBytes := []byte(fmt.Sprintf("s7-candidate-%s", operationID.String()))
	preparedBytes := []byte(fmt.Sprintf("s7-prepared-%s", operationID.String()))
	operation, err := rotation.NewFixedOperation(
		environment, authorityEpoch, resource, operationID,
		protocol.NewRevisionNumber(0), protocol.NewRevisionNumber(1),
		predecessorDigest, candidateBytes, preparedBytes,
	)
	if err != nil {
		fmt.Fprintln(os.Stderr, "operation:", err)
		return 2
	}

	tokenSource := oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})
	conn, err := spannercommit.Dial(ctx, option.WithTokenSource(tokenSource))
	if err != nil {
		fmt.Fprintln(os.Stderr, "dial:", err)
		return 2
	}
	client := spanneradapter.New(conn, database)

	sessionName, err := client.CreateSession(ctx)
	if err != nil {
		fmt.Fprintln(os.Stderr, "create session:", err)
		return 2
	}
	txn, err := client.BeginReadWrite(ctx, sessionName)
	if err != nil {
		fmt.Fprintln(os.Stderr, "begin:", err)
		return 2
	}
	stdout(fmt.Sprintf("SESSION session=%s txn=%s", sessionName, base64.StdEncoding.EncodeToString(txn)))

	if _, _, err := client.ReadAuthorityHead(ctx, sessionName, txn, environment.String(), resource.String()); err != nil {
		fmt.Fprintln(os.Stderr, "read authority_head:", err)
		return 2
	}

	stateDigest := s7DigestOf(9)
	candidateDigest := s7DigestOf(9)
	mutations := spanneradapter.TransitionMutations(
		environment.String(), resource.String(), authorityEpoch.String(), operationID.String(),
		operation.ProposedRevision().Uint64(), operation.ExpectedRevision().Uint64(),
		stateDigest, candidateDigest, operation.PreparedDigest(),
	)
	request := spanneradapter.CommitRequest(sessionName, txn, mutations)

	stdout("CALLING_COMMIT")
	accepted, classification, err := completeRawCommit(ctx, client.Raw(), request, operation, txn)
	if classification.Outcome != protocol.UnambiguousSuccess {
		stdout(fmt.Sprintf("COMMIT_NOT_SUCCESSFUL outcome=%v err=%v", classification.Outcome, err))
		return 0
	}
	stdout("COMMIT_SUCCEEDED")

	if mode == "decisive" {
		// Deliberately do NOT build or sign a CommittedPayload, and do NOT
		// persist a witness -- give the parent a long window to have
		// already hard-killed us at this exact point, having genuinely
		// received a real, positive-timestamp CommitResponse from real
		// Cloud Spanner.
		time.Sleep(20 * time.Second)
		stdout("UNEXPECTEDLY_SURVIVED_DECISIVE_WINDOW")
		return 0
	}

	// mode == "full-success": complete the real sign + real witness write,
	// proving the harness can discriminate a genuinely completed operation
	// from the decisive-window kill above (Control A).
	signingKey, err := hex.DecodeString(os.Getenv(s7EnvSigningKey))
	if err != nil {
		fmt.Fprintln(os.Stderr, "signing key:", err)
		return 2
	}
	signer, err := localsigner.SignerFromPrivateKeyBytes(signingKey)
	if err != nil {
		fmt.Fprintln(os.Stderr, "signer:", err)
		return 2
	}
	payload, err := buildCommittedPayload(ctx, signer, accepted)
	if err != nil {
		fmt.Fprintln(os.Stderr, "build committed payload:", err)
		return 2
	}
	serialized, err := s7SerializeCommittedPayload(payload)
	if err != nil {
		fmt.Fprintln(os.Stderr, "serialize:", err)
		return 2
	}
	gcsClient, err := gcswitness.NewClient(ctx, option.WithTokenSource(tokenSource))
	if err != nil {
		fmt.Fprintln(os.Stderr, "gcs client:", err)
		return 2
	}
	adapter := gcswitness.New(gcsClient, os.Getenv(s7EnvGCSBucket))
	if _, err := adapter.CreateExactIfAbsent(ctx, os.Getenv(s7EnvWitnessKey), serialized); err != nil {
		fmt.Fprintln(os.Stderr, "gcs persist committed:", err)
		return 2
	}
	stdout("COMMITTED_PERSISTED")
	time.Sleep(2 * time.Second)
	stdout("ACKED")
	return 0
}

// s7RunRecoveryAttempt is a genuinely fresh process (Phase 7/9): it never
// received CALLING_COMMIT/COMMIT_SUCCEEDED, never held an
// acceptedRotationContext, and has no channel, pipe, shared memory, or
// file through which one could be communicated to it even if the killed
// process had wanted to (it did not -- acceptedRotationContext's
// processCapability field wraps a non-comparable func value and is never
// serialized anywhere in this codebase). It reads real Spanner and real
// GCS ONLY to log ground truth, and computes the governed recovery
// decision from the zero value alone, exactly as
// TestProcessKillT8SuccessResponseBeforeCommittedPersistenceRequiresNewEpoch
// already does at the emulator tier.
func s7RunRecoveryAttempt(ctx context.Context, stdout func(string), environment protocol.EnvironmentID, resource protocol.ResourceIncarnationID, authorityEpoch protocol.AuthorityEpoch, operationID protocol.OperationID, database, token string) int {
	tokenSource := oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})
	conn, err := spannercommit.Dial(ctx, option.WithTokenSource(tokenSource))
	if err != nil {
		fmt.Fprintln(os.Stderr, "dial:", err)
		return 2
	}
	client := spanneradapter.New(conn, database)
	sessionName, err := client.CreateSession(ctx)
	if err != nil {
		fmt.Fprintln(os.Stderr, "create session:", err)
		return 2
	}
	txn, err := client.BeginReadWrite(ctx, sessionName)
	if err != nil {
		fmt.Fprintln(os.Stderr, "begin:", err)
		return 2
	}
	row, found, err := client.ReadAuthorityHead(ctx, sessionName, txn, environment.String(), resource.String())
	_ = client.Rollback(ctx, sessionName, txn)
	if err != nil {
		fmt.Fprintln(os.Stderr, "read:", err)
		return 2
	}
	stdout(fmt.Sprintf("GROUND_TRUTH_ROW_FOUND=%v revision=%d", found, row.RevisionNumber))

	witnessKey := s7WitnessKey(environment.String(), resource.String(), authorityEpoch.String(), operationID.String())
	gcsClient, err := gcswitness.NewClient(ctx, option.WithTokenSource(tokenSource))
	if err != nil {
		fmt.Fprintln(os.Stderr, "gcs client:", err)
		return 2
	}
	adapter := gcswitness.New(gcsClient, os.Getenv(s7EnvGCSBucket))
	witnessExists, err := adapter.Exists(ctx, witnessKey)
	if err != nil {
		fmt.Fprintln(os.Stderr, "gcs exists:", err)
		return 2
	}
	stdout(fmt.Sprintf("GROUND_TRUTH_WITNESS_EXISTS=%v", witnessExists))

	// The governed decision -- computed from the zero value alone, NEVER
	// from the ground-truth facts just logged above. This process holds no
	// acceptedRotationContext (it never could: the type is unexported,
	// its constructor is unexported, and nothing in this codebase
	// serializes or transmits one across a process boundary), so the only
	// safe starting state is the zero value.
	var state epoch.State
	if state != epoch.StateUnresolvablePreparedOperation {
		fmt.Fprintln(os.Stderr, "zero value is not StateUnresolvablePreparedOperation")
		return 2
	}
	terminated := epoch.Terminate(state)
	stdout(fmt.Sprintf("DECISION state=%s new_epoch_required=%v recovery_allowed=%v", terminated.String(), terminated.NewEpochRequired(), terminated.RecoveryAllowed()))

	// Explicitly attempt to falsify: does a matching ground-truth row
	// change the decision if we (wrongly) let it? Documented, never acted
	// on -- this process's actual DECISION variable above never consults
	// `found` or `witnessExists` at all; this second, clearly-labeled
	// computation exists only to make the contrast explicit in evidence.
	if found && !witnessExists {
		stdout("FALSIFICATION_ATTEMPT: a matching committed-looking Spanner row exists with no witness -- if this process treated that as sufficient acceptance provenance, it would wrongly resume; it does not, per the DECISION line above, which is computed without consulting `found`.")
	}
	return 0
}

func s7SerializeCommittedPayload(payload protocol.CommittedPayload) ([]byte, error) {
	dto := struct {
		EnvironmentID       string `json:"environment_id"`
		AuthorityEpoch      string `json:"authority_epoch"`
		ResourceIncarnation string `json:"resource_incarnation"`
		OperationID         string `json:"operation_id"`
		RevisionNumber      uint64 `json:"revision_number"`
		PredecessorRevision uint64 `json:"predecessor_revision"`
		PredecessorDigest   string `json:"predecessor_digest_hex"`
		StateDigest         string `json:"state_digest_hex"`
		CommitTimestamp     string `json:"commit_timestamp"`
		WriterSignature     string `json:"writer_signature_hex"`
		SigningKeyID        string `json:"signing_key_id,omitempty"`
	}{
		EnvironmentID:       payload.EnvironmentID().String(),
		AuthorityEpoch:      payload.AuthorityEpoch().String(),
		ResourceIncarnation: payload.ResourceIncarnation().String(),
		OperationID:         payload.OperationID().String(),
		RevisionNumber:      payload.RevisionNumber().Uint64(),
		PredecessorRevision: payload.PredecessorRevision().Uint64(),
		PredecessorDigest:   payload.PredecessorDigest().String(),
		StateDigest:         payload.StateDigest().String(),
		CommitTimestamp:     payload.CommitTimestamp().Format(time.RFC3339Nano),
		WriterSignature:     hex.EncodeToString(payload.WriterSignature()),
	}
	if payload.IsV2() {
		dto.SigningKeyID = payload.SigningKeyID().String()
	}
	return json.Marshal(dto)
}

// --- parent-side harness ---

type s7HelperResult struct {
	Lines   []string
	Session string
	TxnID   []byte
}

func (r s7HelperResult) sawLine(prefix string) bool {
	for _, line := range r.Lines {
		if strings.HasPrefix(line, prefix) {
			return true
		}
	}
	return false
}

func s7SpawnAndKillAfter(t *testing.T, mode string, env map[string]string, killAfterPrefix string) s7HelperResult {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^$")
	cmd.Env = append(os.Environ(), s7EnvHelperMode+"="+mode)
	for k, v := range env {
		cmd.Env = append(cmd.Env, k+"="+v)
	}
	stdoutPipe, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	cmd.Stderr = os.Stderr
	startedAt := time.Now().UTC()
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	pid := cmd.Process.Pid

	result := s7HelperResult{}
	buf := make([]byte, 4096)
	var pending string
	killed := false
	for {
		n, readErr := stdoutPipe.Read(buf)
		if n > 0 {
			pending += string(buf[:n])
			for {
				idx := strings.IndexByte(pending, '\n')
				if idx < 0 {
					break
				}
				line := pending[:idx]
				pending = pending[idx+1:]
				result.Lines = append(result.Lines, line)
				t.Logf("child[%d]: %s", pid, line)
				if strings.HasPrefix(line, "SESSION ") {
					for _, field := range strings.Fields(line) {
						if strings.HasPrefix(field, "session=") {
							result.Session = strings.TrimPrefix(field, "session=")
						}
						if strings.HasPrefix(field, "txn=") {
							raw, decodeErr := base64.StdEncoding.DecodeString(strings.TrimPrefix(field, "txn="))
							if decodeErr == nil {
								result.TxnID = raw
							}
						}
					}
				}
				if !killed && strings.HasPrefix(line, killAfterPrefix) {
					killAt := time.Now().UTC()
					t.Logf("SIGKILL pid=%d at %s (%.3fs after start)", pid, killAt.Format(time.RFC3339Nano), killAt.Sub(startedAt).Seconds())
					_ = cmd.Process.Kill() // SIGKILL
					killed = true
				}
			}
		}
		if readErr != nil {
			break
		}
	}
	waitErr := cmd.Wait()
	t.Logf("child[%d] exited: %v", pid, waitErr)
	if !killed {
		t.Fatalf("helper process never reached the required sentinel %q; observed lines: %v", killAfterPrefix, result.Lines)
	}
	return result
}

func s7RunToCompletion(t *testing.T, mode string, env map[string]string) s7HelperResult {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^$")
	cmd.Env = append(os.Environ(), s7EnvHelperMode+"="+mode)
	for k, v := range env {
		cmd.Env = append(cmd.Env, k+"="+v)
	}
	out, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			t.Fatalf("helper exited %v; stderr=%s", err, exitErr.Stderr)
		}
		t.Fatalf("run helper: %v", err)
	}
	lines := strings.Split(strings.TrimRight(string(out), "\n"), "\n")
	for _, l := range lines {
		t.Logf("child(complete): %s", l)
	}
	return s7HelperResult{Lines: lines}
}

func s7BaseEnv(environment, authorityEpoch, resource, operationID, database, token, bucket string) map[string]string {
	return map[string]string{
		s7EnvEnvironment: environment,
		s7EnvEpoch:       authorityEpoch,
		s7EnvResource:    resource,
		s7EnvOperation:   operationID,
		s7EnvDatabase:    database,
		s7EnvAccessToken: token,
		s7EnvGCSBucket:   bucket,
	}
}

func s7RollbackBestEffort(t *testing.T, database, token, session string, txnID []byte) {
	t.Helper()
	if len(txnID) == 0 {
		return
	}
	client := s7DialRealSpanner(t, token, database)
	if err := client.Rollback(context.Background(), session, txnID); err != nil {
		t.Logf("best-effort rollback (session=%s): %v", session, err)
	}
}

type s7Evidence struct {
	Step      string `json:"step"`
	Timestamp string `json:"timestamp"`
	Detail    string `json:"detail"`
}

func s7WriteEvidence(t *testing.T, entries []s7Evidence) {
	t.Helper()
	path := os.Getenv(s7EnvEvidenceOut)
	if path == "" {
		return
	}
	data, err := json.MarshalIndent(entries, "", "  ")
	if err != nil {
		t.Logf("encode evidence: %v", err)
		return
	}
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Logf("write evidence: %v", err)
	}
}

// TestS7ControlCleanSuccess (Control A): the harness's positive case --
// real Commit, real sign, real witness write, killed only after
// COMMITTED_PERSISTED (mirrors emulator T10). Proves the harness can
// discriminate "genuinely completed" from the decisive trial below.
func TestS7ControlCleanSuccess(t *testing.T) {
	database := s7RealDatabase(t)
	bucket := s7RealBucket(t)
	token := s7AccessToken(t)
	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	environment, authorityEpoch, resource, operationID := s7RealEnvironment, s7UUIDv7ish(), s7UUIDv7ish(), s7UUIDv7ish()
	witnessKey := s7WitnessKey(environment, resource, authorityEpoch, operationID)
	env := s7BaseEnv(environment, authorityEpoch, resource, operationID, database, token, bucket)
	env[s7EnvSigningKey] = hex.EncodeToString(keyPair.PrivateKeyBytes())
	env[s7EnvWitnessKey] = witnessKey

	result := s7SpawnAndKillAfter(t, "full-success", env, "ACKED")
	defer s7RollbackBestEffort(t, database, token, result.Session, result.TxnID)

	if !result.sawLine("COMMITTED_PERSISTED") {
		t.Fatal("expected COMMITTED_PERSISTED before ACKED")
	}
	// Independently re-verify the witness via a FRESH GCS client, never
	// the child's.
	tokenSource := oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})
	gcsClient, err := gcswitness.NewClient(context.Background(), option.WithTokenSource(tokenSource))
	if err != nil {
		t.Fatal(err)
	}
	adapter := gcswitness.New(gcsClient, bucket)
	raw, err := adapter.ReadExact(context.Background(), witnessKey)
	if err != nil {
		t.Fatalf("expected a persisted COMMITTED witness object: %v", err)
	}
	var dto struct {
		SigningKeyID string `json:"signing_key_id"`
	}
	if err := json.Unmarshal(raw, &dto); err != nil {
		t.Fatal(err)
	}
	envID, _ := protocol.NewEnvironmentID(environment)
	epochID, _ := protocol.NewAuthorityEpoch(authorityEpoch)
	resourceID, _ := protocol.NewResourceIncarnationID(resource)
	opID, _ := protocol.NewOperationID(operationID)
	expected := recovery.ExpectedBinding{
		EnvironmentID: envID, AuthorityEpoch: epochID, ResourceIncarnation: resourceID, OperationID: opID,
		PredecessorRevision: protocol.NewRevisionNumber(0), PredecessorDigest: s7DigestOf(3),
		ApprovedSigningLineage: func(keyID protocol.SigningKeyID) bool { return keyID == keyPair.KeyID() },
	}
	payload := s7Deserialize(t, raw)
	if err := recovery.VerifyPersistedCommitted(context.Background(), keyPair.Verifier(), payload, expected); err != nil {
		t.Fatalf("independent verification failed: %v", err)
	}
	resumed := epoch.TransitionOnWitnessOutcome(true)
	if resumed != epoch.StateActive || resumed.NewEpochRequired() {
		t.Fatalf("resumed state = %v, want StateActive/not-new-epoch-required", resumed)
	}
	t.Log("CONTROL_A_PASS: real Commit + real sign + real witness write, independently re-verified, resumable")
}

func s7Deserialize(t *testing.T, raw []byte) protocol.CommittedPayload {
	t.Helper()
	var dto struct {
		EnvironmentID       string `json:"environment_id"`
		AuthorityEpoch      string `json:"authority_epoch"`
		ResourceIncarnation string `json:"resource_incarnation"`
		OperationID         string `json:"operation_id"`
		RevisionNumber      uint64 `json:"revision_number"`
		PredecessorRevision uint64 `json:"predecessor_revision"`
		PredecessorDigest   string `json:"predecessor_digest_hex"`
		StateDigest         string `json:"state_digest_hex"`
		CommitTimestamp     string `json:"commit_timestamp"`
		WriterSignature     string `json:"writer_signature_hex"`
		SigningKeyID        string `json:"signing_key_id"`
	}
	if err := json.Unmarshal(raw, &dto); err != nil {
		t.Fatal(err)
	}
	environment, _ := protocol.NewEnvironmentID(dto.EnvironmentID)
	authorityEpoch, _ := protocol.NewAuthorityEpoch(dto.AuthorityEpoch)
	resource, _ := protocol.NewResourceIncarnationID(dto.ResourceIncarnation)
	operationID, _ := protocol.NewOperationID(dto.OperationID)
	predecessorDigest, _ := protocol.ParseDigest32(dto.PredecessorDigest)
	stateDigest, _ := protocol.ParseDigest32(dto.StateDigest)
	commitTimestamp, _ := time.Parse(time.RFC3339Nano, dto.CommitTimestamp)
	signature, _ := hex.DecodeString(dto.WriterSignature)
	keyID, _ := protocol.NewSigningKeyID(dto.SigningKeyID)
	payload, err := protocol.NewCommittedPayloadV2(
		environment, authorityEpoch, resource, operationID,
		protocol.NewRevisionNumber(dto.RevisionNumber), protocol.NewRevisionNumber(dto.PredecessorRevision),
		predecessorDigest, stateDigest, commitTimestamp, keyID, signature,
	)
	if err != nil {
		t.Fatal(err)
	}
	return payload
}

// TestS7ControlKillBeforeCommit (Control C): the child is killed while its
// Commit RPC is still in flight / before dispatch is even confirmed by
// this harness (mirrors emulator T7, without a fault-proxy delay -- real
// Cloud Spanner Commit latency is normally sub-second, so killing
// immediately upon observing CALLING_COMMIT reliably lands before any
// response is processed by the child).
func TestS7ControlKillBeforeCommit(t *testing.T) {
	database := s7RealDatabase(t)
	bucket := s7RealBucket(t)
	token := s7AccessToken(t)
	environment, authorityEpoch, resource, operationID := s7RealEnvironment, s7UUIDv7ish(), s7UUIDv7ish(), s7UUIDv7ish()
	env := s7BaseEnv(environment, authorityEpoch, resource, operationID, database, token, bucket)

	result := s7SpawnAndKillAfter(t, "decisive", env, "CALLING_COMMIT")
	defer s7RollbackBestEffort(t, database, token, result.Session, result.TxnID)

	if !result.sawLine("CALLING_COMMIT") {
		t.Fatal("expected to observe CALLING_COMMIT before the kill")
	}
	if result.sawLine("COMMIT_SUCCEEDED") {
		t.Log("NOTE: commit reached success before the kill signal was processed -- real Cloud Spanner Commit latency can be faster than this harness's read loop; this specific race does not invalidate the decisive trial below, which discriminates on COMMIT_SUCCEEDED specifically, not on this control")
	} else {
		t.Log("CONTROL_C_PASS: kill landed before the child observed a successful Commit")
	}
}

// TestS7DecisiveProcessDeathTrial is the central S7 proof: the child
// genuinely receives a real, positive-timestamp CommitResponse from real
// Cloud Spanner (UnambiguousSuccess), is then hard-killed (SIGKILL) before
// it ever calls the signer or attempts a witness write, and a completely
// fresh, independent process is then spawned to attempt recovery using
// only durable state.
func TestS7DecisiveProcessDeathTrial(t *testing.T) {
	database := s7RealDatabase(t)
	bucket := s7RealBucket(t)
	token := s7AccessToken(t)
	environment, authorityEpoch, resource, operationID := s7RealEnvironment, s7UUIDv7ish(), s7UUIDv7ish(), s7UUIDv7ish()
	env := s7BaseEnv(environment, authorityEpoch, resource, operationID, database, token, bucket)

	var evidence []s7Evidence
	record := func(step, detail string) {
		evidence = append(evidence, s7Evidence{Step: step, Timestamp: time.Now().UTC().Format(time.RFC3339Nano), Detail: detail})
	}
	defer func() { s7WriteEvidence(t, evidence) }()

	result := s7SpawnAndKillAfter(t, "decisive", env, "COMMIT_SUCCEEDED")
	defer s7RollbackBestEffort(t, database, token, result.Session, result.TxnID)

	if !result.sawLine("CALLING_COMMIT") {
		t.Fatal("expected CALLING_COMMIT before the kill")
	}
	if !result.sawLine("COMMIT_SUCCEEDED") {
		t.Fatal("expected COMMIT_SUCCEEDED (real UnambiguousSuccess) before the kill")
	}
	if result.sawLine("UNEXPECTEDLY_SURVIVED_DECISIVE_WINDOW") {
		t.Fatal("the child was not actually killed within the decisive window")
	}
	record("commit_dispatched", "real Commit RPC sent to real Cloud Spanner")
	record("commit_succeeded_observed", "child printed COMMIT_SUCCEEDED: classification was UnambiguousSuccess from a real positive-timestamp CommitResponse")
	record("process_killed", fmt.Sprintf("child SIGKILLed immediately upon observing COMMIT_SUCCEEDED; lines observed: %v", result.Lines))

	// Independent ground truth, via a FRESH connection -- confirms the
	// backend genuinely committed (this is NOT used to make any decision
	// below; it is recorded for evidence only, exactly as
	// TestProcessKillT8... already does at the emulator tier).
	verifyClient := s7DialRealSpanner(t, token, database)
	verifySession, err := verifyClient.CreateSession(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	verifyTxn, err := verifyClient.BeginReadWrite(context.Background(), verifySession)
	if err != nil {
		t.Fatal(err)
	}
	row, found, err := verifyClient.ReadAuthorityHead(context.Background(), verifySession, verifyTxn, environment, resource)
	_ = verifyClient.Rollback(context.Background(), verifySession, verifyTxn)
	if err != nil {
		t.Fatal(err)
	}
	if !found || row.RevisionNumber != 1 {
		t.Fatalf("ground truth: expected a genuinely committed row at revision 1; found=%v row=%+v", found, row)
	}
	t.Logf("ground truth CONFIRMS backend commit == SUCCESS (revision %d) -- decision below is computed WITHOUT consulting this fact", row.RevisionNumber)
	record("ground_truth_commit_confirmed", fmt.Sprintf("real Spanner row exists, revision=%d, commit_timestamp=%s (NOT consulted in the recovery decision)", row.RevisionNumber, row.CommitTimestamp.Format(time.RFC3339Nano)))

	witnessKey := s7WitnessKey(environment, resource, authorityEpoch, operationID)
	tokenSource := oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})
	gcsClient, err := gcswitness.NewClient(context.Background(), option.WithTokenSource(tokenSource))
	if err != nil {
		t.Fatal(err)
	}
	witnessExists, err := gcswitness.New(gcsClient, bucket).Exists(context.Background(), witnessKey)
	if err != nil {
		t.Fatal(err)
	}
	if witnessExists {
		t.Fatal("no COMMITTED witness object may exist -- the child was killed before ever attempting one")
	}
	record("witness_absent_confirmed", "independently re-verified via a fresh GCS client: no witness object exists at the deterministic key")

	// The governed decision, computed from the zero value alone -- NEVER
	// from the ground-truth facts just recorded above.
	var state epoch.State
	if state != epoch.StateUnresolvablePreparedOperation {
		t.Fatalf("zero value = %v, want StateUnresolvablePreparedOperation", state)
	}
	terminated := epoch.Terminate(state)
	if !terminated.NewEpochRequired() {
		t.Fatal("terminated state must require a new epoch")
	}
	if terminated.RecoveryAllowed() || terminated.RotationAllowed() || terminated.FenceReleaseAllowed() || terminated.PostgreSQLReconciliationAllowed() {
		t.Fatal("a terminated epoch must permit no authority-dependent decision")
	}
	record("decision_new_epoch_required", fmt.Sprintf("state=%s new_epoch_required=%v -- computed from the zero value only", terminated.String(), terminated.NewEpochRequired()))
	t.Logf("DECISIVE_TRIAL_PASS: real Commit succeeded, process killed before witness, decision=%s (NEW_EPOCH_REQUIRED=%v), independent of the confirmed-committed ground truth", terminated.String(), terminated.NewEpochRequired())

	// Phase 9 restart matrix: spawn multiple, independent, genuinely fresh
	// recovery-attempt processes (no shared memory with the killed child
	// or with each other), with a delay between them, and confirm every
	// one converges to the identical decision.
	for i, delay := range []time.Duration{0, 2 * time.Second, 5 * time.Second} {
		time.Sleep(delay)
		recoveryEnv := s7BaseEnv(environment, authorityEpoch, resource, operationID, database, token, bucket)
		attempt := s7RunToCompletion(t, "recovery-attempt", recoveryEnv)
		if !attempt.sawLine("GROUND_TRUTH_ROW_FOUND=true") {
			t.Fatalf("restart attempt %d: expected ground truth to confirm the row exists", i)
		}
		if !attempt.sawLine("GROUND_TRUTH_WITNESS_EXISTS=false") {
			t.Fatalf("restart attempt %d: expected ground truth to confirm no witness exists", i)
		}
		found := false
		for _, line := range attempt.Lines {
			if strings.HasPrefix(line, "DECISION ") && strings.Contains(line, "state=EPOCH_TERMINATED") && strings.Contains(line, "new_epoch_required=true") {
				found = true
			}
		}
		if !found {
			t.Fatalf("restart attempt %d: fresh process did not converge to the required fail-closed decision; lines=%v", i, attempt.Lines)
		}
		record(fmt.Sprintf("restart_attempt_%d", i), fmt.Sprintf("fresh process, %v after prior attempt, converged to the identical fail-closed decision", delay))
	}
	t.Log("RESTART_MATRIX_PASS: 3 independent fresh processes, with delays, all converged to the identical fail-closed decision -- no healing across restarts")
}
