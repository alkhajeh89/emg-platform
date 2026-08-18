package bootstrap

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"sync"
	"testing"
	"time"

	"cloud.google.com/go/kms/apiv1/kmspb"
	"cloud.google.com/go/spanner/apiv1/spannerpb"
	gax "github.com/googleapis/gax-go/v2"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/compromiseledger"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/recovery"
)

const (
	testEnvironmentID   = "test-env"
	testCryptoKey       = "projects/p/locations/l/keyRings/r/cryptoKeys/k"
	testSpannerDatabase = "projects/p/instances/i/databases/d"
)

func testSigningKeyID(t testing.TB) protocol.SigningKeyID {
	t.Helper()
	id, err := protocol.NewSigningKeyID(testCryptoKey + "/cryptoKeyVersions/1")
	if err != nil {
		t.Fatal(err)
	}
	return id
}

// generateTestKeyPair produces a real ECDSA P-256 key pair and its
// PEM-encoded SubjectPublicKeyInfo, exactly the shape Cloud KMS's
// GetPublicKey returns (see keypinning.ParsePEMPublicKey).
func generateTestKeyPair(t testing.TB) (*ecdsa.PrivateKey, string) {
	t.Helper()
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	der, err := x509.MarshalPKIXPublicKey(&priv.PublicKey)
	if err != nil {
		t.Fatal(err)
	}
	pemBytes := pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der})
	return priv, string(pemBytes)
}

// fakePublicKeyClient implements keypinning.PublicKeyClient for tests,
// mirroring kmsverifier's own test helper shape.
type fakePublicKeyClient struct {
	version   *kmspb.CryptoKeyVersion
	publicKey *kmspb.PublicKey
}

func (f *fakePublicKeyClient) GetCryptoKeyVersion(_ context.Context, _ *kmspb.GetCryptoKeyVersionRequest, _ ...gax.CallOption) (*kmspb.CryptoKeyVersion, error) {
	return f.version, nil
}

func (f *fakePublicKeyClient) GetPublicKey(_ context.Context, _ *kmspb.GetPublicKeyRequest, _ ...gax.CallOption) (*kmspb.PublicKey, error) {
	return f.publicKey, nil
}

// pinTestKey captures and stores a genuine, correctly-fingerprinted pin for
// keyID via the real keypinning.CaptureFromKMS path -- this test package
// has no access to keypinning's unexported fingerprint helper, by design,
// so every test that needs a valid pin goes through the same production
// capture code real deployments would use.
func pinTestKey(t testing.TB, store keypinning.Store, keyID protocol.SigningKeyID, pub string, lineage recovery.ApprovedSigningLineage) {
	t.Helper()
	client := &fakePublicKeyClient{
		version: &kmspb.CryptoKeyVersion{
			Name:      keyID.String(),
			State:     kmspb.CryptoKeyVersion_ENABLED,
			Algorithm: kmspb.CryptoKeyVersion_EC_SIGN_P256_SHA256,
		},
		publicKey: &kmspb.PublicKey{
			Name:      keyID.String(),
			Pem:       pub,
			Algorithm: kmspb.CryptoKeyVersion_EC_SIGN_P256_SHA256,
		},
	}
	pin, err := keypinning.CaptureFromKMS(context.Background(), client, keyID.String(), lineage, "test-capture")
	if err != nil {
		t.Fatalf("pinTestKey: capture: %v", err)
	}
	if err := store.Pin(context.Background(), pin); err != nil {
		t.Fatalf("pinTestKey: store: %v", err)
	}
}

// fakeGenesisSigner is a real (non-KMS) rotationcommit.Signer implementation
// producing genuine ECDSA P-256 signatures, exactly like
// rotationcommit's own fakeSigner but shaped for this package's tests.
type fakeGenesisSigner struct {
	priv            *ecdsa.PrivateKey
	keyID           protocol.SigningKeyID
	activeKeyIDErr  error
	signErr         error
	confirmOverride protocol.SigningKeyID
}

func (f *fakeGenesisSigner) ActiveKeyID(context.Context) (protocol.SigningKeyID, error) {
	if f.activeKeyIDErr != nil {
		return protocol.SigningKeyID{}, f.activeKeyIDErr
	}
	return f.keyID, nil
}

func (f *fakeGenesisSigner) SignCommittedDigest(_ context.Context, digest protocol.Digest32) ([]byte, protocol.SigningKeyID, error) {
	if f.signErr != nil {
		return nil, protocol.SigningKeyID{}, f.signErr
	}
	sig, err := ecdsa.SignASN1(rand.Reader, f.priv, digest.Bytes())
	if err != nil {
		return nil, protocol.SigningKeyID{}, err
	}
	confirmed := f.keyID
	if !f.confirmOverride.IsZero() {
		confirmed = f.confirmOverride
	}
	return sig, confirmed, nil
}

// fakeGenesisSpannerClient implements GenesisSpannerClient for tests. Each
// Commit call is recorded; commitErr/commitResponse are directly injectable
// so tests can exercise every ClassifyCommit outcome without any real
// network or emulator dependency.
type fakeGenesisSpannerClient struct {
	mu                 sync.Mutex
	sessionErr         error
	commitResponse     *spannerpb.CommitResponse
	commitErr          error
	createSessionCalls int
	commitCalls        int
	lastCommitRequest  *spannerpb.CommitRequest
}

func (f *fakeGenesisSpannerClient) CreateSession(_ context.Context, _ *spannerpb.CreateSessionRequest, _ ...grpc.CallOption) (*spannerpb.Session, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.createSessionCalls++
	if f.sessionErr != nil {
		return nil, f.sessionErr
	}
	return &spannerpb.Session{Name: "projects/p/instances/i/databases/d/sessions/fake"}, nil
}

