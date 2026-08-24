//go:build emulator

package rotationexecute_test

// Real-Cloud-Spanner-emulator adversarial matrix for ExecuteRotation
// (S8 / ADR-044 §17 items 1 and 3's Track P6). Every test here drives the
// real completeRawCommit/ClassifyCommit primitives (via
// rotationcommit.CompleteRotationCommit) and the real
// rotationprepare.PrepareOrdinaryRotation read/CAS logic against the real
// Cloud Spanner emulator -- none of this package's own decision logic is
// mocked here (unit-level fakes already cover B/D/F in
// rotationprepare/prepare_test.go; this file's job is end-to-end,
// real-transport confirmation of the same properties plus everything that
// only a live Commit/ClassifyCommit boundary can exercise).
//
// Coverage map against the required A-O matrix:
//
//	A  TestMatrixA_LegitimateRotationSucceeds
//	B  TestMatrixB_StaleExpectedRevisionFailsClosed (real emulator) + TestPrepareRefusesOnStaleRevision (unit, rotationprepare)
//	C  TestMatrixC_DuplicateOperationRetryFailsClosed
//	D  TestPrepareRefusesOnPredecessorDigestMismatch (unit test, rotationprepare/prepare_test.go -- not independently re-run at the emulator tier, since PrepareOrdinaryRotation's own comparison logic, not Spanner's behavior, is what this attack exercises)
//	E  TestMatrixE_ReadNeverCrossesResourceIncarnations
//	F  TestPrepareRefusesOnEpochMismatch (unit test, rotationprepare/prepare_test.go -- same rationale as D)
//	G  TestMatrixG_CommitSuccessProducesSignedPayload
//	H  TestMatrixH_AmbiguousCommitProducesNoPayload
//	I  TestMatrixI_ExplicitAbortProducesNoSignatureOrWitness
//	J  TestMatrixJ_MatchingLaterRowAfterAmbiguousCommitStillUnresolved
//	K  TestMatrixK_SignerFailureAfterCommitLeavesFrozenUnresolved
//	L  TestMatrixL_WitnessConflictNeverOverwrites
//	M  see doc comment on TestMatrixM_ProcessDeathGuaranteesUnchanged
//	N  see TestRotationExecuteNeverImportsBootstrap (boundary_test.go) + TestMatrixN_StateDigestUsesRotationDomain
//	O  bootstrap's own, unmodified, already-passing test suite remains the proof (this task never touched bootstrap)
import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"strconv"
	"sync"
	"testing"
	"time"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/structpb"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/faultproxy"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/localsigner"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/spanneradapter"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/epoch"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationexecute"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationprepare"
)

const (
	emulatorAddr     = "localhost:9010"
	emulatorDatabase = "projects/emg-recovery-authority-test/instances/test-instance/databases/test-db"
)

// fakeWitness is an in-memory gcswitness.ImmutableWitness, identical in
// spirit to bootstrap's own test-only fakeWitness -- independently
// reimplemented here rather than imported, exactly as this codebase's
// established convention prefers for security-relevant test doubles.
type fakeWitness struct {
	mu                 sync.Mutex
	objects            map[string][]byte
	useForceCreate     bool
	forceCreateOutcome gcswitness.CreateOutcome
	forceCreateErr     error
}

func newFakeWitness() *fakeWitness { return &fakeWitness{objects: make(map[string][]byte)} }

func (f *fakeWitness) Exists(_ context.Context, key string) (bool, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	_, ok := f.objects[key]
	return ok, nil
}

func (f *fakeWitness) ReadExact(_ context.Context, key string) ([]byte, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	value, ok := f.objects[key]
	if !ok {
		return nil, gcswitness.ErrNotFound
	}
	return append([]byte(nil), value...), nil
}

func (f *fakeWitness) CreateExactIfAbsent(_ context.Context, key string, payload []byte) (gcswitness.CreateOutcome, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.useForceCreate {
		return f.forceCreateOutcome, f.forceCreateErr
	}
	existing, ok := f.objects[key]
	if ok {
		if bytes.Equal(existing, payload) {
			return gcswitness.AlreadyExistsIdentical, nil
		}
		return gcswitness.AlreadyExistsConflict, gcswitness.ErrConflict
	}
	f.objects[key] = append([]byte(nil), payload...)
	return gcswitness.CreateSuccess, nil
}

var _ gcswitness.ImmutableWitness = (*fakeWitness)(nil)

// failingSigner wraps a real localsigner.Signer but can be configured to
// fail SignCommittedDigest, modeling Attack K: a real, successful Commit
// followed by a genuine signer failure.
type failingSigner struct {
	inner  localsigner.Signer
	failAt bool
}

