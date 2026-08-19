//go:build realcloud_spanner

// Package bootstrap real-cloud Spanner qualification (ADR-044 §17 item 7 /
// S7 pre-qualification, Wave 1 Track A). This file is gated behind the
// realcloud_spanner build tag specifically so it can NEVER run as part of
// `go test ./...`, CI, or any other normal invocation -- it dials a real
// Cloud Spanner database and requires real, disposable-project credentials
// supplied entirely through environment variables. It is never invoked
// automatically by anything in this repository.
//
// SCOPE: qualifies the real S2 spannercommit.Client.Commit boundary and
// S6's rotationcommit.CompleteGenesisCommit / bootstrap.GenesisMutations /
// bootstrap.GenesisCommitRequest production code, unmodified, against
// genuine Cloud Spanner. It does NOT qualify real Cloud KMS signing (Wave
// 2/Track C, not yet authorized): signing here uses a local, test-only
// ECDSA key (fakeGenesisSigner, already defined in testhelpers_test.go for
// exactly this reason -- the existing emulator-tagged tests use the same
// kind of fake signer to exercise the Spanner boundary genuinely without
// requiring a real KMS key to exist first). It also does not depend on
// Track B's GCS bucket: it calls rotationcommit.CompleteGenesisCommit
// directly, never bootstrap.ExecuteGenesis's witness-write step.
package bootstrap

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"golang.org/x/oauth2"
	"google.golang.org/api/option"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotation"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationcommit"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/spannercommit"
)

// realCloudSpannerToken obtains a short-lived OAuth2 access token via the
// gcloud CLI's own already-authenticated session (gcloud auth
// print-access-token), rather than requiring full Application Default
// Credentials to be separately configured in this environment. This is a
// TEST-HARNESS-ONLY credential-supply mechanism -- production code
// (spannercommit.Dial's own callers) remains ADC/WIF-only, completely
// unmodified by this file. The token is never logged, never written to any
// evidence file, and never persisted beyond this process's memory.
func realCloudSpannerToken(t *testing.T) string {
	t.Helper()
	out, err := exec.Command("gcloud", "auth", "print-access-token").Output()
	if err != nil {
		t.Fatalf("gcloud auth print-access-token: %v", err)
	}
	token := strings.TrimSpace(string(out))
	if token == "" {
		t.Fatal("gcloud auth print-access-token returned an empty token")
	}
	return token
}

func realCloudSpannerDatabase(t *testing.T) string {
	t.Helper()
	database := os.Getenv("EMG_REALCLOUD_SPANNER_DATABASE")
	if database == "" {
		t.Skip("EMG_REALCLOUD_SPANNER_DATABASE not set -- skipping real-cloud Spanner qualification")
	}
	return database
}

// dialRealSpanner reuses the exact production spannercommit.Dial function
// (unmodified) -- the only difference from a real production binary is the
// explicit token source supplied here, standing in for the ADC/WIF
// resolution a real deployment would use instead. The raw generated stub
// is used ONLY for CreateSession, which bootstrap.ExecuteGenesis needs but
// spannercommit.Client deliberately does not provide (see its own package
// doc: session/transaction orchestration is explicitly out of its scope).
// The object actually under qualification is spannercommit.New(conn),
// whose only method is Commit -- exactly rotationcommit.RawCommitClient.
func dialRealSpanner(t *testing.T, token string) (*spannercommit.Client, spannerpb.SpannerClient) {
	t.Helper()
	ctx := context.Background()
	tokenSource := oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})
	conn, err := spannercommit.Dial(ctx, option.WithTokenSource(tokenSource))
	if err != nil {
		t.Fatalf("spannercommit.Dial (real Cloud Spanner): %v", err)
	}
	t.Cleanup(func() { conn.Close() })
	raw := spannerpb.NewSpannerClient(conn)
	return spannercommit.New(conn), raw
}

func realSpannerSession(t *testing.T, ctx context.Context, raw spannerpb.SpannerClient, database string) string {
	t.Helper()
	session, err := raw.CreateSession(ctx, &spannerpb.CreateSessionRequest{Database: database, Session: &spannerpb.Session{}})
	if err != nil {
		t.Fatalf("CreateSession: %v", err)
	}
	t.Cleanup(func() {
		_, _ = raw.DeleteSession(context.Background(), &spannerpb.DeleteSessionRequest{Name: session.GetName()})
	})
	return session.GetName()
}

// realCloudEvidenceEntry is sanitized, non-secret qualification evidence:
// no tokens, no credentials, no raw auth headers. It is written to a JSON
// file at the end of the test run for manual review before it is ever
// proposed for commit -- never written by this file directly to any
// tracked repository path.
type realCloudEvidenceEntry struct {
	Step            string `json:"step"`
	OutcomeString   string `json:"outcome"`
	ReasonCode      int    `json:"reason_code"`
	GRPCCode        string `json:"grpc_code,omitempty"`
	CommitTimestamp string `json:"commit_timestamp,omitempty"`
	Notes           string `json:"notes,omitempty"`
}

