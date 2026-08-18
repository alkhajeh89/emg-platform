package bootstrap

import (
	"encoding/base64"
	"testing"

	"cloud.google.com/go/spanner/apiv1/spannerpb"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

func TestGenesisMutationsUseInsertNeverInsertOrUpdate(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	req := fx.request(t)
	stateDigest := plainDigest([]byte("state"))
	candidateDigest := plainDigest([]byte("candidate"))

	mutations, err := GenesisMutations(req, stateDigest, candidateDigest)
	if err != nil {
		t.Fatal(err)
	}
	if len(mutations) != 2 {
		t.Fatalf("len(mutations) = %d, want 2", len(mutations))
	}
	for i, mutation := range mutations {
		write := mutation.GetInsert()
		if write == nil {
			t.Fatalf("mutation[%d] is not a Mutation_Insert -- genesis must never use InsertOrUpdate", i)
		}
	}
	if mutations[0].GetInsert().GetTable() != "authority_head" {
		t.Fatalf("mutations[0] table = %q, want authority_head", mutations[0].GetInsert().GetTable())
	}
	if mutations[1].GetInsert().GetTable() != "authority_transition_history" {
		t.Fatalf("mutations[1] table = %q, want authority_transition_history", mutations[1].GetInsert().GetTable())
	}
}

func TestGenesisMutationsEncodePredecessorDigestAsZeroSentinel(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	req := fx.request(t)
	stateDigest := plainDigest([]byte("state"))
	candidateDigest := plainDigest([]byte("candidate"))

	mutations, err := GenesisMutations(req, stateDigest, candidateDigest)
	if err != nil {
		t.Fatal(err)
	}
	headValues := mutations[0].GetInsert().GetValues()[0].GetValues()
	// predecessor_checkpoint_digest is column index 7 (see authorityHeadColumns).
	got := headValues[7].GetStringValue()
	want := base64.StdEncoding.EncodeToString(protocol.Digest32{}.Bytes())
	if got != want {
		t.Fatalf("predecessor_checkpoint_digest = %q, want %q (zero sentinel)", got, want)
	}
}

func TestGenesisMutationsUseCommitTimestampSentinel(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	req := fx.request(t)
	stateDigest := plainDigest([]byte("state"))
	candidateDigest := plainDigest([]byte("candidate"))

	mutations, err := GenesisMutations(req, stateDigest, candidateDigest)
	if err != nil {
		t.Fatal(err)
	}
	headValues := mutations[0].GetInsert().GetValues()[0].GetValues()
	if headValues[len(headValues)-1].GetStringValue() != spannerCommitTimestampSentinel {
		t.Fatalf("commit_timestamp column = %q, want %q", headValues[len(headValues)-1].GetStringValue(), spannerCommitTimestampSentinel)
	}
}

func TestGenesisCommitRequestUsesSingleUseReadWriteTransaction(t *testing.T) {
	t.Parallel()
	req := GenesisCommitRequest("session-name", []*spannerpb.Mutation{})
	single := req.GetSingleUseTransaction()
	if single == nil {
		t.Fatal("expected a SingleUseTransaction")
	}
	if single.GetReadWrite() == nil {
		t.Fatal("expected TransactionOptions_ReadWrite_ mode")
	}
	if req.GetTransactionId() != nil {
		t.Fatal("a single-use genesis commit must never also carry a TransactionId")
	}
}

func TestPlainDigestNeverUsesAReservedDomainSeparator(t *testing.T) {
	t.Parallel()
	data := []byte("genesis candidate content")
	got := plainDigest(data)
	forDomain := func(domain protocol.DomainSeparator) protocol.Digest32 {
		return protocol.HashCanonical(domain, data)
	}
	if got == forDomain(protocol.DomainRotationCandidate) {
		t.Fatal("plainDigest must never coincide with DomainRotationCandidate's hash of the same bytes")
	}
	if got == forDomain(protocol.DomainNewEpochGenesis) {
		t.Fatal("plainDigest must never coincide with DomainNewEpochGenesis's hash of the same bytes")
	}
}
