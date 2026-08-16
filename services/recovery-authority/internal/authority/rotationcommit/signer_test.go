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
type fakeSigner struct {
	key      []byte
	fail     bool
	calls    int
	lastSeen protocol.Digest32
}

func (signer *fakeSigner) SignCommittedDigest(_ context.Context, digest protocol.Digest32) ([]byte, error) {
	signer.calls++
	signer.lastSeen = digest
	if signer.fail {
		return nil, errors.New("injected signer failure")
	}
	return fakeSign(signer.key, digest), nil
}

func fakeSign(key []byte, digest protocol.Digest32) []byte {
	material := append(append([]byte{}, key...), digest.Bytes()...)
	return protocol.HashCanonical(protocol.DomainCommitted, material).Bytes()
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

	signer := &fakeSigner{key: []byte("writer-key")}
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

	signer := &fakeSigner{key: []byte("writer-key"), fail: true}
	_, err = buildCommittedPayload(context.Background(), signer, accepted)
	if !errors.Is(err, ErrCommittedPayloadUnavailable) {
		t.Fatalf("err = %v, want ErrCommittedPayloadUnavailable", err)
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
	signer := &fakeSigner{key: []byte("writer-key")}
	if _, err := buildCommittedPayload(context.Background(), signer, accepted); err != nil {
		t.Fatal(err)
	}
	if signer.calls != 1 {
		t.Fatalf("signer.calls = %d, want exactly 1", signer.calls)
	}
}