// realCloudFixture bundles the pieces every subtest needs: a real Spanner
// connection (shared -- Dial/CreateSession are themselves under
// qualification only once, not once per subtest).
type realCloudFixture struct {
	t        *testing.T
	database string
	client   *spannercommit.Client
	raw      spannerpb.SpannerClient
}

func newRealCloudFixture(t *testing.T) *realCloudFixture {
	t.Helper()
	database := realCloudSpannerDatabase(t)
	token := realCloudSpannerToken(t)
	client, raw := dialRealSpanner(t, token)
	return &realCloudFixture{t: t, database: database, client: client, raw: raw}
}

// freshGenesisRequest builds one fully validated, dual-control-approved
// GenesisRequest via the real, unmodified NewGenesisRequest constructor --
// exercising the identical production validation path a real operator
// invocation would use, not a hand-assembled struct literal. Each call
// mints fresh identifiers (GenerateFreshIdentifiers), so distinct subtests
// never collide on the same authority_head primary key unless the SAME
// GenesisRequest value is deliberately reused (the duplicate/conflict
// subtest below).
func (f *realCloudFixture) freshGenesisRequest(t *testing.T, keyID protocol.SigningKeyID, now time.Time) GenesisRequest {
	t.Helper()
	authorityEpoch, operationID, err := GenerateFreshIdentifiers()
	if err != nil {
		t.Fatal(err)
	}
	resourceUUID, _, err := GenerateFreshIdentifiers()
	if err != nil {
		t.Fatal(err)
	}
	params := GenesisRequestParams{
		EnvironmentID:            "adr044-realcloud-prequal",
		ResourceIncarnationID:    resourceUUID.String(),
		AuthorityEpoch:           authorityEpoch.String(),
		OperationID:              operationID.String(),
		SpannerDatabase:          f.database,
		SigningKeyID:             keyID.String(),
		ApprovedSigningCryptoKey: testCryptoKey,
	}
	digest := computeRequestDigest(
		params.EnvironmentID, params.ResourceIncarnationID, params.AuthorityEpoch, params.OperationID,
		params.SpannerDatabase, params.SigningKeyID, params.ApprovedSigningCryptoKey,
	)
	params.Approvals = []Approval{
		{Role: ApprovalRoleAuthority, ApproverID: "realcloud-authority-approver", ApprovedAt: now.Add(-time.Hour), Reason: "realcloud qualification", RequestDigest: digest},
		{Role: ApprovalRoleSigning, ApproverID: "realcloud-signing-approver", ApprovedAt: now.Add(-time.Hour), Reason: "realcloud qualification", RequestDigest: digest},
	}
	req, err := NewGenesisRequest(params, now)
	if err != nil {
		t.Fatalf("NewGenesisRequest: %v", err)
	}
	return req
}

// commitGenesis exercises the real production sequence exactly as
// ExecuteGenesis does, minus the witness step: genesisCandidateBytes,
// GenesisMutations, a real CreateSession, GenesisCommitRequest,
// rotation.NewFixedOperation, and rotationcommit.CompleteGenesisCommit --
// all real, unmodified production functions. ctxTimeout, if nonzero,
// bounds only the Commit RPC itself (A5 deadline-interruption case).
func (f *realCloudFixture) commitGenesis(t *testing.T, req GenesisRequest, signer *fakeGenesisSigner, ctxTimeout time.Duration) (protocol.CommittedPayload, rotationcommit.CommitClassification, error) {
	t.Helper()
	ctx := context.Background()

	candidateBytes, err := genesisCandidateBytes(req)
	if err != nil {
		t.Fatal(err)
	}
	stateDigest := protocol.HashCanonical(protocol.DomainNewEpochGenesis, candidateBytes)
	candidateDigest := plainDigest(candidateBytes)

	mutations, err := GenesisMutations(req, stateDigest, candidateDigest)
	if err != nil {
		t.Fatal(err)
	}

	sessionName := realSpannerSession(t, ctx, f.raw, f.database)
	commitRequest := GenesisCommitRequest(sessionName, mutations)

	operation, err := rotation.NewFixedOperation(
		req.EnvironmentID, req.AuthorityEpoch, req.ResourceIncarnation, req.OperationID,
		GenesisPredecessorRevision, GenesisRevision, GenesisPredecessorDigest,
		candidateBytes, nil,
	)
	if err != nil {
		t.Fatal(err)
	}

	commitCtx := ctx
	if ctxTimeout > 0 {
		var cancel context.CancelFunc
		commitCtx, cancel = context.WithTimeout(ctx, ctxTimeout)
		defer cancel()
	}

	return rotationcommit.CompleteGenesisCommit(commitCtx, f.client, commitRequest, operation, signer)
}

