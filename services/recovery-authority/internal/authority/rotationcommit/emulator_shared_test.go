//go:build emulator

package rotationcommit

// Shared test-support for the ADR-043 emulator-tier conformance matrix.
// Every test in this build-tag-gated file group drives the real, frozen
// completeRawCommit/ClassifyCommit functions against a real Cloud Spanner
// emulator (docker image gcr.io/cloud-spanner-emulator/emulator, see
// services/recovery-authority/scripts/emulator/ for setup) -- these test
// files live inside package rotationcommit specifically because that is
// the only place completeRawCommit, acceptedRotationContext, and
// buildCommittedPayload are reachable at all, by design.

import (
	"context"
	"crypto/rand"
	"fmt"
	"testing"
	"time"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/spanneradapter"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotation"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

const (
	emulatorAddr     = "localhost:9010"
	emulatorDatabase = "projects/emg-recovery-authority-test/instances/test-instance/databases/test-db"
	fixedEnvironment = "staging"
)

// dialEmulator opens a fresh raw gRPC connection to addr (either the
// emulator directly, or a faultproxy.Proxy address standing in front of
// it) and wraps it as a spanneradapter.Client.
func dialEmulator(t *testing.T, addr string) *spanneradapter.Client {
	t.Helper()
	conn, err := spanneradapter.Dial(context.Background(), addr)
	if err != nil {
		t.Fatalf("dial %s: %v", addr, err)
	}
	t.Cleanup(func() { conn.Close() })
	return spanneradapter.New(conn, emulatorDatabase)
}

func hexDigit(t *testing.T) byte {
	t.Helper()
	b := make([]byte, 1)
	if _, err := rand.Read(b); err != nil {
		t.Fatal(err)
	}
	return "0123456789abcdef"[b[0]%16]
}

func hexRun(t *testing.T, n int) string {
	t.Helper()
	out := make([]byte, n)
	for i := range out {
		out[i] = hexDigit(t)
	}
	return string(out)
}

// newUUIDv7ish generates a fresh, random, canonically-shaped UUIDv7 string
// satisfying protocol.NewAuthorityEpoch / NewOperationID /
// NewResourceIncarnationID's strict validation (version nibble '7',
// variant nibble in 89ab). It carries no real timestamp semantics -- only
// the string shape needed to construct valid protocol identifiers for each
// independent emulator test.
func newUUIDv7ish(t *testing.T) string {
	t.Helper()
	variantChars := "89ab"
	variant := variantChars[int(hexDigit(t))%4]
	return fmt.Sprintf("%s-%s-7%s-%c%s-%s",
		hexRun(t, 8), hexRun(t, 4), hexRun(t, 3), variant, hexRun(t, 3), hexRun(t, 12))
}

// freshResourceIncarnation returns a resource incarnation ID unique to this
// test, so independent tests never collide on the authority_head primary
// key (environment_id, resource_incarnation_id) inside the shared emulator
// database.
func freshResourceIncarnation(t *testing.T) protocol.ResourceIncarnationID {
	t.Helper()
	id, err := protocol.NewResourceIncarnationID(newUUIDv7ish(t))
	if err != nil {
		t.Fatal(err)
	}
	return id
}

func freshOperationID(t *testing.T) protocol.OperationID {
	t.Helper()
	id, err := protocol.NewOperationID(newUUIDv7ish(t))
	if err != nil {
		t.Fatal(err)
	}
	return id
}

func fixedEpoch(t *testing.T) protocol.AuthorityEpoch {
	t.Helper()
	epoch, err := protocol.NewAuthorityEpoch(newUUIDv7ish(t))
	if err != nil {
		t.Fatal(err)
	}
	return epoch
}

func environmentID(t *testing.T) protocol.EnvironmentID {
	t.Helper()
	id, err := protocol.NewEnvironmentID(fixedEnvironment)
	if err != nil {
		t.Fatal(err)
	}
	return id
}

func digestOf(t *testing.T, seed byte) protocol.Digest32 {
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

// emulatorOperation is one independent, freshly-keyed rotation scenario:
// its own resource incarnation, epoch, and operation ID, so it never
// collides with any other test's rows in the shared emulator database.
type emulatorOperation struct {
	Environment         protocol.EnvironmentID
	Epoch               protocol.AuthorityEpoch
	ResourceIncarnation protocol.ResourceIncarnationID
	OperationID         protocol.OperationID
}

func newEmulatorOperation(t *testing.T) emulatorOperation {
	t.Helper()
	return emulatorOperation{
		Environment:         environmentID(t),
		Epoch:               fixedEpoch(t),
		ResourceIncarnation: freshResourceIncarnation(t),
		OperationID:         freshOperationID(t),
	}
}

// buildFixedOperation constructs the FixedOperation and matching Spanner
// mutations for a rotation from expectedRevision to expectedRevision+1.
func (o emulatorOperation) buildFixedOperation(t *testing.T, expectedRevision uint64) rotation.FixedOperation {
	t.Helper()
	predecessorDigest := digestOf(t, 3)
	candidateBytes := []byte(fmt.Sprintf("candidate-%s-%d", o.OperationID.String(), expectedRevision+1))
	preparedBytes := []byte(fmt.Sprintf("prepared-%s-%d", o.OperationID.String(), expectedRevision+1))
	operation, err := rotation.NewFixedOperation(
		o.Environment, o.Epoch, o.ResourceIncarnation, o.OperationID,
		protocol.NewRevisionNumber(expectedRevision), protocol.NewRevisionNumber(expectedRevision+1),
		predecessorDigest, candidateBytes, preparedBytes,
	)
	if err != nil {
		t.Fatal(err)
	}
	return operation
}

// commitRequestFor builds the real *spannerpb.CommitRequest for one
// rotation attempt: begins a genuine read-write transaction against the
// emulator, reads the current authority_head row (proving real Read RPC
// traffic, matching the required-capability list), and assembles the
// mutations completeRawCommit's caller is responsible for providing.
func commitRequestFor(
	t *testing.T,
	client *spanneradapter.Client,
	operation rotation.FixedOperation,
) (request *spannerpb.CommitRequest, session string, txnID []byte) {
	t.Helper()
	ctx := context.Background()
	sessionName, err := client.CreateSession(ctx)
	if err != nil {
		t.Fatalf("CreateSession: %v", err)
	}
	txn, err := client.BeginReadWrite(ctx, sessionName)
	if err != nil {
		t.Fatalf("BeginReadWrite: %v", err)
	}
	if _, _, err := client.ReadAuthorityHead(
		ctx, sessionName, txn,
		operation.EnvironmentID().String(), operation.ResourceIncarnation().String(),
	); err != nil {
		t.Fatalf("ReadAuthorityHead: %v", err)
	}
	stateDigest := digestOf(t, 9)
	candidateDigest := digestOf(t, 9)
	mutations := spanneradapter.TransitionMutations(
		operation.EnvironmentID().String(), operation.ResourceIncarnation().String(),
		operation.AuthorityEpoch().String(), operation.OperationID().String(),
		operation.ProposedRevision().Uint64(), operation.ExpectedRevision().Uint64(),
		stateDigest, candidateDigest, operation.PreparedDigest(),
	)
	return spanneradapter.CommitRequest(sessionName, txn, mutations), sessionName, txn
}

func withDeadline(seconds float64) (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), time.Duration(seconds*float64(time.Second)))
}