func (f *fakeGenesisSpannerClient) Commit(_ context.Context, req *spannerpb.CommitRequest, _ ...grpc.CallOption) (*spannerpb.CommitResponse, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.commitCalls++
	f.lastCommitRequest = req
	return f.commitResponse, f.commitErr
}

func successfulCommitResponse(t time.Time) *spannerpb.CommitResponse {
	return &spannerpb.CommitResponse{CommitTimestamp: timestamppb.New(t)}
}

func abortedCommitErr() error { return status.Error(codes.Aborted, "injected abort") }

func alreadyExistsCommitErr() error { return status.Error(codes.AlreadyExists, "injected conflict") }

func ambiguousCommitErr() error { return status.Error(codes.Unavailable, "injected ambiguous failure") }

// fakeWitness is an in-memory gcswitness.ImmutableWitness with the same
// create-if-absent/no-overwrite semantics as the real adapter, plus
// injectable force-outcomes for adversarial tests.
type fakeWitness struct {
	mu                 sync.Mutex
	objects            map[string][]byte
	forceExistsErr     error
	useForceCreate     bool
	forceCreateOutcome gcswitness.CreateOutcome
	forceCreateErr     error
}

func newFakeWitness() *fakeWitness {
	return &fakeWitness{objects: make(map[string][]byte)}
}

func (f *fakeWitness) Exists(_ context.Context, key string) (bool, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.forceExistsErr != nil {
		return false, f.forceExistsErr
	}
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

// testFixture bundles a fully valid, ready-to-run genesis environment: a
// pinned, approved-lineage signing key with a real key pair, a compromise
// ledger with nothing distrusted, a fresh pair of dual-control approvals
// bound to the request, and fake Spanner/witness dependencies primed for a
// clean success. Individual tests mutate exactly the one piece they mean
// to attack.
type testFixture struct {
	t        testing.TB
	now      time.Time
	priv     *ecdsa.PrivateKey
	keyID    protocol.SigningKeyID
	lineage  recovery.ApprovedSigningLineage
	pinStore keypinning.Store
	ledger   compromiseledger.Ledger
	spanner  *fakeGenesisSpannerClient
	witness  *fakeWitness
	signer   *fakeGenesisSigner
	evidence string
}

func newTestFixture(t testing.TB) *testFixture {
	t.Helper()
	priv, pub := generateTestKeyPair(t)
	keyID := testSigningKeyID(t)
	lineage, err := keypinning.CryptoKeyLineage(testCryptoKey)
	if err != nil {
		t.Fatal(err)
	}
	pinStore := keypinning.NewMemoryStore()
	pinTestKey(t, pinStore, keyID, pub, lineage)

	ledgerPath := t.TempDir() + "/ledger.jsonl"
	ledger, err := compromiseledger.NewFileLedger(ledgerPath)
	if err != nil {
		t.Fatal(err)
	}

	return &testFixture{
		t:        t,
		now:      time.Date(2026, 8, 18, 12, 0, 0, 0, time.UTC),
		priv:     priv,
		keyID:    keyID,
		lineage:  lineage,
		pinStore: pinStore,
		ledger:   ledger,
		spanner:  &fakeGenesisSpannerClient{commitResponse: successfulCommitResponse(time.Date(2026, 8, 18, 12, 0, 1, 0, time.UTC))},
		witness:  newFakeWitness(),
		signer:   &fakeGenesisSigner{priv: priv, keyID: keyID},
		evidence: t.TempDir(),
	}
}

func (f *testFixture) approvals(digest [32]byte) []Approval {
	return []Approval{
		{Role: ApprovalRoleAuthority, ApproverID: "authority-approver", ApprovedAt: f.now.Add(-time.Hour), Reason: "reviewed", RequestDigest: digest},
		{Role: ApprovalRoleSigning, ApproverID: "signing-approver", ApprovedAt: f.now.Add(-time.Hour), Reason: "reviewed", RequestDigest: digest},
	}
}

func (f *testFixture) params(t testing.TB) GenesisRequestParams {
	t.Helper()
	authorityEpoch, operationID, err := GenerateFreshIdentifiers()
	if err != nil {
		t.Fatal(err)
	}
	resourceUUID, _, err := GenerateFreshIdentifiers()
	if err != nil {
		t.Fatal(err)
	}
	base := GenesisRequestParams{
		EnvironmentID:            testEnvironmentID,
		ResourceIncarnationID:    resourceUUID.String(),
		AuthorityEpoch:           authorityEpoch.String(),
		OperationID:              operationID.String(),
		SpannerDatabase:          testSpannerDatabase,
		SigningKeyID:             f.keyID.String(),
		ApprovedSigningCryptoKey: testCryptoKey,
	}
	digest := computeRequestDigest(
		base.EnvironmentID, base.ResourceIncarnationID, base.AuthorityEpoch, base.OperationID,
		base.SpannerDatabase, base.SigningKeyID, base.ApprovedSigningCryptoKey,
	)
	base.Approvals = f.approvals(digest)
	return base
}

func (f *testFixture) request(t testing.TB) GenesisRequest {
	t.Helper()
	req, err := NewGenesisRequest(f.params(t), f.now)
	if err != nil {
		t.Fatalf("newTestFixture: valid request failed to validate: %v", err)
	}
	return req
}

func (f *testFixture) deps() Dependencies {
	return Dependencies{
		Spanner:     f.spanner,
		Witness:     f.witness,
		Signer:      f.signer,
		Lineage:     f.lineage,
		PinStore:    f.pinStore,
		Ledger:      f.ledger,
		EvidenceDir: f.evidence,
	}
}

var errInjected = errors.New("bootstrap_test: injected failure")