func TestRealCloudSpannerQualification(t *testing.T) {
	fixture := newRealCloudFixture(t)
	now := time.Now().UTC()

	privKey, _ := generateTestKeyPair(t)
	keyID := testSigningKeyID(t)
	signer := &fakeGenesisSigner{priv: privKey, keyID: keyID}

	var evidence []realCloudEvidenceEntry
	record := func(e realCloudEvidenceEntry) { evidence = append(evidence, e) }
	t.Cleanup(func() {
		path := os.Getenv("EMG_REALCLOUD_EVIDENCE_OUT")
		if path == "" {
			return
		}
		data, err := json.MarshalIndent(evidence, "", "  ")
		if err != nil {
			t.Logf("encode evidence: %v", err)
			return
		}
		if err := os.WriteFile(path, data, 0o600); err != nil {
			t.Logf("write evidence: %v", err)
		}
	})

	// A4 items 1, 2, 4, 7: one real Commit succeeds; exactly one attempt is
	// made (rotationcommit.completeRawCommit's own frozen single-call
	// contract, not re-verified here); response/error passthrough is
	// unchanged (CompleteGenesisCommit returns the real classification
	// unmodified); acceptedRotationContext / CommittedPayload is produced
	// only after genuine UnambiguousSuccess classification.
	var successReq GenesisRequest
	t.Run("RealCommitSucceeds", func(t *testing.T) {
		successReq = fixture.freshGenesisRequest(t, keyID, now)
		payload, classification, err := fixture.commitGenesis(t, successReq, signer, 0)
		if err != nil {
			t.Fatalf("expected a successful real Commit, got: %v", err)
		}
		if classification.Outcome != protocol.UnambiguousSuccess {
			t.Fatalf("classification.Outcome = %v, want UnambiguousSuccess", classification.Outcome)
		}
		if !payload.IsV2() {
			t.Fatal("expected a V2 CommittedPayload")
		}
		record(realCloudEvidenceEntry{
			Step: "real_commit_succeeds", OutcomeString: classification.Outcome.String(),
			ReasonCode: int(classification.Reason), CommitTimestamp: payload.CommitTimestamp().UTC().Format(time.RFC3339Nano),
			Notes: "genuine UnambiguousSuccess from real Cloud Spanner; CommittedPayload produced only after this classification",
		})
	})

	// A4 item 6: a second Mutation_Insert against the SAME primary key
	// (identical environment/resource/epoch -> identical authority_head PK)
	// must fail closed, never silently succeed or overwrite.
	t.Run("DuplicateInsertFailsClosed", func(t *testing.T) {
		if successReq.EnvironmentID.String() == "" {
			t.Skip("RealCommitSucceeds did not run first")
		}
		_, dupClassification, dupErr := fixture.commitGenesis(t, successReq, signer, 0)
		if dupErr == nil {
			t.Fatal("expected the duplicate genesis attempt to fail")
		}
		if dupClassification.Outcome == protocol.UnambiguousSuccess {
			t.Fatal("a duplicate Mutation_Insert against an existing primary key must never classify as UnambiguousSuccess")
		}
		record(realCloudEvidenceEntry{
			Step: "duplicate_insert_fails_closed", OutcomeString: dupClassification.Outcome.String(),
			ReasonCode: int(dupClassification.Reason), Notes: "identical GenesisRequest re-committed against real Cloud Spanner: " + dupErr.Error(),
		})
	})

	// A5: deadline/transport interruption -- a real, safe, non-destructive
	// way to attempt to induce a genuinely ambiguous outcome against real
	// Spanner: an extremely short client-side deadline may abort the RPC
	// locally while the request is still in flight server-side.
	// ClassifyCommit's own frozen logic must never classify this as success
	// unless a genuine, valid commit timestamp was actually observed.
	t.Run("DeadlineInterruption", func(t *testing.T) {
		req := fixture.freshGenesisRequest(t, keyID, now)
		_, classification, err := fixture.commitGenesis(t, req, signer, 1*time.Millisecond)
		grpcCode := "n/a"
		if err != nil {
			grpcCode = status.Code(err).String()
		}
		record(realCloudEvidenceEntry{
			Step: "deadline_interruption", OutcomeString: classification.Outcome.String(),
			ReasonCode: int(classification.Reason), GRPCCode: grpcCode,
			Notes: "1ms client deadline against real Cloud Spanner -- classification must never be UnambiguousSuccess without a genuine, valid commit timestamp",
		})
		switch {
		case classification.Outcome == protocol.UnambiguousSuccess:
			t.Log("commit completed within 1ms deadline -- ambiguity was not actually induced this run; expected to be flaky, not itself a defect")
		case err != nil && status.Code(err) == codes.DeadlineExceeded:
			t.Log("deadline exceeded as expected; classification below asserts fail-closed handling")
		default:
			t.Logf("non-deadline outcome observed instead: err=%v grpc_code=%s -- also an acceptable, non-UnambiguousSuccess outcome", err, grpcCode)
		}
		if classification.Outcome == protocol.UnambiguousSuccess && err != nil {
			t.Fatal("classification reported UnambiguousSuccess but CompleteGenesisCommit also returned an error -- contradictory result")
		}
	})

	t.Log("STILL_REQUIRED_FOR_S7: genuine mid-RPC process death (killing this test process between request-dispatch and response) was not safely inducible in this environment/session and is not claimed as qualified by this run.")
}