func transitionMutationsFor(operation rotation.FixedOperation) []*spannerpb.Mutation {
	stateDigest, _ := protocol.NewDigest32(bytesOfSeed(9))
	candidateDigest, _ := protocol.NewDigest32(bytesOfSeed(9))
	return spanneradapter.TransitionMutations(
		operation.EnvironmentID().String(), operation.ResourceIncarnation().String(),
		operation.AuthorityEpoch().String(), operation.OperationID().String(),
		operation.ProposedRevision().Uint64(), operation.ExpectedRevision().Uint64(),
		stateDigest, candidateDigest, operation.PreparedDigest(),
	)
}

func bytesOfSeed(seed byte) []byte {
	raw := make([]byte, 32)
	for i := range raw {
		raw[i] = seed
	}
	return raw
}

func statusCodeOf(err error) codes.Code {
	return status.Code(err)
}

// rollbackBestEffort releases the emulator's single global "active
// transaction" slot (a real, documented limitation of this emulator build:
// "The emulator only supports one transaction at a time" -- observed
// directly against the running container, see the emulator conformance
// notes in the final report). Any test that begins a read-write
// transaction and does not carry it through to a successful Commit MUST
// call this in a defer/cleanup, or every subsequent test in this package
// will spuriously fail with ABORTED against an emulator that thinks a
// prior, abandoned transaction is still active -- including, critically,
// transactions abandoned by a SIGKILLed helper process in the T7/T8/T10
// process-kill tests, where the parent (not the dead child) must perform
// this cleanup using a fresh connection.
func rollbackBestEffort(t *testing.T, addr, session string, transactionID []byte) {
	t.Helper()
	if len(transactionID) == 0 {
		return
	}
	client := dialEmulator(t, addr)
	if err := client.Rollback(context.Background(), session, transactionID); err != nil {
		t.Logf("best-effort rollback (session=%s): %v", session, err)
	}
}
