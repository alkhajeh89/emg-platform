//go:build emulator

package rotationcommit

// T9 with the GCS witness adapter substituted for the local filesystem
// witness: same live process, a real signed COMMITTED already held in
// memory, the GCS create response lost (via the real fault proxy in front
// of fake-gcs-server), and exact-key read-resolution confirming identical
// bytes -- ACTIVE may resume. This exercises the bounded GCS adapter
// end-to-end against a real Spanner emulator commit and a real (though
// non-authoritative) GCS emulator, reusing the same faultproxy already
// proven against Spanner.

import (
	"context"
	"net/http"
	"testing"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/faultproxy"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/localsigner"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/epoch"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/recovery"
	"google.golang.org/api/option"
)

func gcsAdapterForTest(t *testing.T, endpoint string) *gcswitness.Adapter {
	t.Helper()
	client, err := gcswitness.NewClient(context.Background(),
		option.WithEndpoint(endpoint),
		option.WithoutAuthentication(),
		option.WithHTTPClient(&http.Client{}),
	)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { client.Close() })
	return gcswitness.New(client, fakeGCSBucketForTest)
}

// TestT1GCSNormalSuccessReachesActiveOnlyAfterGCSVerification is T1 with the
// GCS witness adapter substituted for the local filesystem witness: a
// completely healthy Spanner CAS success, a real signed COMMITTED persisted
// to the GCS emulator via CreateExactIfAbsent, and only after independent
// exact-key-read verification does ACTIVE become permitted. Reaching
// StateRecoveryFrozenPendingWitness alone (i.e. the Spanner success by
// itself) must never be treated as sufficient.
func TestT1GCSNormalSuccessReachesActiveOnlyAfterGCSVerification(t *testing.T) {
	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	spannerClient := dialEmulator(t, emulatorAddr)
	request, _, _ := commitRequestFor(t, spannerClient, operation)
	accepted, classification, err := completeRawCommit(context.Background(), spannerClient.Raw(), request, operation, nil)
	if err != nil || classification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("setup: classification=%v err=%v", classification, err)
	}
	frozen := epoch.TransitionOnCASOutcome(classification.Outcome)
	if frozen != epoch.StateRecoveryFrozenPendingWitness {
		t.Fatalf("state after CAS success = %v, want StateRecoveryFrozenPendingWitness", frozen)
	}
	if frozen.RecoveryAllowed() || frozen.RotationAllowed() || frozen.FenceReleaseAllowed() || frozen.PostgreSQLReconciliationAllowed() {
		t.Fatal("StateRecoveryFrozenPendingWitness must permit no authority-dependent action prior to witness verification")
	}

	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	payload, err := buildCommittedPayload(context.Background(), keyPair.Signer(), accepted)
	if err != nil {
		t.Fatal(err)
	}
	serialized, err := serializeCommittedPayload(payload)
	if err != nil {
		t.Fatal(err)
	}

	adapter := gcsAdapterForTest(t, fakeGCSEndpointForTest)
	witnessKey := "committed/" + op.OperationID.String()
	outcome, err := adapter.CreateExactIfAbsent(context.Background(), witnessKey, serialized)
	if err != nil {
		t.Fatal(err)
	}
	if outcome != gcswitness.CreateSuccess {
		t.Fatalf("outcome = %v, want CreateSuccess", outcome)
	}

	stored, err := adapter.ReadExact(context.Background(), witnessKey)
	if err != nil {
		t.Fatal(err)
	}
	roundTripped := deserializeCommittedPayload(t, stored)
	expected := recovery.ExpectedBinding{
		EnvironmentID:       op.Environment,
		AuthorityEpoch:      op.Epoch,
		ResourceIncarnation: op.ResourceIncarnation,
		OperationID:         op.OperationID,
		PredecessorRevision: operation.ExpectedRevision(),
		PredecessorDigest:   operation.PreparedDigest(),
		ApprovedSigningLineage: func(keyID protocol.SigningKeyID) bool {
			return keyID == keyPair.KeyID()
		},
	}
	if err := recovery.VerifyPersistedCommitted(context.Background(), keyPair.Verifier(), roundTripped, expected); err != nil {
		t.Fatalf("independent verification of the GCS-persisted COMMITTED failed: %v", err)
	}

	active := epoch.TransitionOnWitnessOutcome(true)
	if active != epoch.StateActive {
		t.Fatalf("state = %v, want StateActive", active)
	}
	if !active.RecoveryAllowed() || !active.RotationAllowed() || !active.FenceReleaseAllowed() || !active.PostgreSQLReconciliationAllowed() {
		t.Fatal("StateActive must permit all four authority-dependent actions after verified GCS witness persistence")
	}
}

