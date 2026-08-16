//go:build emulator

package rotationcommit

// T7/T8/T10 process-kill matrix. These tests spawn a real, separate OS
// process (the compiled test binary re-executing itself, the same trick
// Go's own os/exec tests use) that performs one real Commit attempt
// against the emulator, and SIGKILL it at a controlled point. The parent
// then inspects real emulator state and applies the frozen epoch/recovery
// logic to decide whether a new epoch is required or resumption is safe.
//
// completeRawCommit and buildCommittedPayload are unexported. A genuinely
// separate `package main` helper binary could not call them at all -- that
// restriction is the security boundary working as designed, not an
// oversight to work around. The subprocess here is therefore this same
// test binary, re-executed with an environment variable telling TestMain
// to run helper logic instead of the normal test suite: it is still
// package rotationcommit code, running in a genuinely separate OS process
// with its own memory, exactly what T7/T8/T10 require.

import (
	"bufio"
	"context"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/faultproxy"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/localsigner"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/spanneradapter"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/witness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/epoch"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/recovery"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotation"
	"google.golang.org/api/option"
)

const (
	helperEnvMode          = "EMG_ADR043_HELPER_MODE"
	helperEnvDialAddr      = "EMG_ADR043_DIAL_ADDR"
	helperEnvEnvironment   = "EMG_ADR043_ENVIRONMENT"
	helperEnvEpoch         = "EMG_ADR043_EPOCH"
	helperEnvResource      = "EMG_ADR043_RESOURCE"
	helperEnvOperation     = "EMG_ADR043_OPERATION"
	helperEnvExpectedRev   = "EMG_ADR043_EXPECTED_REVISION"
	helperEnvPredecessor   = "EMG_ADR043_PREDECESSOR_DIGEST_HEX"
	helperEnvCandidate     = "EMG_ADR043_CANDIDATE"
	helperEnvPrepared      = "EMG_ADR043_PREPARED"
	helperEnvSigningKeyHex = "EMG_ADR043_SIGNING_KEY_HEX"
	helperEnvWitnessRoot   = "EMG_ADR043_WITNESS_ROOT"
	helperEnvWitnessKey    = "EMG_ADR043_WITNESS_KEY"
	helperEnvGCSEndpoint   = "EMG_ADR043_GCS_ENDPOINT"
	helperEnvGCSBucket     = "EMG_ADR043_GCS_BUCKET"
)

func TestMain(m *testing.M) {
	if mode := os.Getenv(helperEnvMode); mode != "" {
		os.Exit(runHelperProcess(mode))
	}
	os.Exit(m.Run())
}

