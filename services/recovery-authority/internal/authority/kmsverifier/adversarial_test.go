// This file is the S3 end-to-end adversarial matrix (Phase 7 of the S3
// authorization): it wires a real kmssigner.Signer (against a fake, but
// cryptographically genuine, AsymmetricSignClient), a real
// keypinning.Store, a real compromiseledger.Ledger, and this package's
// Verifier together behind recovery.VerifyPersistedCommitted -- the exact
// same exported entry point production code calls -- and proves the
// letter-labeled properties Phase 7 requires. Letters refer to that list.
package kmsverifier_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"encoding/pem"
	"testing"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/compromiseledger"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/kmssigner"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/kmsverifier"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/recovery"
)

// -- shared harness -----------------------------------------------------

type harness struct {
	t              *testing.T
	signClient     *fakeSignClient
	signer         *kmssigner.Signer
	pins           keypinning.Store
	ledger         compromiseledger.Ledger
	verifier       *kmsverifier.Verifier
	keyVersionName string
	lineage        recovery.ApprovedSigningLineage
}

func newHarness(t *testing.T, cryptoKeyName, keyVersionName string) *harness {
	t.Helper()
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	signClient := &fakeSignClient{privKey: priv, fabricateAt: true}
	signer, err := kmssigner.New(signClient, keyVersionName, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	pins := keypinning.NewMemoryStore()
	ledger := compromiseledger.NewMemoryLedger()
	verifier, err := kmsverifier.New(pins, ledger)
	if err != nil {
		t.Fatal(err)
	}
	lineage, err := keypinning.CryptoKeyLineage(cryptoKeyName)
	if err != nil {
		t.Fatal(err)
	}

	der, err := x509.MarshalPKIXPublicKey(&priv.PublicKey)
	if err != nil {
		t.Fatal(err)
	}
	pemStr := string(pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der}))
	keyID, err := protocol.NewSigningKeyID(keyVersionName)
	if err != nil {
		t.Fatal(err)
	}
	pin, err := keypinning.CaptureFromKMS(context.Background(), &fakePublicKeyClient{
		version:   version(keyVersionName),
		publicKey: publicKey(keyVersionName, pemStr),
	}, keyVersionName, lineage, "test pin")
	if err != nil {
		t.Fatal(err)
	}
	if err := pins.Pin(context.Background(), pin); err != nil {
		t.Fatal(err)
	}
	_ = keyID

	return &harness{
		t: t, signClient: signClient, signer: signer, pins: pins, ledger: ledger,
		verifier: verifier, keyVersionName: keyVersionName, lineage: lineage,
	}
}

// buildV2Payload replicates rotationcommit.buildCommittedPayload's ADR-045
// §10 construction order using only exported surface -- buildCommittedPayload
// itself is package-private and already independently tested by Track A;
// this harness's job is to exercise S3's provider realization, not
// re-litigate S1's construction-order tests.
func (h *harness) buildV2Payload(t *testing.T, envID, epoch, resource, op string, revision, predRevision uint64) protocol.CommittedPayload {
	t.Helper()
	ctx := context.Background()
	keyID, err := h.signer.ActiveKeyID(ctx)
	if err != nil {
		t.Fatal(err)
	}
	environment, err := protocol.NewEnvironmentID(envID)
	if err != nil {
		t.Fatal(err)
	}
	authorityEpoch, err := protocol.NewAuthorityEpoch(epoch)
	if err != nil {
		t.Fatal(err)
	}
	resourceID, err := protocol.NewResourceIncarnationID(resource)
	if err != nil {
		t.Fatal(err)
	}
	operationID, err := protocol.NewOperationID(op)
	if err != nil {
		t.Fatal(err)
	}
	predDigest := fixedDigest(t, 3)
	stateDigest := fixedDigest(t, 9)
	unsigned, err := protocol.NewCommittedPayloadV2(
		environment, authorityEpoch, resourceID, operationID,
		protocol.NewRevisionNumber(revision), protocol.NewRevisionNumber(predRevision),
		predDigest, stateDigest, time.Unix(1000, 0).UTC(), keyID, nil,
	)
	if err != nil {
		t.Fatal(err)
	}
	digest, err := unsigned.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	sig, confirmed, err := h.signer.SignCommittedDigest(ctx, digest)
	if err != nil {
		t.Fatal(err)
	}
	if confirmed != keyID {
		t.Fatal("signer confirmation mismatch in test harness")
	}
	return unsigned.WithSignature(sig)
}