// TestT9GCSSameProcessRetryAfterAmbiguousWitnessWriteIsSafe is T9 against
// the real bounded GCS adapter: a genuine Spanner commit succeeds, a real
// signed CommittedPayload is built, the FIRST attempt to persist it to GCS
// has its response dropped by the fault proxy (backend genuinely creates
// the object; the client never sees the response), and the SAME live
// process retries with the SAME retained signed bytes -- resolving safely
// via 412+exact-read, never via any Spanner-side re-classification.
func TestT9GCSSameProcessRetryAfterAmbiguousWitnessWriteIsSafe(t *testing.T) {
	op := newEmulatorOperation(t)
	operation := op.buildFixedOperation(t, 0)
	spannerClient := dialEmulator(t, emulatorAddr)
	request, _, _ := commitRequestFor(t, spannerClient, operation)
	accepted, classification, err := completeRawCommit(context.Background(), spannerClient.Raw(), request, operation, nil)
	if err != nil || classification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("setup: classification=%v err=%v", classification, err)
	}

	keyPair, err := localsigner.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	payload, err := buildCommittedPayload(context.Background(), keyPair.Signer(), accepted)
	if err != nil {
		t.Fatal(err)
	}
	serialized, err := serializeCommittedPayload(payload)
	if err != nil {
		t.Fatal(err)
	}
	witnessKey := "committed/" + op.OperationID.String()

	// First attempt: through a fault proxy that drops the response after
	// the backend genuinely creates the object.
	proxy := faultproxy.New("localhost:4443", time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	proxy.QueueFault(faultproxy.DropResponseAfterBackendSuccess)
	proxiedAdapter := gcsAdapterForTest(t, "http://"+proxyAddr+"/storage/v1/")

	firstOutcome, firstErr := proxiedAdapter.CreateExactIfAbsent(context.Background(), witnessKey, serialized)
	if firstOutcome == gcswitness.HardFailure {
		t.Fatalf("first attempt must not be a hard failure: %v", firstErr)
	}

	// SAME live process, SAME retained signed bytes, retried directly
	// (unproxied) -- this is the T9 "same process, same bytes, safe retry"
	// property.
	directAdapter := gcsAdapterForTest(t, fakeGCSEndpointForTest)
	secondOutcome, secondErr := directAdapter.CreateExactIfAbsent(context.Background(), witnessKey, serialized)
	if secondErr != nil {
		t.Fatalf("same-process retry with identical bytes must succeed: %v", secondErr)
	}
	if secondOutcome != gcswitness.CreateSuccess && secondOutcome != gcswitness.AlreadyExistsIdentical {
		t.Fatalf("second outcome = %v, want CreateSuccess or AlreadyExistsIdentical", secondOutcome)
	}

	// Exact-key read confirms identical signed bytes.
	stored, err := directAdapter.ReadExact(context.Background(), witnessKey)
	if err != nil {
		t.Fatal(err)
	}
	roundTripped := deserializeCommittedPayload(t, stored)

	expected := recovery.ExpectedBinding{
		EnvironmentID:       op.Environment,
		AuthorityEpoch:      op.Epoch,
		ResourceIncarnation: op.ResourceIncarnation,
		OperationID:         op.OperationID,
		PredecessorRevision: operation.ExpectedRevision(),
		PredecessorDigest:   operation.PreparedDigest(),
		ApprovedSigningLineage: func(keyID protocol.SigningKeyID) bool {
			return keyID == keyPair.KeyID()
		},
	}
	if err := recovery.VerifyPersistedCommitted(context.Background(), keyPair.Verifier(), roundTripped, expected); err != nil {
		t.Fatalf("independent verification of the GCS-persisted COMMITTED failed: %v", err)
	}

	// ACTIVE may resume.
	active := epoch.TransitionOnWitnessOutcome(true)
	if active != epoch.StateActive {
		t.Fatalf("state = %v, want StateActive", active)
	}
}