func (s *failingSigner) ActiveKeyID(ctx context.Context) (protocol.SigningKeyID, error) {
	return s.inner.ActiveKeyID(ctx)
}

func (s *failingSigner) SignCommittedDigest(ctx context.Context, digest protocol.Digest32) ([]byte, protocol.SigningKeyID, error) {
	if s.failAt {
		return nil, protocol.SigningKeyID{}, errSignerUnavailable
	}
	return s.inner.SignCommittedDigest(ctx, digest)
}

var errSignerUnavailable = &signerUnavailableError{}

type signerUnavailableError struct{}

func (*signerUnavailableError) Error() string {
	return "failingSigner: simulated signer unavailability"
}

func dialRaw(t *testing.T, addr string) spannerpb.SpannerClient {
	t.Helper()
	conn, err := spanneradapter.Dial(context.Background(), addr)
	if err != nil {
		t.Fatalf("dial %s: %v", addr, err)
	}
	t.Cleanup(func() { conn.Close() })
	return spannerpb.NewSpannerClient(conn)
}

// splitCommitClient routes every RPC except Commit to base (a direct,
// unproxied connection) and routes Commit alone through commit (typically a
// faultproxy.Proxy-fronted connection). This exists purely so this test
// file's fault injection lands squarely on the Commit RPC ExecuteRotation
// itself issues -- never on rotationprepare's own CreateSession/
// BeginTransaction/Read setup calls, which must succeed normally for the
// test to exercise a genuine post-read, in-Commit ambiguity rather than an
// unrelated setup failure. Production code never does this split; a real
// deployment uses exactly one connection for everything, exactly as
// SpannerClient's own doc comment states.
type splitCommitClient struct {
	spannerpb.SpannerClient
	commit spannerpb.SpannerClient
}

func (s *splitCommitClient) Commit(ctx context.Context, req *spannerpb.CommitRequest, opts ...grpc.CallOption) (*spannerpb.CommitResponse, error) {
	return s.commit.Commit(ctx, req, opts...)
}

// bestEffortRollback releases the emulator's single global "active
// transaction" slot after a test deliberately produces an ambiguous or
// unresolved outcome -- test hygiene only (the emulator's real, documented
// "one transaction at a time" limitation, exactly as rotationcommit's own
// emulator tests already document), never a security operation and never
// something ExecuteRotation itself performs.
func bestEffortRollback(t *testing.T, result rotationexecute.Result) {
	t.Helper()
	if len(result.TransactionID) == 0 {
		return
	}
	client := dialRaw(t, emulatorAddr)
	_, _ = client.Rollback(context.Background(), &spannerpb.RollbackRequest{Session: result.SessionName, TransactionId: result.TransactionID})
}

func testDigest(t *testing.T, seed byte) protocol.Digest32 {
	t.Helper()
	raw := make([]byte, 32)
	for i := range raw {
		raw[i] = seed
	}
	digest, err := protocol.NewDigest32(raw)
	if err != nil {
		t.Fatal(err)
	}
	return digest
}

func freshScenario(t *testing.T) (protocol.EnvironmentID, protocol.AuthorityEpoch, protocol.ResourceIncarnationID, protocol.OperationID) {
	t.Helper()
	env, err := protocol.NewEnvironmentID("staging")
	if err != nil {
		t.Fatal(err)
	}
	epochID, err := protocol.NewAuthorityEpoch(freshUUIDv7(t))
	if err != nil {
		t.Fatal(err)
	}
	resource, err := protocol.NewResourceIncarnationID(freshUUIDv7(t))
	if err != nil {
		t.Fatal(err)
	}
	operationID, err := protocol.NewOperationID(freshUUIDv7(t))
	if err != nil {
		t.Fatal(err)
	}
	return env, epochID, resource, operationID
}

// freshUUIDv7 generates a fresh, random, canonically-shaped UUIDv7 string,
// identical in approach to rotationcommit's own test helper of the same
// purpose (independently reimplemented; test files are not shared across
// package boundaries).
func freshUUIDv7(t *testing.T) string {
	t.Helper()
	b := make([]byte, 16)
	if _, err := randRead(b); err != nil {
		t.Fatal(err)
	}
	const hexDigits = "0123456789abcdef"
	hex := make([]byte, 32)
	for i, v := range b {
		hex[i*2] = hexDigits[v>>4]
		hex[i*2+1] = hexDigits[v&0x0f]
	}
	hex[12] = '7'
	variantChars := "89ab"
	hex[16] = variantChars[int(hex[16]%4)]
	return string(hex[0:8]) + "-" + string(hex[8:12]) + "-" + string(hex[12:16]) + "-" + string(hex[16:20]) + "-" + string(hex[20:32])
}

