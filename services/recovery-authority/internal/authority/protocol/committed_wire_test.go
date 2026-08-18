package protocol

import (
	"testing"
	"time"
)

func testWireEnvironment(t *testing.T) EnvironmentID {
	t.Helper()
	id, err := NewEnvironmentID("staging")
	if err != nil {
		t.Fatal(err)
	}
	return id
}

func testWireUUID(t *testing.T, suffix string) string {
	t.Helper()
	return "00000000-0000-7000-8000-00000000000" + suffix
}

func testWireDigest(t *testing.T, fill byte) Digest32 {
	t.Helper()
	raw := make([]byte, 32)
	for i := range raw {
		raw[i] = fill
	}
	d, err := NewDigest32(raw)
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func TestMarshalUnmarshalV1RoundTrip(t *testing.T) {
	epoch, err := NewAuthorityEpoch(testWireUUID(t, "1"))
	if err != nil {
		t.Fatal(err)
	}
	resource, err := NewResourceIncarnationID(testWireUUID(t, "2"))
	if err != nil {
		t.Fatal(err)
	}
	op, err := NewOperationID(testWireUUID(t, "3"))
	if err != nil {
		t.Fatal(err)
	}
	original := NewCommittedPayload(
		testWireEnvironment(t), epoch, resource, op,
		NewRevisionNumber(1), NewRevisionNumber(0),
		testWireDigest(t, 3), testWireDigest(t, 9),
		time.Date(2026, 8, 18, 0, 0, 0, 0, time.UTC),
		[]byte{0xAA, 0xBB},
	)
	data, err := MarshalCommittedPayloadJSON(original)
	if err != nil {
		t.Fatal(err)
	}
	roundTripped, err := UnmarshalCommittedPayloadJSON(data)
	if err != nil {
		t.Fatal(err)
	}
	if roundTripped.IsV2() {
		t.Fatal("expected round-tripped payload to remain V1")
	}
	origDigest, err := original.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	rtDigest, err := roundTripped.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	if origDigest.String() != rtDigest.String() {
		t.Fatal("round-tripped V1 payload's canonical digest changed")
	}
}

func TestMarshalUnmarshalV2RoundTrip(t *testing.T) {
	epoch, err := NewAuthorityEpoch(testWireUUID(t, "1"))
	if err != nil {
		t.Fatal(err)
	}
	resource, err := NewResourceIncarnationID(testWireUUID(t, "2"))
	if err != nil {
		t.Fatal(err)
	}
	op, err := NewOperationID(testWireUUID(t, "3"))
	if err != nil {
		t.Fatal(err)
	}
	keyID, err := NewSigningKeyID("projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	if err != nil {
		t.Fatal(err)
	}
	original, err := NewCommittedPayloadV2(
		testWireEnvironment(t), epoch, resource, op,
		NewRevisionNumber(1), NewRevisionNumber(0),
		testWireDigest(t, 3), testWireDigest(t, 9),
		time.Date(2026, 8, 18, 0, 0, 0, 0, time.UTC),
		keyID, []byte{0xAA, 0xBB},
	)
	if err != nil {
		t.Fatal(err)
	}
	data, err := MarshalCommittedPayloadJSON(original)
	if err != nil {
		t.Fatal(err)
	}
	roundTripped, err := UnmarshalCommittedPayloadJSON(data)
	if err != nil {
		t.Fatal(err)
	}
	if !roundTripped.IsV2() {
		t.Fatal("expected round-tripped payload to remain V2")
	}
	if roundTripped.SigningKeyID() != keyID {
		t.Fatalf("SigningKeyID = %q, want %q", roundTripped.SigningKeyID().String(), keyID.String())
	}
	origDigest, err := original.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	rtDigest, err := roundTripped.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	if origDigest.String() != rtDigest.String() {
		t.Fatal("round-tripped V2 payload's canonical digest changed")
	}
}

func TestUnmarshalRejectsMalformedJSON(t *testing.T) {
	if _, err := UnmarshalCommittedPayloadJSON([]byte("not json")); err == nil {
		t.Fatal("expected malformed JSON to be rejected")
	}
}

func TestUnmarshalRejectsBadFieldValues(t *testing.T) {
	cases := []string{
		`{"environment_id":"","authority_epoch":"x","resource_incarnation":"x","operation_id":"x","predecessor_digest_hex":"aa","state_digest_hex":"aa","commit_timestamp":"2026-01-01T00:00:00Z","writer_signature_hex":"aa"}`,
		`{"environment_id":"staging","authority_epoch":"not-a-uuid","resource_incarnation":"x","operation_id":"x","predecessor_digest_hex":"aa","state_digest_hex":"aa","commit_timestamp":"2026-01-01T00:00:00Z","writer_signature_hex":"aa"}`,
		`{"environment_id":"staging","authority_epoch":"00000000-0000-7000-8000-000000000001","resource_incarnation":"00000000-0000-7000-8000-000000000002","operation_id":"00000000-0000-7000-8000-000000000003","predecessor_digest_hex":"not-hex","state_digest_hex":"aa","commit_timestamp":"2026-01-01T00:00:00Z","writer_signature_hex":"aa"}`,
	}
	for i, tc := range cases {
		if _, err := UnmarshalCommittedPayloadJSON([]byte(tc)); err == nil {
			t.Errorf("case %d: expected malformed field to be rejected", i)
		}
	}
}