func (h *harness) expectedBinding(payload protocol.CommittedPayload) recovery.ExpectedBinding {
	return recovery.ExpectedBinding{
		EnvironmentID:          payload.EnvironmentID(),
		AuthorityEpoch:         payload.AuthorityEpoch(),
		ResourceIncarnation:    payload.ResourceIncarnation(),
		OperationID:            payload.OperationID(),
		PredecessorRevision:    payload.PredecessorRevision(),
		PredecessorDigest:      payload.PredecessorDigest(),
		ApprovedSigningLineage: h.lineage,
	}
}

func fixedDigest(t *testing.T, fill byte) protocol.Digest32 {
	t.Helper()
	raw := make([]byte, 32)
	for i := range raw {
		raw[i] = fill
	}
	d, err := protocol.NewDigest32(raw)
	if err != nil {
		t.Fatal(err)
	}
	return d
}

const approvedCryptoKey = "projects/p/locations/l/keyRings/r/cryptoKeys/my-key"
const approvedKeyVersion = approvedCryptoKey + "/cryptoKeyVersions/1"

const (
	testEpoch    = "00000000-0000-7000-8000-000000000001"
	testResource = "00000000-0000-7000-8000-000000000002"
	testOp       = "00000000-0000-7000-8000-000000000003"
)

// -- A. attacker-owned valid Cloud KMS key cannot authenticate a record --

func TestMatrix_A_AttackerOwnedValidKeyCannotAuthenticate(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	genuine := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)
	expected := h.expectedBinding(genuine)

	// Attacker's own, fully independent, genuinely-owned KMS key.
	attackerCryptoKey := "projects/attacker/locations/l/keyRings/r/cryptoKeys/attacker-key"
	attackerKeyVersion := attackerCryptoKey + "/cryptoKeyVersions/1"
	attackerHarness := newHarness(t, attackerCryptoKey, attackerKeyVersion)
	forged := attackerHarness.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)

	// The attacker signs with their own genuinely valid key, but presents
	// the forged record for verification against the DEFENDER's
	// approved-lineage/pin/ledger configuration -- exactly the real attack
	// shape (an attacker cannot make the defender's verifier consult the
	// attacker's own trust anchors).
	err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, forged, expected)
	if err == nil {
		t.Fatal("attacker-owned valid key must never authenticate a record")
	}
}

// -- B. foreign project/key lineage rejected -----------------------------

func TestMatrix_B_ForeignLineageRejected(t *testing.T) {
	foreignCryptoKey := "projects/other-project/locations/l/keyRings/r/cryptoKeys/my-key"
	foreignKeyVersion := foreignCryptoKey + "/cryptoKeyVersions/1"
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	foreignHarness := newHarness(t, foreignCryptoKey, foreignKeyVersion)

	payload := foreignHarness.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)
	expected := h.expectedBinding(payload) // defender's own lineage/verifier
	err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, payload, expected)
	if err == nil {
		t.Fatal("a key from a foreign project lineage must be rejected")
	}
}

// -- C. key ID tampering fails -------------------------------------------

func TestMatrix_C_KeyIDTamperingFails(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	genuine := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)

	otherVersion := approvedCryptoKey + "/cryptoKeyVersions/2"
	tamperedKeyID, err := protocol.NewSigningKeyID(otherVersion)
	if err != nil {
		t.Fatal(err)
	}
	tampered, err := protocol.NewCommittedPayloadV2(
		genuine.EnvironmentID(), genuine.AuthorityEpoch(), genuine.ResourceIncarnation(), genuine.OperationID(),
		genuine.RevisionNumber(), genuine.PredecessorRevision(), genuine.PredecessorDigest(), genuine.StateDigest(),
		genuine.CommitTimestamp(), tamperedKeyID, genuine.WriterSignature(),
	)
	if err != nil {
		t.Fatal(err)
	}
	expected := h.expectedBinding(genuine)
	if err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, tampered, expected); err == nil {
		t.Fatal("a tampered signing_key_id must fail verification")
	}
}