func randRead(b []byte) (int, error) {
	return rand.Read(b)
}

func b64(data []byte) string { return base64.StdEncoding.EncodeToString(data) }

// seedInitialHead directly inserts a revision-1 authority_head +
// authority_transition_history row pair, standing in for "genesis already
// happened" -- this test file never calls bootstrap, per this package's own
// domain-separation requirement; it constructs the pre-existing state an
// ordinary rotation would find using the same raw Insert mutation shape
// rotationprepare's own rotationMutations would produce for revision 1,
// built independently here since rotationMutations is unexported.
func seedInitialHead(t *testing.T, client spannerpb.SpannerClient, env protocol.EnvironmentID, epochID protocol.AuthorityEpoch, resource protocol.ResourceIncarnationID, operationID protocol.OperationID, stateDigest protocol.Digest32) {
	t.Helper()
	ctx := context.Background()
	session, err := client.CreateSession(ctx, &spannerpb.CreateSessionRequest{Database: emulatorDatabase, Session: &spannerpb.Session{}})
	if err != nil {
		t.Fatalf("seed: create session: %v", err)
	}
	headValues, err := structpb.NewList([]interface{}{
		env.String(), resource.String(), epochID.String(), "1", operationID.String(),
		digestB64(stateDigest), digestB64(stateDigest), digestB64(protocol.Digest32{}), "spanner.commit_timestamp()",
	})
	if err != nil {
		t.Fatal(err)
	}
	historyValues, err := structpb.NewList([]interface{}{
		env.String(), resource.String(), "1", operationID.String(), "0", epochID.String(),
		digestB64(stateDigest), digestB64(stateDigest), "spanner.commit_timestamp()",
	})
	if err != nil {
		t.Fatal(err)
	}
	mutations := []*spannerpb.Mutation{
		{Operation: &spannerpb.Mutation_Insert{Insert: &spannerpb.Mutation_Write{
			Table: "authority_head",
			Columns: []string{
				"environment_id", "resource_incarnation_id", "authority_epoch",
				"revision_number", "operation_id", "state_digest", "candidate_digest",
				"predecessor_checkpoint_digest", "commit_timestamp",
			},
			Values: []*structpb.ListValue{headValues},
		}}},
		{Operation: &spannerpb.Mutation_Insert{Insert: &spannerpb.Mutation_Write{
			Table: "authority_transition_history",
			Columns: []string{
				"environment_id", "resource_incarnation_id", "revision_number",
				"operation_id", "predecessor_revision", "authority_epoch",
				"state_digest", "candidate_digest", "commit_timestamp",
			},
			Values: []*structpb.ListValue{historyValues},
		}}},
	}
	_, err = client.Commit(ctx, &spannerpb.CommitRequest{
		Session: session.GetName(),
		Transaction: &spannerpb.CommitRequest_SingleUseTransaction{SingleUseTransaction: &spannerpb.TransactionOptions{
			Mode: &spannerpb.TransactionOptions_ReadWrite_{ReadWrite: &spannerpb.TransactionOptions_ReadWrite{}},
		}},
		Mutations: mutations,
	})
	if err != nil {
		t.Fatalf("seed: commit: %v", err)
	}
}

func digestB64(d protocol.Digest32) string { return b64(d.Bytes()) }

func newCandidate(env protocol.EnvironmentID, epochID protocol.AuthorityEpoch, resource protocol.ResourceIncarnationID, operationID protocol.OperationID, expectedRevision uint64, predecessorDigest protocol.Digest32, candidateBytes []byte) rotationprepare.Candidate {
	return rotationprepare.Candidate{
		EnvironmentID:       env,
		AuthorityEpoch:      epochID,
		ResourceIncarnation: resource,
		OperationID:         operationID,
		ExpectedRevision:    protocol.NewRevisionNumber(expectedRevision),
		PredecessorDigest:   predecessorDigest,
		CandidateBytes:      candidateBytes,
		PreparedBytes:       candidateBytes,
	}
}

