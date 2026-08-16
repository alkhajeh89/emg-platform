package rotationcommit

import (
	"context"
	"errors"
	"testing"
	"time"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// fakeSigner is a TEST-ONLY, no-KMS, no-network Signer. It signs by
// concatenating a fixed key with the digest bytes and hashing -- adequate to
// prove the boundary and verification logic in this phase; a real
// asymmetric signing adapter is explicitly out of scope here.
//
// keyID is this signer's fixed, test-only ADR-045 key identifier, reported
// by ActiveKeyID and confirmed (truthfully, by default) by
// SignCommittedDigest. confirmOverride, when non-zero, lets a test force a
// deliberately WRONG confirmation to exercise buildCommittedPayload's
// mismatch hard-failure path (ADR-045 §10 step 7) -- a real signer could
// never intentionally do this, but a compromised or malfunctioning one
// might, and the caller-side check must catch it regardless of why it
// happened.
type fakeSigner struct {
	key             []byte
	keyID           protocol.SigningKeyID
	fail            bool
	failActiveKeyID bool
	confirmOverride protocol.SigningKeyID
	calls           int
	activeKeyCalls  int
	lastSeen        protocol.Digest32
}

func newFakeSigner(t testing.TB, key []byte, keyIDValue string) *fakeSigner {
	t.Helper()
	keyID, err := protocol.NewSigningKeyID(keyIDValue)
	if err != nil {
		t.Fatal(err)
	}
	return &fakeSigner{key: key, keyID: keyID}
}

func (signer *fakeSigner) ActiveKeyID(_ context.Context) (protocol.SigningKeyID, error) {
	signer.activeKeyCalls++
	if signer.failActiveKeyID {
		return protocol.SigningKeyID{}, errors.New("injected ActiveKeyID failure")
	}
	return signer.keyID, nil
}

func (signer *fakeSigner) SignCommittedDigest(_ context.Context, digest protocol.Digest32) ([]byte, protocol.SigningKeyID, error) {
	signer.calls++
	signer.lastSeen = digest
	if signer.fail {
		return nil, protocol.SigningKeyID{}, errors.New("injected signer failure")
	}
	confirmed := signer.keyID
	if !signer.confirmOverride.IsZero() {
		confirmed = signer.confirmOverride
	}
	return fakeSign(signer.key, digest), confirmed, nil
}

func fakeSign(key []byte, digest protocol.Digest32) []byte {
	material := append(append([]byte{}, key...), digest.Bytes()...)
	return protocol.HashCanonical(protocol.DomainCommittedV2, material).Bytes()
}

func TestBuildCommittedPayloadRequiresLiveAcceptedContext(t *testing.T) {
	t.Parallel()
	// buildCommittedPayload's second parameter is acceptedRotationContext,
	// an unexported type. This test documents, and enforces at compile
	// time, that only code inside this package -- which can only obtain a
	// value of that type from a prior completeRawCommit success -- can call
	// it. There is no way to write this same call from outside the package;
	// that is not merely a convention, it is a compile error, and this test
	// exercises the one legitimate path.
	operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))
	response := &spannerpb.CommitResponse{
		CommitTimestamp: timestamppb.New(time.Date(2026, 8, 16, 1, 2, 3, 0, time.UTC)),
	}
	client := &fakeRawCommitClient{response: response}
	accepted, classification, err := completeRawCommit(
		context.Background(), client, &spannerpb.CommitRequest{}, operation, nil,
	)
	if err != nil || classification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("setup: completeRawCommit failed: classification=%v err=%v", classification, err)
	}

	signer := newFakeSigner(t, []byte("writer-key"), "projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	payload, err := buildCommittedPayload(context.Background(), signer, accepted)
	if err != nil {
		t.Fatalf("buildCommittedPayload failed: %v", err)
	}
	if signer.calls != 1 {
		t.Fatalf("signer.calls = %d, want 1", signer.calls)
	}
	digest, err := payload.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	if digest.String() != signer.lastSeen.String() {
		t.Fatal("signer was asked to sign a different digest than the payload actually carries")
	}
	if len(payload.WriterSignature()) == 0 {
		t.Fatal("built payload has no writer signature")
	}
}

func TestBuildCommittedPayloadFailsClosedOnSignerError(t *testing.T) {
	t.Parallel()
	operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))
	response := &spannerpb.CommitResponse{
		CommitTimestamp: timestamppb.New(time.Date(2026, 8, 16, 1, 2, 3, 0, time.UTC)),
	}
	client := &fakeRawCommitClient{response: response}
	accepted, _, err := completeRawCommit(context.Background(), client, &spannerpb.CommitRequest{}, operation, nil)
	if err != nil {
		t.Fatal(err)
	}

	signer := newFakeSigner(t, []byte("writer-key"), "projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	signer.fail = true
	_, err = buildCommittedPayload(context.Background(), signer, accepted)
	if !errors.Is(err, ErrCommittedPayloadUnavailable) {
		t.Fatalf("err = %v, want ErrCommittedPayloadUnavailable", err)
	}
}