func runHelperProcess(mode string) int {
	ctx := context.Background()
	stdout := func(line string) {
		fmt.Println(line)
		os.Stdout.Sync()
	}

	environment, err := protocol.NewEnvironmentID(os.Getenv(helperEnvEnvironment))
	if err != nil {
		fmt.Fprintln(os.Stderr, "environment:", err)
		return 2
	}
	authorityEpoch, err := protocol.NewAuthorityEpoch(os.Getenv(helperEnvEpoch))
	if err != nil {
		fmt.Fprintln(os.Stderr, "epoch:", err)
		return 2
	}
	resource, err := protocol.NewResourceIncarnationID(os.Getenv(helperEnvResource))
	if err != nil {
		fmt.Fprintln(os.Stderr, "resource:", err)
		return 2
	}
	operationID, err := protocol.NewOperationID(os.Getenv(helperEnvOperation))
	if err != nil {
		fmt.Fprintln(os.Stderr, "operation:", err)
		return 2
	}
	expectedRevision, err := strconv.ParseUint(os.Getenv(helperEnvExpectedRev), 10, 64)
	if err != nil {
		fmt.Fprintln(os.Stderr, "expected revision:", err)
		return 2
	}
	predecessorDigestRaw, err := hex.DecodeString(os.Getenv(helperEnvPredecessor))
	if err != nil {
		fmt.Fprintln(os.Stderr, "predecessor digest:", err)
		return 2
	}
	predecessorDigest, err := protocol.NewDigest32(predecessorDigestRaw)
	if err != nil {
		fmt.Fprintln(os.Stderr, "predecessor digest:", err)
		return 2
	}

	operation, err := rotation.NewFixedOperation(
		environment, authorityEpoch, resource, operationID,
		protocol.NewRevisionNumber(expectedRevision), protocol.NewRevisionNumber(expectedRevision+1),
		predecessorDigest, []byte(os.Getenv(helperEnvCandidate)), []byte(os.Getenv(helperEnvPrepared)),
	)
	if err != nil {
		fmt.Fprintln(os.Stderr, "operation:", err)
		return 2
	}

	// Session/transaction management always goes over a DIRECT connection
	// to the real emulator, never through a fault-injecting proxy: only the
	// raw Commit call itself (below, over a second, separately dialed
	// connection) is ever subject to an injected fault. This mirrors
	// RawCommitClient's own shape -- it is exactly and only the Commit
	// method -- and means a connection-level proxy fault cannot
	// accidentally delay CreateSession/BeginTransaction/Read as a side
	// effect of delaying Commit's response.
	sessionConn, err := spanneradapter.Dial(ctx, emulatorAddr)
	if err != nil {
		fmt.Fprintln(os.Stderr, "dial (session):", err)
		return 2
	}
	client := spanneradapter.New(sessionConn, emulatorDatabase)

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
	// Announce session/transaction identity immediately -- whatever happens
	// next, the parent needs these to release the emulator's single active
	// transaction slot after killing us.
	stdout(fmt.Sprintf("SESSION session=%s txn=%s", sessionName, base64.StdEncoding.EncodeToString(txn)))

	client.ReadAuthorityHead(ctx, sessionName, txn, environment.String(), resource.String())
	mutations := transitionMutationsFor(operation)
	request := spanneradapter.CommitRequest(sessionName, txn, mutations)

	commitConn, err := spanneradapter.Dial(ctx, os.Getenv(helperEnvDialAddr))
	if err != nil {
		fmt.Fprintln(os.Stderr, "dial (commit):", err)
		return 2
	}
	commitClient := spanneradapter.New(commitConn, emulatorDatabase)

	stdout("CALLING_COMMIT")
	accepted, classification, err := completeRawCommit(ctx, commitClient.Raw(), request, operation, txn)
	if classification.Outcome != protocol.UnambiguousSuccess {
		stdout(fmt.Sprintf("COMMIT_NOT_SUCCESSFUL outcome=%v err=%v", classification.Outcome, err))
		return 0
	}
	stdout("COMMIT_SUCCEEDED")

	if mode == "t8" {
		// Deliberately do NOT persist COMMITTED yet -- give the parent a
		// long window to kill us exactly here, having already received a
		// genuine successful CommitResponse.
		time.Sleep(10 * time.Second)
		stdout("UNEXPECTEDLY_SURVIVED_T8_WINDOW")
		return 0
	}

	signingKey, err := hex.DecodeString(os.Getenv(helperEnvSigningKeyHex))
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
	serialized, err := serializeCommittedPayload(payload)
	if err != nil {
		fmt.Fprintln(os.Stderr, "serialize:", err)
		return 2
	}
	if mode == "t10gcs" {
		client, gcsErr := gcswitness.NewClient(ctx,
			option.WithEndpoint(os.Getenv(helperEnvGCSEndpoint)),
			option.WithoutAuthentication(),
			option.WithHTTPClient(&http.Client{}),
		)
		if gcsErr != nil {
			fmt.Fprintln(os.Stderr, "gcs client:", gcsErr)
			return 2
		}
		adapter := gcswitness.New(client, os.Getenv(helperEnvGCSBucket))
		if _, createErr := adapter.CreateExactIfAbsent(ctx, os.Getenv(helperEnvWitnessKey), serialized); createErr != nil {
			fmt.Fprintln(os.Stderr, "gcs persist committed:", createErr)
			return 2
		}
	} else {
		repo, err := witness.NewRepository(os.Getenv(helperEnvWitnessRoot))
		if err != nil {
			fmt.Fprintln(os.Stderr, "witness repository:", err)
			return 2
		}
		if err := repo.CreateOnlyIfAbsent(ctx, os.Getenv(helperEnvWitnessKey), serialized); err != nil {
			fmt.Fprintln(os.Stderr, "persist committed:", err)
			return 2
		}
	}
	stdout("COMMITTED_PERSISTED")

	// Deliberately do NOT print any further acknowledgement yet -- give the
	// parent a long window to kill us exactly here, having already
	// durably persisted a valid, signed COMMITTED witness object, but
	// before the process could ever tell its own caller "done".
	time.Sleep(10 * time.Second)
	stdout("ACKED")
	return 0
}