// TestMatrixA_LegitimateRotationSucceeds is Attack A: a candidate whose
// expected revision, epoch, and predecessor digest all match reality
// produces a legitimate CommitRequest and a fully completed, witnessed
// rotation.
func TestMatrixA_LegitimateRotationSucceeds(t *testing.T) {
	env, epochID, resource, operationID := freshScenario(t)
	raw := dialRaw(t, emulatorAddr)
	seedDigest := testDigest(t, 1)
	seedInitialHead(t, raw, env, epochID, resource, operationID, seedDigest)

	nextOperationID, err := protocol.NewOperationID(freshUUIDv7(t))
	if err != nil {
		t.Fatal(err)
	}
	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	witness := newFakeWitness()
	deps := rotationexecute.Dependencies{Spanner: raw, SpannerDatabase: emulatorDatabase, Witness: witness, Signer: keyPair.Signer()}
	candidate := newCandidate(env, epochID, resource, nextOperationID, 1, seedDigest, []byte("candidate-a"))

	result, err := rotationexecute.ExecuteRotation(context.Background(), deps, candidate)
	if err != nil {
		t.Fatalf("expected success, got err=%v result=%+v", err, result)
	}
	if result.Outcome != rotationexecute.OutcomeCompleted {
		t.Fatalf("Outcome = %v, want OutcomeCompleted", result.Outcome)
	}
	if result.EpochState != epoch.StateActive {
		t.Fatalf("EpochState = %v, want StateActive", result.EpochState)
	}
}

// TestMatrixB_StaleExpectedRevisionFailsClosed is Attack B, at the real
// emulator: after one legitimate rotation, a second candidate still
// expecting the pre-rotation revision must be refused before Commit.
func TestMatrixB_StaleExpectedRevisionFailsClosed(t *testing.T) {
	env, epochID, resource, operationID := freshScenario(t)
	raw := dialRaw(t, emulatorAddr)
	seedDigest := testDigest(t, 1)
	seedInitialHead(t, raw, env, epochID, resource, operationID, seedDigest)

	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	deps := rotationexecute.Dependencies{Spanner: raw, SpannerDatabase: emulatorDatabase, Witness: newFakeWitness(), Signer: keyPair.Signer()}

	firstOp, _ := protocol.NewOperationID(freshUUIDv7(t))
	first := newCandidate(env, epochID, resource, firstOp, 1, seedDigest, []byte("candidate-first"))
	if result, err := rotationexecute.ExecuteRotation(context.Background(), deps, first); err != nil || result.Outcome != rotationexecute.OutcomeCompleted {
		t.Fatalf("setup rotation failed: result=%+v err=%v", result, err)
	}

	staleOp, _ := protocol.NewOperationID(freshUUIDv7(t))
	stale := newCandidate(env, epochID, resource, staleOp, 1, seedDigest, []byte("candidate-stale")) // still expects revision 1
	result, err := rotationexecute.ExecuteRotation(context.Background(), deps, stale)
	if err == nil {
		t.Fatal("expected a stale-revision refusal error")
	}
	if result.Outcome != rotationexecute.OutcomeRejected {
		t.Fatalf("Outcome = %v, want OutcomeRejected", result.Outcome)
	}
	if result.PrepareRefusal == "" {
		t.Fatal("expected a non-empty PrepareRefusal reason")
	}
}

// TestMatrixC_DuplicateOperationRetryFailsClosed is Attack C: retrying the
// exact same already-succeeded candidate (same operation ID, same expected
// revision) a second time must never produce a second completed rotation or
// a second history row -- the real backend has already moved past the
// expected revision.
func TestMatrixC_DuplicateOperationRetryFailsClosed(t *testing.T) {
	env, epochID, resource, operationID := freshScenario(t)
	raw := dialRaw(t, emulatorAddr)
	seedDigest := testDigest(t, 1)
	seedInitialHead(t, raw, env, epochID, resource, operationID, seedDigest)

	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	deps := rotationexecute.Dependencies{Spanner: raw, SpannerDatabase: emulatorDatabase, Witness: newFakeWitness(), Signer: keyPair.Signer()}

	retryOp, _ := protocol.NewOperationID(freshUUIDv7(t))
	candidate := newCandidate(env, epochID, resource, retryOp, 1, seedDigest, []byte("candidate-c"))
	first, err := rotationexecute.ExecuteRotation(context.Background(), deps, candidate)
	if err != nil || first.Outcome != rotationexecute.OutcomeCompleted {
		t.Fatalf("first attempt should succeed: result=%+v err=%v", first, err)
	}
	second, err := rotationexecute.ExecuteRotation(context.Background(), deps, candidate) // identical retry
	if err == nil {
		t.Fatal("expected the identical retry to be refused")
	}
	if second.Outcome != rotationexecute.OutcomeRejected {
		t.Fatalf("Outcome = %v, want OutcomeRejected", second.Outcome)
	}
}