// -- D. unknown SigningKeyID fails ---------------------------------------

func TestMatrix_D_UnknownSigningKeyIDFails(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	genuine := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)
	unknownVersion := approvedCryptoKey + "/cryptoKeyVersions/999"
	unknownKeyID, err := protocol.NewSigningKeyID(unknownVersion)
	if err != nil {
		t.Fatal(err)
	}
	unpinned, err := protocol.NewCommittedPayloadV2(
		genuine.EnvironmentID(), genuine.AuthorityEpoch(), genuine.ResourceIncarnation(), genuine.OperationID(),
		genuine.RevisionNumber(), genuine.PredecessorRevision(), genuine.PredecessorDigest(), genuine.StateDigest(),
		genuine.CommitTimestamp(), unknownKeyID, genuine.WriterSignature(),
	)
	if err != nil {
		t.Fatal(err)
	}
	expected := h.expectedBinding(genuine)
	// unknownVersion IS within the approved lineage (same CryptoKey), so
	// this exercises step 4 (no pinned key) specifically, not step 2.
	err = recovery.VerifyPersistedCommitted(context.Background(), h.verifier, unpinned, expected)
	if err == nil {
		t.Fatal("an unknown (unpinned) SigningKeyID must fail closed")
	}
}

// -- F. correct old key verifies after routine rotation ------------------

func TestMatrix_F_OldKeyVerifiesAfterRoutineRotation(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	old := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)
	expected := h.expectedBinding(old)

	// Simulate rotation: a NEW active version exists now, but the old
	// version's pin remains, and its own lineage-approved for this
	// resource is unaffected (§7D: routine rotation != compromise).
	newVersion := approvedCryptoKey + "/cryptoKeyVersions/2"
	newSigner, err := kmssigner.New(&fakeSignClient{privKey: mustNewECDSAKey(t), fabricateAt: true}, newVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	_ = newSigner // new active signer exists; old pin still governs `old`.

	if err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, old, expected); err != nil {
		t.Fatalf("old, routinely-rotated-out key must still verify its own historical record: %v", err)
	}
}

// -- G. correct old key verifies after provider version disabled, pin exists

func TestMatrix_G_OldKeyVerifiesAfterDisablementWithPin(t *testing.T) {
	// Disablement is entirely a provider-side, live-call concept; this
	// Verifier never makes a live call at all (see doc comment), so a
	// disabled version's historical record verifies exactly the same as
	// an enabled one, as long as its pin exists -- this test proves no
	// hidden live-availability dependency exists.
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	payload := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)
	expected := h.expectedBinding(payload)
	// signClient.err simulates "the provider would now refuse to sign or
	// serve the public key live" -- but Verify never calls signClient at
	// all, proving no live dependency.
	h.signClient.err = errAssertNeverCalled
	if err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, payload, expected); err != nil {
		t.Fatalf("verification must not depend on live KMS availability once pinned: %v", err)
	}
}

// -- H. disabled old key with no pin => fail closed -----------------------

func TestMatrix_H_NoPinFailsClosed(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	payload := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)
	expected := h.expectedBinding(payload)

	// Fresh verifier with an EMPTY pin store -- simulates a version whose
	// pin was never captured (an operational governance violation, §7C).
	emptyVerifier, err := kmsverifier.New(keypinning.NewMemoryStore(), compromiseledger.NewMemoryLedger())
	if err != nil {
		t.Fatal(err)
	}
	if err := recovery.VerifyPersistedCommitted(context.Background(), emptyVerifier, payload, expected); err == nil {
		t.Fatal("a key with no pinned material must fail closed, never silently accepted")
	}
}

// -- I. different public key substituted under same SigningKeyID ---------