type committedPayloadDTO struct {
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
}

func serializeCommittedPayload(payload protocol.CommittedPayload) ([]byte, error) {
	return json.Marshal(committedPayloadDTO{
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
	})
}

func deserializeCommittedPayload(t *testing.T, data []byte) protocol.CommittedPayload {
	t.Helper()
	var dto committedPayloadDTO
	if err := json.Unmarshal(data, &dto); err != nil {
		t.Fatal(err)
	}
	environment, err := protocol.NewEnvironmentID(dto.EnvironmentID)
	if err != nil {
		t.Fatal(err)
	}
	authorityEpoch, err := protocol.NewAuthorityEpoch(dto.AuthorityEpoch)
	if err != nil {
		t.Fatal(err)
	}
	resource, err := protocol.NewResourceIncarnationID(dto.ResourceIncarnation)
	if err != nil {
		t.Fatal(err)
	}
	operationID, err := protocol.NewOperationID(dto.OperationID)
	if err != nil {
		t.Fatal(err)
	}
	predecessorDigest, err := protocol.ParseDigest32(dto.PredecessorDigest)
	if err != nil {
		t.Fatal(err)
	}
	stateDigest, err := protocol.ParseDigest32(dto.StateDigest)
	if err != nil {
		t.Fatal(err)
	}
	commitTimestamp, err := time.Parse(time.RFC3339Nano, dto.CommitTimestamp)
	if err != nil {
		t.Fatal(err)
	}
	signature, err := hex.DecodeString(dto.WriterSignature)
	if err != nil {
		t.Fatal(err)
	}
	return protocol.NewCommittedPayload(
		environment, authorityEpoch, resource, operationID,
		protocol.NewRevisionNumber(dto.RevisionNumber), protocol.NewRevisionNumber(dto.PredecessorRevision),
		predecessorDigest, stateDigest, commitTimestamp, signature,
	)
}

// helperResult is what the parent observed from a killed subprocess before
// it died.
type helperResult struct {
	Lines   []string
	Session string
	TxnID   []byte
}

func (r helperResult) sawLine(prefix string) bool {
	for _, line := range r.Lines {
		if strings.HasPrefix(line, prefix) {
			return true
		}
	}
	return false
}

// spawnHelperAndKillAfter starts this same test binary as a subprocess in
// helper mode, reads its stdout line by line, and sends SIGKILL the moment
// killAfterPrefix is observed (or, if it never appears within the timeout,
// fails the test rather than silently proceeding).
func spawnHelperAndKillAfter(t *testing.T, mode string, env map[string]string, killAfterPrefix string) helperResult {
	t.Helper()
	cmd := exec.Command(os.Args[0])
	cmd.Env = append(os.Environ(), helperEnvMode+"="+mode)
	for k, v := range env {
		cmd.Env = append(cmd.Env, k+"="+v)
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}

	result := helperResult{}
	scanner := bufio.NewScanner(stdout)
	killed := false
	for scanner.Scan() {
		line := scanner.Text()
		result.Lines = append(result.Lines, line)
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
		if strings.HasPrefix(line, killAfterPrefix) {
			cmd.Process.Kill() // SIGKILL
			killed = true
			break
		}
	}
	cmd.Wait() // reap; error expected (killed)
	if !killed {
		t.Fatalf("helper process never reached the required sentinel %q; observed lines: %v", killAfterPrefix, result.Lines)
	}
	return result
}

func baseHelperEnv(t *testing.T, op emulatorOperation, expectedRevision uint64, dialAddr, witnessRoot, witnessKey string, signingKeyHex string) map[string]string {
	t.Helper()
	predecessorDigest := digestOf(t, 3)
	return map[string]string{
		helperEnvDialAddr:      dialAddr,
		helperEnvEnvironment:   op.Environment.String(),
		helperEnvEpoch:         op.Epoch.String(),
		helperEnvResource:      op.ResourceIncarnation.String(),
		helperEnvOperation:     op.OperationID.String(),
		helperEnvExpectedRev:   strconv.FormatUint(expectedRevision, 10),
		helperEnvPredecessor:   predecessorDigest.String(),
		helperEnvCandidate:     fmt.Sprintf("candidate-%s-%d", op.OperationID.String(), expectedRevision+1),
		helperEnvPrepared:      fmt.Sprintf("prepared-%s-%d", op.OperationID.String(), expectedRevision+1),
		helperEnvSigningKeyHex: signingKeyHex,
		helperEnvWitnessRoot:   witnessRoot,
		helperEnvWitnessKey:    witnessKey,
	}
}