func TestBuildCommittedPayloadFailsClosedOnActiveKeyIDError(t *testing.T) {
	t.Parallel()
	operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))
	response := &spannerpb.CommitResponse{
		CommitTimestamp: timestamppb.New(time.Date(2026, 8, 16, 1, 2, 3, 0, time.UTC)),
	}
	client := &fakeRawCommitClient{response: response}
	accepted, _, err := completeRawCommit(context.Background(), client, &spannerpb.CommitRequest{}, operation, nil)
	if err != nil {
		t.Fatal(err)
	}
	signer := newFakeSigner(t, []byte("writer-key"), "projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	signer.failActiveKeyID = true
	_, err = buildCommittedPayload(context.Background(), signer, accepted)
	if !errors.Is(err, ErrCommittedPayloadUnavailable) {
		t.Fatalf("err = %v, want ErrCommittedPayloadUnavailable", err)
	}
	if signer.calls != 0 {
		t.Fatalf("signer.calls = %d, want 0 -- SignCommittedDigest must never be called if ActiveKeyID failed", signer.calls)
	}
}

// TestBuildCommittedPayloadHardFailsOnConfirmedKeyMismatch is the direct
// regression test for the second P0 this ADR-045 review found and
// corrected: if the signer's post-signing confirmation names a DIFFERENT
// key than the one already bound into the digest via ActiveKeyID, this
// MUST be a hard construction failure -- never a silent success, never a
// retry, never a rebuild under either identifier.
func TestBuildCommittedPayloadHardFailsOnConfirmedKeyMismatch(t *testing.T) {
	t.Parallel()
	operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))
	response := &spannerpb.CommitResponse{
		CommitTimestamp: timestamppb.New(time.Date(2026, 8, 16, 1, 2, 3, 0, time.UTC)),
	}
	client := &fakeRawCommitClient{response: response}
	accepted, _, err := completeRawCommit(context.Background(), client, &spannerpb.CommitRequest{}, operation, nil)
	if err != nil {
		t.Fatal(err)
	}
	signer := newFakeSigner(t, []byte("writer-key"), "projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	wrongKeyID, err := protocol.NewSigningKeyID("projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/2")
	if err != nil {
		t.Fatal(err)
	}
	signer.confirmOverride = wrongKeyID

	_, err = buildCommittedPayload(context.Background(), signer, accepted)
	if !errors.Is(err, ErrSigningKeyMismatch) {
		t.Fatalf("err = %v, want ErrSigningKeyMismatch", err)
	}
}

// TestBuildCommittedPayloadProducesV2Payload proves buildCommittedPayload
// now always produces a V2 CommittedPayload (ADR-045: production genesis is
// V2-exclusive from the first record onward).
func TestBuildCommittedPayloadProducesV2Payload(t *testing.T) {
	t.Parallel()
	operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))
	response := &spannerpb.CommitResponse{
		CommitTimestamp: timestamppb.New(time.Date(2026, 8, 16, 1, 2, 3, 0, time.UTC)),
	}
	client := &fakeRawCommitClient{response: response}
	accepted, _, err := completeRawCommit(context.Background(), client, &spannerpb.CommitRequest{}, operation, nil)
	if err != nil {
		t.Fatal(err)
	}
	signer := newFakeSigner(t, []byte("writer-key"), "projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	payload, err := buildCommittedPayload(context.Background(), signer, accepted)
	if err != nil {
		t.Fatal(err)
	}
	if !payload.IsV2() {
		t.Fatal("buildCommittedPayload must produce a V2 payload")
	}
	if payload.SigningKeyID() != signer.keyID {
		t.Fatalf("payload.SigningKeyID() = %q, want %q", payload.SigningKeyID().String(), signer.keyID.String())
	}
}

// TestSignerCallsNeverExceedOnePerBuild proves the signing step, like the
// Commit step it follows, is never internally retried.
func TestSignerCallsNeverExceedOnePerBuild(t *testing.T) {
	t.Parallel()
	operation := fixedOperationForTest(t, []byte("candidate"), []byte("prepared"))
	response := &spannerpb.CommitResponse{
		CommitTimestamp: timestamppb.New(time.Date(2026, 8, 16, 1, 2, 3, 0, time.UTC)),
	}
	client := &fakeRawCommitClient{response: response}
	accepted, _, err := completeRawCommit(context.Background(), client, &spannerpb.CommitRequest{}, operation, nil)
	if err != nil {
		t.Fatal(err)
	}
	signer := newFakeSigner(t, []byte("writer-key"), "projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	if _, err := buildCommittedPayload(context.Background(), signer, accepted); err != nil {
		t.Fatal(err)
	}
	if signer.calls != 1 {
		t.Fatalf("signer.calls = %d, want exactly 1", signer.calls)
	}
}