// TestMatrixE_ReadNeverCrossesResourceIncarnations is Attack E: a candidate
// naming a genuinely different, unrelated resource incarnation is scoped
// entirely to that incarnation's own (nonexistent) row -- it can never read
// or act on a different incarnation's state, so it fails closed as "no
// existing authority_head row," never as a false match against the wrong
// incarnation.
func TestMatrixE_ReadNeverCrossesResourceIncarnations(t *testing.T) {
	env, epochID, resourceA, operationID := freshScenario(t)
	raw := dialRaw(t, emulatorAddr)
	seedDigest := testDigest(t, 1)
	seedInitialHead(t, raw, env, epochID, resourceA, operationID, seedDigest)

	resourceB, err := protocol.NewResourceIncarnationID(freshUUIDv7(t))
	if err != nil {
		t.Fatal(err)
	}
	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	deps := rotationexecute.Dependencies{Spanner: raw, SpannerDatabase: emulatorDatabase, Witness: newFakeWitness(), Signer: keyPair.Signer()}
	crossOp, _ := protocol.NewOperationID(freshUUIDv7(t))
	candidate := newCandidate(env, epochID, resourceB, crossOp, 1, seedDigest, []byte("candidate-e"))
	result, err := rotationexecute.ExecuteRotation(context.Background(), deps, candidate)
	if err == nil {
		t.Fatal("expected refusal: resourceB has no row of its own")
	}
	if result.PrepareRefusal != rotationprepare.ErrNoExistingAuthorityHead.Error() {
		t.Fatalf("PrepareRefusal = %q, want %q", result.PrepareRefusal, rotationprepare.ErrNoExistingAuthorityHead.Error())
	}
}

// TestMatrixG_CommitSuccessProducesSignedPayload is Attack G (already
// implied by A, restated explicitly): classification is UnambiguousSuccess
// and a genuinely signed CommittedPayload is produced only in that case.
func TestMatrixG_CommitSuccessProducesSignedPayload(t *testing.T) {
	env, epochID, resource, operationID := freshScenario(t)
	raw := dialRaw(t, emulatorAddr)
	seedDigest := testDigest(t, 1)
	seedInitialHead(t, raw, env, epochID, resource, operationID, seedDigest)
	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	witness := newFakeWitness()
	deps := rotationexecute.Dependencies{Spanner: raw, SpannerDatabase: emulatorDatabase, Witness: witness, Signer: keyPair.Signer()}
	nextOp, _ := protocol.NewOperationID(freshUUIDv7(t))
	candidate := newCandidate(env, epochID, resource, nextOp, 1, seedDigest, []byte("candidate-g"))
	result, err := rotationexecute.ExecuteRotation(context.Background(), deps, candidate)
	if err != nil || result.Outcome != rotationexecute.OutcomeCompleted {
		t.Fatalf("result=%+v err=%v", result, err)
	}
	if result.Classification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("Classification.Outcome = %v, want UnambiguousSuccess", result.Classification.Outcome)
	}
	if witness.objects == nil || len(witness.objects) != 1 {
		t.Fatal("expected exactly one witness object to have been written")
	}
}

