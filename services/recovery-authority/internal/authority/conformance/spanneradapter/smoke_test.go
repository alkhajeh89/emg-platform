//go:build emulator

package spanneradapter

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"testing"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// freshResourceID returns a resource identifier unique to this test
// invocation, so re-running this smoke test against a long-lived emulator
// (which does not reset state between runs, unlike CI's fresh container
// per run) never collides with a row a previous run already committed.
func freshResourceID(t *testing.T) string {
	t.Helper()
	suffix := make([]byte, 8)
	if _, err := rand.Read(suffix); err != nil {
		t.Fatal(err)
	}
	return "smoke-" + hex.EncodeToString(suffix)
}

const emulatorDatabase = "projects/emg-recovery-authority-test/instances/test-instance/databases/test-db"

func dialEmulator(t *testing.T) *Client {
	t.Helper()
	conn, err := Dial(context.Background(), "localhost:9010")
	if err != nil {
		t.Fatalf("dial emulator: %v", err)
	}
	t.Cleanup(func() { conn.Close() })
	return New(conn, emulatorDatabase)
}

func TestSmokeCreateSessionBeginReadCommitRead(t *testing.T) {
	client := dialEmulator(t)
	ctx := context.Background()

	session, err := client.CreateSession(ctx)
	if err != nil {
		t.Fatalf("CreateSession: %v", err)
	}
	defer client.DeleteSession(ctx, session)

	txn, err := client.BeginReadWrite(ctx, session)
	if err != nil {
		t.Fatalf("BeginReadWrite: %v", err)
	}

	resourceID := freshResourceID(t)
	_, found, err := client.ReadAuthorityHead(ctx, session, txn, "staging", resourceID)
	if err != nil {
		t.Fatalf("ReadAuthorityHead (empty): %v", err)
	}
	if found {
		t.Fatal("expected no row on first read")
	}

	stateDigest, _ := protocol.NewDigest32(bytesOf(1))
	candidateDigest, _ := protocol.NewDigest32(bytesOf(2))
	predecessorDigest, _ := protocol.NewDigest32(bytesOf(3))
	mutations := TransitionMutations(
		"staging", resourceID, "018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a1",
		"018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a3", 1, 0,
		stateDigest, candidateDigest, predecessorDigest,
	)
	request := CommitRequest(session, txn, mutations)
	response, err := client.Raw().Commit(ctx, request)
	if err != nil {
		t.Fatalf("Commit: %v", err)
	}
	if response.GetCommitTimestamp() == nil {
		t.Fatal("expected a commit timestamp")
	}

	verifySession, err := client.CreateSession(ctx)
	if err != nil {
		t.Fatalf("CreateSession (verify): %v", err)
	}
	defer client.DeleteSession(ctx, verifySession)
	verifyTxn, err := client.BeginReadWrite(ctx, verifySession)
	if err != nil {
		t.Fatalf("BeginReadWrite (verify): %v", err)
	}
	row, found, err := client.ReadAuthorityHead(ctx, verifySession, verifyTxn, "staging", resourceID)
	if err != nil {
		t.Fatalf("ReadAuthorityHead (verify): %v", err)
	}
	if !found {
		t.Fatal("expected the row written above to be readable")
	}
	if row.RevisionNumber != 1 {
		t.Fatalf("row.RevisionNumber = %d, want 1", row.RevisionNumber)
	}
	client.Rollback(ctx, verifySession, verifyTxn)
}

func bytesOf(b byte) []byte {
	out := make([]byte, 32)
	for i := range out {
		out[i] = b
	}
	return out
}