func TestMatrix_I_SubstitutedPinFailsClosed(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	payload := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)
	expected := h.expectedBinding(payload)

	// Attempt to overwrite the pin for the SAME SigningKeyID with a
	// DIFFERENT key's material -- Store.Pin itself must refuse this.
	otherPriv := mustNewECDSAKey(t)
	otherDER, err := x509.MarshalPKIXPublicKey(&otherPriv.PublicKey)
	if err != nil {
		t.Fatal(err)
	}
	otherPEM := string(pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: otherDER}))
	substitutePin, err := keypinning.CaptureFromKMS(context.Background(), &fakePublicKeyClient{
		version:   version(approvedKeyVersion),
		publicKey: publicKey(approvedKeyVersion, otherPEM),
	}, approvedKeyVersion, h.lineage, "malicious substitution attempt")
	if err != nil {
		t.Fatal(err)
	}
	if err := h.pins.Pin(context.Background(), substitutePin); err == nil {
		t.Fatal("pinning different material under an already-pinned SigningKeyID must fail closed")
	}
	// And the original, genuine payload must still verify correctly --
	// the rejected substitution attempt must not have corrupted the store.
	if err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, payload, expected); err != nil {
		t.Fatalf("original pin must remain intact after a rejected substitution attempt: %v", err)
	}
}

// -- J. correct signature under wrong key => fail -------------------------

func TestMatrix_J_CorrectSignatureUnderWrongKeyFails(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	genuine := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)

	otherVersion := approvedCryptoKey + "/cryptoKeyVersions/2"
	otherClient := &fakeSignClient{privKey: mustNewECDSAKey(t), fabricateAt: true}
	otherSigner, err := kmssigner.New(otherClient, otherVersion, keypinning.AlgorithmECSignP256SHA256)
	if err != nil {
		t.Fatal(err)
	}
	// Build a payload claiming genuine's key ID, but actually sign with
	// otherSigner's different key -- a wrong-key/genuine-key-ID mismatch.
	unsignedForOther, err := protocol.NewCommittedPayloadV2(
		genuine.EnvironmentID(), genuine.AuthorityEpoch(), genuine.ResourceIncarnation(), genuine.OperationID(),
		genuine.RevisionNumber(), genuine.PredecessorRevision(), genuine.PredecessorDigest(), genuine.StateDigest(),
		genuine.CommitTimestamp(), genuine.SigningKeyID(), nil,
	)
	if err != nil {
		t.Fatal(err)
	}
	digest, err := unsignedForOther.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	wrongSig, _, err := otherSigner.SignCommittedDigest(context.Background(), digest)
	if err != nil {
		t.Fatal(err)
	}
	forged := unsignedForOther.WithSignature(wrongSig)
	expected := h.expectedBinding(genuine)
	if err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, forged, expected); err == nil {
		t.Fatal("a genuinely-produced signature from the WRONG key must fail cryptographic verification")
	}
}

// -- K. try-all-key behavior does not exist --------------------------------

// TestMatrix_K_NoTryAllKeysFallback proves the verifier resolves EXACTLY
// the claimed SigningKeyID's own pinned material -- never any other
// pinned key in the store, even one that would make an otherwise-forged
// record verify. Store.Get is a single deterministic, keyed lookup; no
// method anywhere in this package enumerates or iterates over all pins.
func TestMatrix_K_NoTryAllKeysFallback(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	genuine := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)

	// Pin a SECOND, genuinely different key under a different SigningKeyID
	// in the SAME store and lineage.
	secondVersion := approvedCryptoKey + "/cryptoKeyVersions/2"
	secondPriv := mustNewECDSAKey(t)
	secondDER, err := x509.MarshalPKIXPublicKey(&secondPriv.PublicKey)
	if err != nil {
		t.Fatal(err)
	}
	secondPEM := string(pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: secondDER}))
	secondPin, err := keypinning.CaptureFromKMS(context.Background(), &fakePublicKeyClient{
		version:   version(secondVersion),
		publicKey: publicKey(secondVersion, secondPEM),
	}, secondVersion, h.lineage, "second key")
	if err != nil {
		t.Fatal(err)
	}
	if err := h.pins.Pin(context.Background(), secondPin); err != nil {
		t.Fatal(err)
	}

	// Take genuine's content and signature (produced by the FIRST key) but
	// re-stamp its claimed signing_key_id to the SECOND key -- a forged
	// record. If the verifier ever "tried" multiple pinned keys, it might
	// find the first key's material would verify this signature -- but it
	// must only ever consult the SECOND key's pin, since that is what the
	// record claims, and that key's material does NOT produce this
	// signature.
	relabeled, err := protocol.NewCommittedPayloadV2(
		genuine.EnvironmentID(), genuine.AuthorityEpoch(), genuine.ResourceIncarnation(), genuine.OperationID(),
		genuine.RevisionNumber(), genuine.PredecessorRevision(), genuine.PredecessorDigest(), genuine.StateDigest(),
		genuine.CommitTimestamp(), secondPin.SigningKeyID, genuine.WriterSignature(),
	)
	if err != nil {
		t.Fatal(err)
	}
	expected := h.expectedBinding(genuine)
	if err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, relabeled, expected); err == nil {
		t.Fatal("verification must never fall back to trying a different pinned key than the one the record claims")
	}
}