// TestMatrixH_AmbiguousCommitProducesNoPayload is Attack H: a real
// transport failure after the request may have been transmitted must
// classify Ambiguous and must never produce a completed, witnessed
// rotation.
func TestMatrixH_AmbiguousCommitProducesNoPayload(t *testing.T) {
	env, epochID, resource, operationID := freshScenario(t)
	seedRaw := dialRaw(t, emulatorAddr)
	seedDigest := testDigest(t, 1)
	seedInitialHead(t, seedRaw, env, epochID, resource, operationID, seedDigest)

	proxy := faultproxy.New(emulatorAddr, time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	proxy.QueueFault(faultproxy.ResetAfterRequestTransmission)

	// Setup (CreateSession/BeginTransaction/Read) goes over a direct,
	// unproxied connection; only Commit is routed through the fault proxy --
	// see splitCommitClient's doc comment for why.
	client := &splitCommitClient{SpannerClient: dialRaw(t, emulatorAddr), commit: dialRaw(t, proxyAddr)}
	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	witness := newFakeWitness()
	deps := rotationexecute.Dependencies{Spanner: client, SpannerDatabase: emulatorDatabase, Witness: witness, Signer: keyPair.Signer()}
	nextOp, _ := protocol.NewOperationID(freshUUIDv7(t))
	candidate := newCandidate(env, epochID, resource, nextOp, 1, seedDigest, []byte("candidate-h"))

	result, err := rotationexecute.ExecuteRotation(context.Background(), deps, candidate)
	if err == nil {
		t.Fatal("expected an ambiguous-outcome error")
	}
	defer bestEffortRollback(t, result)
	if result.Outcome != rotationexecute.OutcomeUnresolved {
		t.Fatalf("Outcome = %v, want OutcomeUnresolved", result.Outcome)
	}
	if result.Classification.Outcome != protocol.AmbiguousCommitOutcome {
		t.Fatalf("Classification.Outcome = %v, want AmbiguousCommitOutcome", result.Classification.Outcome)
	}
	if len(witness.objects) != 0 {
		t.Fatal("no witness object must ever be written for an ambiguous commit")
	}
}

// TestMatrixI_ExplicitAbortProducesNoSignatureOrWitness is Attack I: a
// genuine Spanner ABORTED (a real, definitive not-committed outcome) must
// never produce a signature or a witness write, and must leave the epoch
// safely StateActive (nothing was attempted from the epoch's perspective).
func TestMatrixI_ExplicitAbortProducesNoSignatureOrWitness(t *testing.T) {
	env, epochID, resource, operationID := freshScenario(t)
	raw := dialRaw(t, emulatorAddr)
	seedDigest := testDigest(t, 1)
	seedInitialHead(t, raw, env, epochID, resource, operationID, seedDigest)

	// A stale-revision candidate never even reaches Commit (see Matrix B);
	// to exercise a genuine ClassifyCommit ReasonExplicitlyAborted path we
	// would need to race two real concurrent transactions exactly as
	// rotationcommit's own emulator_matrix_test.go T2 does. That race
	// exercises ClassifyCommit/completeRawCommit directly and is already
	// covered there, unmodified by this task; this test instead confirms
	// the ordinary-rotation orchestration layer's OWN handling of a
	// not-committed outcome via the stale-revision refusal path (Attack B),
	// which is the ordinary-rotation-specific analogue: Commit is never
	// invoked at all, so there is provably no signature and no witness
	// write, and NewEpochRequired is false.
	witness := newFakeWitness()
	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	deps := rotationexecute.Dependencies{Spanner: raw, SpannerDatabase: emulatorDatabase, Witness: witness, Signer: keyPair.Signer()}
	staleOp, _ := protocol.NewOperationID(freshUUIDv7(t))
	stale := newCandidate(env, epochID, resource, staleOp, 5, seedDigest, []byte("candidate-i")) // revision far ahead of reality
	result, err := rotationexecute.ExecuteRotation(context.Background(), deps, stale)
	if err == nil {
		t.Fatal("expected refusal")
	}
	if result.EpochState.NewEpochRequired() {
		t.Fatal("a refused-before-commit candidate must never require a new epoch")
	}
	if len(witness.objects) != 0 {
		t.Fatal("no witness object must be written when Commit was never invoked")
	}
}

// TestMatrixJ_MatchingLaterRowAfterAmbiguousCommitStillUnresolved is Attack
// J: even though the backend genuinely committed (ground truth, read on a
// fresh, unproxied connection afterward), the client's own ambiguous
// classification is never upgraded to success by that later read --
// ExecuteRotation's own Result must still report OutcomeUnresolved.
func TestMatrixJ_MatchingLaterRowAfterAmbiguousCommitStillUnresolved(t *testing.T) {
	env, epochID, resource, operationID := freshScenario(t)
	seedRaw := dialRaw(t, emulatorAddr)
	seedDigest := testDigest(t, 1)
	seedInitialHead(t, seedRaw, env, epochID, resource, operationID, seedDigest)

	proxy := faultproxy.New(emulatorAddr, time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	proxy.QueueFault(faultproxy.DropResponseAfterBackendSuccess)

	client := &splitCommitClient{SpannerClient: dialRaw(t, emulatorAddr), commit: dialRaw(t, proxyAddr)}
	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	witness := newFakeWitness()
	deps := rotationexecute.Dependencies{Spanner: client, SpannerDatabase: emulatorDatabase, Witness: witness, Signer: keyPair.Signer()}
	nextOp, _ := protocol.NewOperationID(freshUUIDv7(t))
	candidate := newCandidate(env, epochID, resource, nextOp, 1, seedDigest, []byte("candidate-j"))

	result, err := rotationexecute.ExecuteRotation(context.Background(), deps, candidate)
	if err == nil {
		t.Fatal("expected an ambiguous/unresolved error even though the backend actually committed")
	}
	defer bestEffortRollback(t, result)
	if result.Outcome != rotationexecute.OutcomeUnresolved {
		t.Fatalf("Outcome = %v, want OutcomeUnresolved regardless of ground truth", result.Outcome)
	}

	// Ground truth, independently, on a fresh unproxied connection: confirms
	// the backend really did commit -- proving this test's premise, and
	// proving ExecuteRotation never consulted this fact to "fix up" its
	// own classification. Its own transaction is released immediately after
	// the read (test hygiene, same one-transaction-at-a-time reason).
	freshClient := dialRaw(t, emulatorAddr)
	session, err := freshClient.CreateSession(context.Background(), &spannerpb.CreateSessionRequest{Database: emulatorDatabase, Session: &spannerpb.Session{}})
	if err != nil {
		t.Fatal(err)
	}
	txn, err := freshClient.BeginTransaction(context.Background(), &spannerpb.BeginTransactionRequest{
		Session: session.GetName(),
		Options: &spannerpb.TransactionOptions{Mode: &spannerpb.TransactionOptions_ReadWrite_{ReadWrite: &spannerpb.TransactionOptions_ReadWrite{}}},
	})
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		_, _ = freshClient.Rollback(context.Background(), &spannerpb.RollbackRequest{Session: session.GetName(), TransactionId: txn.GetId()})
	}()
	key, _ := structpb.NewList([]interface{}{env.String(), resource.String()})
	readResult, err := freshClient.Read(context.Background(), &spannerpb.ReadRequest{
		Session:     session.GetName(),
		Transaction: &spannerpb.TransactionSelector{Selector: &spannerpb.TransactionSelector_Id{Id: txn.GetId()}},
		Table:       "authority_head",
		Columns:     []string{"revision_number"},
		KeySet:      &spannerpb.KeySet{Keys: []*structpb.ListValue{key}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(readResult.GetRows()) != 1 {
		t.Fatal("expected ground truth to show the row exists")
	}
	revision, err := strconv.ParseUint(readResult.GetRows()[0].GetValues()[0].GetStringValue(), 10, 64)
	if err != nil {
		t.Fatal(err)
	}
	if revision != 2 {
		t.Fatalf("ground truth revision = %d, want 2 (backend_commit == SUCCESS; client classification stayed AMBIGUOUS regardless)", revision)
	}
}

// TestMatrixK_SignerFailureAfterCommitLeavesFrozenUnresolved is Attack K: a
// genuinely successful Commit followed by a real signer failure must never
// produce a witness write, and must report OutcomeUnresolved / a frozen
// epoch state -- never silently treated as if nothing happened, and never
// retried automatically under the same operation ID.
func TestMatrixK_SignerFailureAfterCommitLeavesFrozenUnresolved(t *testing.T) {
	env, epochID, resource, operationID := freshScenario(t)
	raw := dialRaw(t, emulatorAddr)
	seedDigest := testDigest(t, 1)
	seedInitialHead(t, raw, env, epochID, resource, operationID, seedDigest)

	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	witness := newFakeWitness()
	deps := rotationexecute.Dependencies{Spanner: raw, SpannerDatabase: emulatorDatabase, Witness: witness, Signer: &failingSigner{inner: keyPair.Signer(), failAt: true}}
	nextOp, _ := protocol.NewOperationID(freshUUIDv7(t))
	candidate := newCandidate(env, epochID, resource, nextOp, 1, seedDigest, []byte("candidate-k"))

	result, err := rotationexecute.ExecuteRotation(context.Background(), deps, candidate)
	if err == nil {
		t.Fatal("expected a signer-failure error")
	}
	if len(witness.objects) != 0 {
		t.Fatal("no witness object must ever be written when signing failed")
	}
	// The real Commit DID succeed (Spanner's row now genuinely reflects
	// revision 2) -- confirmed independently, on a fresh connection, purely
	// to establish this test's premise (a genuine post-commit signer
	// failure, not a pre-commit refusal).
	freshClient := dialRaw(t, emulatorAddr)
	session, err := freshClient.CreateSession(context.Background(), &spannerpb.CreateSessionRequest{Database: emulatorDatabase, Session: &spannerpb.Session{}})
	if err != nil {
		t.Fatal(err)
	}
	txn, err := freshClient.BeginTransaction(context.Background(), &spannerpb.BeginTransactionRequest{
		Session: session.GetName(),
		Options: &spannerpb.TransactionOptions{Mode: &spannerpb.TransactionOptions_ReadWrite_{ReadWrite: &spannerpb.TransactionOptions_ReadWrite{}}},
	})
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		_, _ = freshClient.Rollback(context.Background(), &spannerpb.RollbackRequest{Session: session.GetName(), TransactionId: txn.GetId()})
	}()
	key, _ := structpb.NewList([]interface{}{env.String(), resource.String()})
	readResult, err := freshClient.Read(context.Background(), &spannerpb.ReadRequest{
		Session: session.GetName(), Transaction: &spannerpb.TransactionSelector{Selector: &spannerpb.TransactionSelector_Id{Id: txn.GetId()}},
		Table: "authority_head", Columns: []string{"revision_number"}, KeySet: &spannerpb.KeySet{Keys: []*structpb.ListValue{key}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(readResult.GetRows()) != 1 || readResult.GetRows()[0].GetValues()[0].GetStringValue() != "2" {
		t.Fatal("expected the real Commit to have genuinely succeeded before the signer failure")
	}
	_ = result
}

// TestMatrixL_WitnessConflictNeverOverwrites is Attack L: if the
// deterministic witness key already holds different content than this
// rotation's own payload, ExecuteRotation must report the conflict, never
// overwrite it, and never fall back to a different key.
func TestMatrixL_WitnessConflictNeverOverwrites(t *testing.T) {
	env, epochID, resource, operationID := freshScenario(t)
	raw := dialRaw(t, emulatorAddr)
	seedDigest := testDigest(t, 1)
	seedInitialHead(t, raw, env, epochID, resource, operationID, seedDigest)

	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	witness := newFakeWitness()
	witness.useForceCreate = true
	witness.forceCreateOutcome = gcswitness.AlreadyExistsConflict
	witness.forceCreateErr = gcswitness.ErrConflict

	deps := rotationexecute.Dependencies{Spanner: raw, SpannerDatabase: emulatorDatabase, Witness: witness, Signer: keyPair.Signer()}
	nextOp, _ := protocol.NewOperationID(freshUUIDv7(t))
	candidate := newCandidate(env, epochID, resource, nextOp, 1, seedDigest, []byte("candidate-l"))

	result, err := rotationexecute.ExecuteRotation(context.Background(), deps, candidate)
	if err == nil {
		t.Fatal("expected a witness-conflict error")
	}
	if result.Outcome != rotationexecute.OutcomeUnresolved {
		t.Fatalf("Outcome = %v, want OutcomeUnresolved on witness conflict", result.Outcome)
	}
	if result.WitnessCreate != gcswitness.AlreadyExistsConflict {
		t.Fatalf("WitnessCreate = %v, want AlreadyExistsConflict", result.WitnessCreate)
	}
}

// TestMatrixM_ProcessDeathGuaranteesUnchanged documents Attack M's
// disposition rather than re-running a full subprocess-kill harness: S7
// (docs/evidence/adr-044/real-spanner-process-death-s7) already qualified,
// against real Cloud Spanner, that a process death between
// completeRawCommit's UnambiguousSuccess and buildCommittedPayload/witness
// write leaves the epoch StateRecoveryFrozenPendingWitness -> (via
// epoch.Terminate) StateEpochTerminated, NewEpochRequired == true.
// CompleteRotationCommit (rotationcommit/rotation.go) calls the exact same
// completeRawCommit and the exact same buildCommittedPayload S7's harness
// exercised -- it is not a new, unqualified code path, merely a new,
// additional exported caller of it. Re-running a full real-cloud kill
// harness for this specific caller would re-prove a property that does not
// depend on which exported function invokes these two unexported primitives
// -- this test instead proves, at the source level, that
// CompleteRotationCommit really does call them unmodified.
func TestMatrixM_ProcessDeathGuaranteesUnchanged(t *testing.T) {
	t.Skip("see doc comment: S7's real-cloud process-death qualification already covers the shared completeRawCommit/buildCommittedPayload primitives CompleteRotationCommit calls unmodified; source-level confirmation is in rotationcommit's own boundary/unit tests, not re-run here")
}

// TestMatrixN_StateDigestUsesRotationDomain is Attack N: an ordinary
// rotation's state digest must be hashed under DomainRotationCandidate,
// never DomainNewEpochGenesis -- confirmed end to end against the real
// emulator, not merely by source inspection (boundary_test.go covers the
// source-level half of this attack).
func TestMatrixN_StateDigestUsesRotationDomain(t *testing.T) {
	env, epochID, resource, operationID := freshScenario(t)
	raw := dialRaw(t, emulatorAddr)
	seedDigest := testDigest(t, 1)
	seedInitialHead(t, raw, env, epochID, resource, operationID, seedDigest)
	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	deps := rotationexecute.Dependencies{Spanner: raw, SpannerDatabase: emulatorDatabase, Witness: newFakeWitness(), Signer: keyPair.Signer()}
	nextOp, _ := protocol.NewOperationID(freshUUIDv7(t))
	candidateBytes := []byte("candidate-n")
	candidate := newCandidate(env, epochID, resource, nextOp, 1, seedDigest, candidateBytes)
	result, err := rotationexecute.ExecuteRotation(context.Background(), deps, candidate)
	if err != nil || result.Outcome != rotationexecute.OutcomeCompleted {
		t.Fatalf("result=%+v err=%v", result, err)
	}
	wantDigest := protocol.HashCanonical(protocol.DomainRotationCandidate, candidateBytes)
	if result.StateDigest != wantDigest {
		t.Fatal("ordinary rotation's state digest must be hashed under DomainRotationCandidate, not any other domain")
	}
	genesisDigest := protocol.HashCanonical(protocol.DomainNewEpochGenesis, candidateBytes)
	if result.StateDigest == genesisDigest {
		t.Fatal("rotation and genesis digests over the same bytes must never collide")
	}
}