// TestProcessKillT7CommitOutstandingRequiresNewEpoch: the helper process is
// killed while its Commit RPC is still genuinely in flight (guaranteed via
// a fault-proxy delay far longer than the kill happens after). No later
// Spanner read may be used to resolve this -- the assertion below is
// computed without consulting one, and a ground-truth read is performed
// only afterward, for logging, to document that the decision does not
// depend on what it finds.
func TestProcessKillT7CommitOutstandingRequiresNewEpoch(t *testing.T) {
	op := newEmulatorOperation(t)
	proxy := faultproxy.New(emulatorAddr, 8*time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	proxy.QueueFault(faultproxy.DelayPastDeadline)

	witnessRoot := t.TempDir()
	env := baseHelperEnv(t, op, 0, proxyAddr, witnessRoot, "committed/"+op.OperationID.String(), hex.EncodeToString(make([]byte, 64)))
	result := spawnHelperAndKillAfter(t, "t7", env, "CALLING_COMMIT")
	defer rollbackBestEffort(t, emulatorAddr, result.Session, result.TxnID)

	if !result.sawLine("CALLING_COMMIT") {
		t.Fatal("expected to observe CALLING_COMMIT before the kill")
	}
	if result.sawLine("COMMIT_SUCCEEDED") || result.sawLine("COMMITTED_PERSISTED") {
		t.Fatal("T7 requires the kill to land before any success was observed by the child")
	}

	// Ground truth, for documentation only -- NOT consulted in the
	// decision below.
	directClient := dialEmulator(t, emulatorAddr)
	groundTruthSession, err := directClient.CreateSession(context.Background())
	if err == nil {
		groundTruthTxn, txnErr := directClient.BeginReadWrite(context.Background(), groundTruthSession)
		if txnErr == nil {
			_, found, _ := directClient.ReadAuthorityHead(context.Background(), groundTruthSession, groundTruthTxn, op.Environment.String(), op.ResourceIncarnation.String())
			t.Logf("ground truth (not consulted in the decision): authority_head row present = %v", found)
			directClient.Rollback(context.Background(), groundTruthSession, groundTruthTxn)
		}
	}

	repo, err := witness.NewRepository(witnessRoot)
	if err != nil {
		t.Fatal(err)
	}
	committedExists, err := repo.Exists(context.Background(), "committed/"+op.OperationID.String())
	if err != nil {
		t.Fatal(err)
	}
	if committedExists {
		t.Fatal("no COMMITTED witness object may exist -- the child never reached persistence")
	}

	// The recovery decision, computed from ONLY {no live accepted context,
	// no valid witnessed COMMITTED} -- the zero value, by construction.
	var state epoch.State
	if state != epoch.StateUnresolvablePreparedOperation {
		t.Fatalf("state = %v, want the zero value", state)
	}
	terminated := epoch.Terminate(state)
	assertAmbiguousEpochInvariants(t, terminated, false)
}

// TestProcessKillT8SuccessResponseBeforeCommittedPersistenceRequiresNewEpoch
// is the sharpest process-kill test: the child genuinely received a
// successful CommitResponse (proven by a direct, unproxied ground-truth
// read after the kill, which DOES show the committed row -- real success,
// not a simulated one), but was killed before it could persist COMMITTED.
// The epoch must still be terminated, specifically despite that favorable
// ground truth.
func TestProcessKillT8SuccessResponseBeforeCommittedPersistenceRequiresNewEpoch(t *testing.T) {
	op := newEmulatorOperation(t)
	witnessRoot := t.TempDir()
	env := baseHelperEnv(t, op, 0, emulatorAddr, witnessRoot, "committed/"+op.OperationID.String(), hex.EncodeToString(make([]byte, 64)))
	result := spawnHelperAndKillAfter(t, "t8", env, "COMMIT_SUCCEEDED")
	defer rollbackBestEffort(t, emulatorAddr, result.Session, result.TxnID)

	if !result.sawLine("COMMIT_SUCCEEDED") {
		t.Fatal("expected to observe COMMIT_SUCCEEDED before the kill")
	}
	if result.sawLine("COMMITTED_PERSISTED") {
		t.Fatal("T8 requires the kill to land before persistence was observed by the child")
	}

	// Ground truth: this MUST show the row committed -- proving the backend
	// genuinely succeeded, not merely that the classifier would have
	// treated some ambiguous response as success.
	directClient := dialEmulator(t, emulatorAddr)
	verifySession, err := directClient.CreateSession(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	verifyTxn, err := directClient.BeginReadWrite(context.Background(), verifySession)
	if err != nil {
		t.Fatal(err)
	}
	row, found, err := directClient.ReadAuthorityHead(context.Background(), verifySession, verifyTxn, op.Environment.String(), op.ResourceIncarnation.String())
	directClient.Rollback(context.Background(), verifySession, verifyTxn)
	if err != nil {
		t.Fatal(err)
	}
	if !found || row.RevisionNumber != 1 {
		t.Fatalf("expected ground truth to show a genuinely committed row at revision 1; found=%v row=%+v", found, row)
	}
	t.Logf("ground truth CONFIRMS backend_commit == SUCCESS (revision %d) -- decision below must still terminate the epoch", row.RevisionNumber)

	repo, err := witness.NewRepository(witnessRoot)
	if err != nil {
		t.Fatal(err)
	}
	committedExists, err := repo.Exists(context.Background(), "committed/"+op.OperationID.String())
	if err != nil {
		t.Fatal(err)
	}
	if committedExists {
		t.Fatal("no COMMITTED witness object may exist -- the child was killed before persisting one")
	}

	var state epoch.State
	terminated := epoch.Terminate(state)
	assertAmbiguousEpochInvariants(t, terminated, false)
}

// TestProcessKillT10CommittedPersistedBeforeAckMayResume is the one
// positive-resolution case in the process-kill matrix: the child is killed
// only AFTER it durably persisted a validly signed COMMITTED witness
// object (proven by the parent independently re-verifying it after the
// kill, in a fresh process, using only the public verifier key -- never
// the child's private key material), and before it could tell its own
// caller "done". Recovery may treat ACTIVE(new_revision) as resumable.
func TestProcessKillT10CommittedPersistedBeforeAckMayResume(t *testing.T) {
	op := newEmulatorOperation(t)
	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	witnessRoot := t.TempDir()
	witnessKey := "committed/" + op.OperationID.String()
	env := baseHelperEnv(t, op, 0, emulatorAddr, witnessRoot, witnessKey, hex.EncodeToString(keyPair.PrivateKeyBytes()))
	result := spawnHelperAndKillAfter(t, "t10", env, "COMMITTED_PERSISTED")
	defer rollbackBestEffort(t, emulatorAddr, result.Session, result.TxnID)

	if !result.sawLine("COMMITTED_PERSISTED") {
		t.Fatal("expected to observe COMMITTED_PERSISTED before the kill")
	}
	if result.sawLine("ACKED") {
		t.Fatal("T10 requires the kill to land before the child could acknowledge completion")
	}

	repo, err := witness.NewRepository(witnessRoot)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := repo.Read(context.Background(), witnessKey)
	if err != nil {
		t.Fatalf("expected a persisted COMMITTED witness object: %v", err)
	}
	payload := deserializeCommittedPayload(t, raw)

	// A fresh verifier, holding only the PUBLIC key -- this process never
	// had access to the child's private signing key material.
	verifier := keyPair.Verifier()
	expected := recovery.ExpectedBinding{
		EnvironmentID:       op.Environment,
		AuthorityEpoch:      op.Epoch,
		ResourceIncarnation: op.ResourceIncarnation,
		OperationID:         op.OperationID,
		PredecessorRevision: protocol.NewRevisionNumber(0),
		PredecessorDigest:   digestOf(t, 3),
	}
	if err := recovery.VerifyPersistedCommitted(context.Background(), verifier, payload, expected); err != nil {
		t.Fatalf("independent verification of the persisted COMMITTED failed: %v", err)
	}

	// Verification succeeded -- resumption is safe. Contrast with T7/T8:
	// here the witness outcome is validated true, not assumed.
	resumed := epoch.TransitionOnWitnessOutcome(true)
	if resumed != epoch.StateActive {
		t.Fatalf("resumed state = %v, want StateActive", resumed)
	}
	if !resumed.RecoveryAllowed() || !resumed.RotationAllowed() || !resumed.FenceReleaseAllowed() || !resumed.PostgreSQLReconciliationAllowed() {
		t.Fatal("a verified, resumed epoch must permit all four authority-dependent actions")
	}
	if resumed.NewEpochRequired() {
		t.Fatal("a verified, resumed epoch must not require a new epoch")
	}

	// Ground truth cross-check.
	directClient := dialEmulator(t, emulatorAddr)
	verifySession, err := directClient.CreateSession(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	verifyTxn, err := directClient.BeginReadWrite(context.Background(), verifySession)
	if err != nil {
		t.Fatal(err)
	}
	row, found, err := directClient.ReadAuthorityHead(context.Background(), verifySession, verifyTxn, op.Environment.String(), op.ResourceIncarnation.String())
	directClient.Rollback(context.Background(), verifySession, verifyTxn)
	if err != nil {
		t.Fatal(err)
	}
	if !found || row.RevisionNumber != payload.RevisionNumber().Uint64() {
		t.Fatalf("ground truth revision mismatch: found=%v row=%+v payload_revision=%d", found, row, payload.RevisionNumber().Uint64())
	}
}

// TestProcessKillT10GCSCommittedPersistedBeforeAckMayResume is
// TestProcessKillT10CommittedPersistedBeforeAckMayResume with the GCS
// witness adapter substituted for the local filesystem witness -- the
// bounded ADR-043 GCS adapter, exercised against fake-gcs-server, in the
// exact same process-kill shape as the already-proven local/Spanner-only
// T10. Only the witness storage backend differs; the signing boundary,
// verification logic, and epoch decision are byte-for-byte the same frozen
// code.
func TestProcessKillT10GCSCommittedPersistedBeforeAckMayResume(t *testing.T) {
	op := newEmulatorOperation(t)
	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	witnessKey := "committed/" + op.OperationID.String()
	env := baseHelperEnv(t, op, 0, emulatorAddr, t.TempDir(), witnessKey, hex.EncodeToString(keyPair.PrivateKeyBytes()))
	env[helperEnvGCSEndpoint] = fakeGCSEndpointForTest
	env[helperEnvGCSBucket] = fakeGCSBucketForTest
	result := spawnHelperAndKillAfter(t, "t10gcs", env, "COMMITTED_PERSISTED")
	defer rollbackBestEffort(t, emulatorAddr, result.Session, result.TxnID)

	if !result.sawLine("COMMITTED_PERSISTED") {
		t.Fatal("expected to observe COMMITTED_PERSISTED before the kill")
	}
	if result.sawLine("ACKED") {
		t.Fatal("T10 requires the kill to land before the child could acknowledge completion")
	}

	client, err := gcswitness.NewClient(context.Background(),
		option.WithEndpoint(fakeGCSEndpointForTest),
		option.WithoutAuthentication(),
		option.WithHTTPClient(&http.Client{}),
	)
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	adapter := gcswitness.New(client, fakeGCSBucketForTest)

	raw, err := adapter.ReadExact(context.Background(), witnessKey)
	if err != nil {
		t.Fatalf("expected a persisted COMMITTED witness object in GCS: %v", err)
	}
	payload := deserializeCommittedPayload(t, raw)

	verifier := keyPair.Verifier()
	expected := recovery.ExpectedBinding{
		EnvironmentID:       op.Environment,
		AuthorityEpoch:      op.Epoch,
		ResourceIncarnation: op.ResourceIncarnation,
		OperationID:         op.OperationID,
		PredecessorRevision: protocol.NewRevisionNumber(0),
		PredecessorDigest:   digestOf(t, 3),
	}
	if err := recovery.VerifyPersistedCommitted(context.Background(), verifier, payload, expected); err != nil {
		t.Fatalf("independent verification of the GCS-persisted COMMITTED failed: %v", err)
	}

	resumed := epoch.TransitionOnWitnessOutcome(true)
	if resumed != epoch.StateActive {
		t.Fatalf("resumed state = %v, want StateActive", resumed)
	}
	if resumed.NewEpochRequired() {
		t.Fatal("a verified, resumed epoch must not require a new epoch")
	}
}

// TestGCSWitnessUnsignedFabricatedWrongKeyTamperedNeverActivates proves,
// against the real GCS-emulator-backed adapter, that no forged variant of a
// persisted COMMITTED can ever activate: absent signature, fabricated
// signature, wrong signing key, and content-tampered-but-originally-signed
// are all independently rejected by the same frozen recovery.VerifyPersistedCommitted
// logic already proven against the local witness -- this test exists to
// confirm the GCS storage substitution changes nothing about that outcome.
func TestGCSWitnessUnsignedFabricatedWrongKeyTamperedNeverActivates(t *testing.T) {
	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	client := dialEmulator(t, emulatorAddr)
	request, _, _ := commitRequestFor(t, client, operation)
	accepted, classification, err := completeRawCommit(context.Background(), client.Raw(), request, operation, nil)
	if err != nil || classification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("setup: classification=%v err=%v", classification, err)
	}

	genuineKeyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	genuinePayload, err := buildCommittedPayload(context.Background(), genuineKeyPair.Signer(), accepted)
	if err != nil {
		t.Fatal(err)
	}

	gcsClient, err := gcswitness.NewClient(context.Background(),
		option.WithEndpoint(fakeGCSEndpointForTest),
		option.WithoutAuthentication(),
		option.WithHTTPClient(&http.Client{}),
	)
	if err != nil {
		t.Fatal(err)
	}
	defer gcsClient.Close()
	adapter := gcswitness.New(gcsClient, fakeGCSBucketForTest)

	expected := recovery.ExpectedBinding{
		EnvironmentID:       op.Environment,
		AuthorityEpoch:      op.Epoch,
		ResourceIncarnation: op.ResourceIncarnation,
		OperationID:         op.OperationID,
		PredecessorRevision: operation.ExpectedRevision(),
		PredecessorDigest:   operation.PreparedDigest(),
	}

	scenarios := map[string]protocol.CommittedPayload{
		"unsigned": protocol.NewCommittedPayload(
			genuinePayload.EnvironmentID(), genuinePayload.AuthorityEpoch(), genuinePayload.ResourceIncarnation(),
			genuinePayload.OperationID(), genuinePayload.RevisionNumber(), genuinePayload.PredecessorRevision(),
			genuinePayload.PredecessorDigest(), genuinePayload.StateDigest(), genuinePayload.CommitTimestamp(), nil,
		),
		"fabricated": genuinePayload.WithSignature([]byte("not-a-real-signature-at-all")),
	}
	otherKeyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	wrongKeyDigest, err := genuinePayload.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	wrongKeySig, err := otherKeyPair.Signer().SignCommittedDigest(context.Background(), wrongKeyDigest)
	if err != nil {
		t.Fatal(err)
	}
	scenarios["wrong-key"] = genuinePayload.WithSignature(wrongKeySig)

	tamperedStateDigest := digestOf(t, 200)
	tampered := protocol.NewCommittedPayload(
		genuinePayload.EnvironmentID(), genuinePayload.AuthorityEpoch(), genuinePayload.ResourceIncarnation(),
		genuinePayload.OperationID(), genuinePayload.RevisionNumber(), genuinePayload.PredecessorRevision(),
		genuinePayload.PredecessorDigest(), tamperedStateDigest, genuinePayload.CommitTimestamp(),
		genuinePayload.WriterSignature(), // reuse the genuine signature over the ORIGINAL content
	)
	scenarios["tampered-content-original-signature"] = tampered

	for name, payload := range scenarios {
		t.Run(name, func(t *testing.T) {
			serialized, err := serializeCommittedPayload(payload)
			if err != nil {
				t.Fatal(err)
			}
			key := "forged/" + op.OperationID.String() + "-" + name
			if _, err := adapter.CreateExactIfAbsent(context.Background(), key, serialized); err != nil {
				t.Fatal(err)
			}
			raw, err := adapter.ReadExact(context.Background(), key)
			if err != nil {
				t.Fatal(err)
			}
			roundTripped := deserializeCommittedPayload(t, raw)
			err = recovery.VerifyPersistedCommitted(context.Background(), genuineKeyPair.Verifier(), roundTripped, expected)
			if err == nil {
				t.Fatalf("%s: expected verification to fail, activation must never occur", name)
			}
		})
	}
}

const (
	fakeGCSEndpointForTest = "http://localhost:4443/storage/v1/"
	fakeGCSBucketForTest   = "adr043-witness-test"
)

// TestGCSWitnessBindingMismatchNeverActivates proves a genuinely,
// correctly signed COMMITTED persisted in GCS still fails verification if
// the caller's expected binding (environment/epoch/resource/operation/
// predecessor) does not match -- a correct signature over the WRONG
// expectation must never activate.
func TestGCSWitnessBindingMismatchNeverActivates(t *testing.T) {
	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	client := dialEmulator(t, emulatorAddr)
	request, _, _ := commitRequestFor(t, client, operation)
	accepted, classification, err := completeRawCommit(context.Background(), client.Raw(), request, operation, nil)
	if err != nil || classification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("setup: classification=%v err=%v", classification, err)
	}
	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	genuinePayload, err := buildCommittedPayload(context.Background(), keyPair.Signer(), accepted)
	if err != nil {
		t.Fatal(err)
	}
	serialized, err := serializeCommittedPayload(genuinePayload)
	if err != nil {
		t.Fatal(err)
	}

	gcsClient, err := gcswitness.NewClient(context.Background(),
		option.WithEndpoint(fakeGCSEndpointForTest),
		option.WithoutAuthentication(),
		option.WithHTTPClient(&http.Client{}),
	)
	if err != nil {
		t.Fatal(err)
	}
	defer gcsClient.Close()
	adapter := gcswitness.New(gcsClient, fakeGCSBucketForTest)
	key := "binding-mismatch/" + op.OperationID.String()
	if _, err := adapter.CreateExactIfAbsent(context.Background(), key, serialized); err != nil {
		t.Fatal(err)
	}
	raw, err := adapter.ReadExact(context.Background(), key)
	if err != nil {
		t.Fatal(err)
	}
	roundTripped := deserializeCommittedPayload(t, raw)

	// A DIFFERENT, unrelated operation's expected binding.
	otherOp := newEmulatorOperation(t)
	wrongExpected := recovery.ExpectedBinding{
		EnvironmentID:       otherOp.Environment,
		AuthorityEpoch:      otherOp.Epoch,
		ResourceIncarnation: otherOp.ResourceIncarnation,
		OperationID:         otherOp.OperationID,
		PredecessorRevision: operation.ExpectedRevision(),
		PredecessorDigest:   operation.PreparedDigest(),
	}
	err = recovery.VerifyPersistedCommitted(context.Background(), keyPair.Verifier(), roundTripped, wrongExpected)
	if err == nil {
		t.Fatal("a genuinely signed COMMITTED must not verify against a mismatched expected binding")
	}
}

// TestGCSMalformedObjectFailsClosed proves an object at the deterministic
// key that is not even well-formed COMMITTED JSON (corrupted bytes, never a
// product of this codebase's own serialization) is rejected during
// deserialization rather than silently accepted or partially trusted.
func TestGCSMalformedObjectFailsClosed(t *testing.T) {
	gcsClient, err := gcswitness.NewClient(context.Background(),
		option.WithEndpoint(fakeGCSEndpointForTest),
		option.WithoutAuthentication(),
		option.WithHTTPClient(&http.Client{}),
	)
	if err != nil {
		t.Fatal(err)
	}
	defer gcsClient.Close()
	adapter := gcswitness.New(gcsClient, fakeGCSBucketForTest)

	key := "malformed/" + t.Name()
	malformed := []byte(`{"environment_id": "staging", "this is not valid COMMITTED JSON at all`)
	if _, err := adapter.CreateExactIfAbsent(context.Background(), key, malformed); err != nil {
		t.Fatal(err)
	}
	raw, err := adapter.ReadExact(context.Background(), key)
	if err != nil {
		t.Fatal(err)
	}
	if string(raw) != string(malformed) {
		t.Fatal("ReadExact must return the raw bytes unmodified even when they are malformed -- deserialization is the caller's responsibility, not the storage layer's")
	}
	// Deserialization must fail closed rather than panic or silently
	// produce a zero-value payload that could be mistaken for a genuine one.
	var dto committedPayloadDTO
	if err := json.Unmarshal(raw, &dto); err == nil {
		t.Fatal("expected deserialization of malformed bytes to fail")
	}
}