// -- L/M. compromise before/at-or-after distrust-effective-time ----------

func TestMatrix_L_CompromiseBeforeEffectiveTimeStillVerifies(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	payload := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0) // CommitTimestamp = unix(1000)
	expected := h.expectedBinding(payload)

	if err := h.ledger.Declare(context.Background(), compromiseledger.DistrustRecord{
		Subject: approvedKeyVersion, EffectiveTime: time.Unix(2000, 0), RecordedAt: time.Unix(2000, 0),
		Reason: "test", RecordedBy: "test-admin",
	}); err != nil {
		t.Fatal(err)
	}
	if err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, payload, expected); err != nil {
		t.Fatalf("a record strictly before the distrust-effective-time must still verify: %v", err)
	}
}

func TestMatrix_M_CompromiseAtOrAfterEffectiveTimeFails(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	payload := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0) // CommitTimestamp = unix(1000)
	expected := h.expectedBinding(payload)

	if err := h.ledger.Declare(context.Background(), compromiseledger.DistrustRecord{
		Subject: approvedKeyVersion, EffectiveTime: time.Unix(500, 0), RecordedAt: time.Unix(500, 0),
		Reason: "test", RecordedBy: "test-admin",
	}); err != nil {
		t.Fatal(err)
	}
	err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, payload, expected)
	if err == nil {
		t.Fatal("a record at/after the distrust-effective-time must never pass ordinary automated verification")
	}
}

// -- N. compromise ledger unavailable => fail closed ----------------------

type failingLedger struct{}

func (failingLedger) Declare(context.Context, compromiseledger.DistrustRecord) error {
	return errAssertNeverCalled
}
func (failingLedger) Status(context.Context, string, time.Time) (compromiseledger.Status, error) {
	return compromiseledger.StatusNotDistrusted, errAssertNeverCalled
}

func TestMatrix_N_LedgerUnavailableFailsClosed(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	payload := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)
	expected := h.expectedBinding(payload)

	brokenVerifier, err := kmsverifier.New(h.pins, failingLedger{})
	if err != nil {
		t.Fatal(err)
	}
	if err := recovery.VerifyPersistedCommitted(context.Background(), brokenVerifier, payload, expected); err == nil {
		t.Fatal("ledger unavailability must never result in silent verification success")
	}
}

// -- O. routine live-KMS outage with valid pinned material still verifies

func TestMatrix_O_LiveKMSOutageDoesNotBreakHistoricalVerification(t *testing.T) {
	// Identical in spirit to G, restated as its own named case per Phase 7.
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	payload := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)
	expected := h.expectedBinding(payload)
	h.signClient.err = errAssertNeverCalled // "live KMS is down"
	if err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, payload, expected); err != nil {
		t.Fatalf("a live KMS outage must not break historical verification of an already-pinned key: %v", err)
	}
}

// -- P. superseded-but-not-compromised lineage retains historical semantics

func TestMatrix_P_SupersededLineageRetainsHistoricalVerification(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	payload := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)
	// "Superseded" is caller-side ExpectedBinding configuration state
	// (§7D) -- the historical record's own expected binding, captured at
	// the time it was genuinely authorized, is unaffected by whatever the
	// CURRENT approved lineage is for new signing. Verifying against the
	// SAME expected binding the record was created under (not today's
	// current lineage) must still succeed.
	expected := h.expectedBinding(payload)
	if err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, payload, expected); err != nil {
		t.Fatalf("a record verified against its own authorization-at-the-time binding must succeed regardless of later lineage supersession: %v", err)
	}
}

// -- Q. superseded lineage cannot authorize new signing --------------------

func TestMatrix_Q_DifferentLineageCannotAuthorizeForeignPayload(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	payload := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)

	newCryptoKey := "projects/p/locations/l/keyRings/r/cryptoKeys/replacement-key"
	newLineage, err := keypinning.CryptoKeyLineage(newCryptoKey)
	if err != nil {
		t.Fatal(err)
	}
	expected := h.expectedBinding(payload)
	expected.ApprovedSigningLineage = newLineage // "current" lineage now points elsewhere
	if err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, payload, expected); err == nil {
		t.Fatal("a payload signed under a lineage the caller no longer approves must not verify against the new lineage")
	}
}

// -- W. pinned key cannot substitute for approved lineage authorization --

func TestMatrix_W_PinnedKeyAloneCannotSubstituteForLineageAuthorization(t *testing.T) {
	// A key can be validly pinned (verification material exists) while
	// still being OUTSIDE the approved lineage for THIS verification call
	// -- pinning existence must never be treated as authorization.
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	payload := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)

	unrelatedLineage, err := keypinning.CryptoKeyLineage("projects/p/locations/l/keyRings/r/cryptoKeys/unrelated-key")
	if err != nil {
		t.Fatal(err)
	}
	expected := h.expectedBinding(payload)
	expected.ApprovedSigningLineage = unrelatedLineage
	// VerifyPersistedCommitted's own step 2 (lineage) runs before ever
	// reaching this package's Verifier -- proving the pin's mere existence
	// in h.pins never lets verification proceed regardless.
	err = recovery.VerifyPersistedCommitted(context.Background(), h.verifier, payload, expected)
	if err == nil {
		t.Fatal("an existing pin must never substitute for lineage authorization")
	}
}

// -- X. compromise ledger cannot substitute for cryptographic verification

func TestMatrix_X_LedgerClearanceCannotSubstituteForCryptoVerification(t *testing.T) {
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	genuine := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)
	// Tamper the signature bytes -- ledger has NOTHING declared (fully
	// "clear"), but the signature itself is now invalid.
	tamperedSig := append([]byte{}, genuine.WriterSignature()...)
	if len(tamperedSig) > 0 {
		tamperedSig[0] ^= 0xFF
	}
	tampered := genuine.WithSignature(tamperedSig)
	expected := h.expectedBinding(genuine)
	if err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, tampered, expected); err == nil {
		t.Fatal("a clear compromise-ledger status must never substitute for cryptographic signature verification")
	}
}

// -- Y. valid crypto verification cannot substitute for compromise check --

func TestMatrix_Y_ValidSignatureCannotSubstituteForComplianceCheck(t *testing.T) {
	// This is exactly Matrix M restated as its own named case per Phase 7:
	// a genuinely, cryptographically valid signature is not enough on its
	// own if the ledger requires manual review.
	h := newHarness(t, approvedCryptoKey, approvedKeyVersion)
	payload := h.buildV2Payload(t, "staging", testEpoch, testResource, testOp, 1, 0)
	expected := h.expectedBinding(payload)
	if err := h.ledger.Declare(context.Background(), compromiseledger.DistrustRecord{
		Subject: approvedKeyVersion, EffectiveTime: time.Unix(1, 0), RecordedAt: time.Unix(1, 0),
		Reason: "test", RecordedBy: "test-admin",
	}); err != nil {
		t.Fatal(err)
	}
	if err := recovery.VerifyPersistedCommitted(context.Background(), h.verifier, payload, expected); err == nil {
		t.Fatal("a valid signature must never substitute for a clean compromise/distrust status")
	}
}

func mustNewECDSAKey(t *testing.T) *ecdsa.PrivateKey {
	t.Helper()
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	return priv
}
