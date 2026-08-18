package bootstrap

import (
	"errors"
	"testing"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

func TestNewGenesisRequestAcceptsValidInput(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	req := fx.request(t)
	if req.EnvironmentID.String() != testEnvironmentID {
		t.Fatalf("environment id = %q", req.EnvironmentID.String())
	}
	if req.SigningKeyID != fx.keyID {
		t.Fatalf("signing key id mismatch")
	}
}

func TestNewGenesisRequestRejectsMalformedEnvironmentID(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	params := fx.params(t)
	params.EnvironmentID = "Not Valid!!"
	if _, err := NewGenesisRequest(params, fx.now); err == nil {
		t.Fatal("expected an error for a malformed environment id")
	}
}

func TestNewGenesisRequestRejectsMalformedSpannerDatabase(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	params := fx.params(t)
	params.SpannerDatabase = "not-a-spanner-resource-name"
	if _, err := NewGenesisRequest(params, fx.now); !errors.Is(err, ErrGenesisRequestFieldRequired) {
		t.Fatalf("err = %v, want ErrGenesisRequestFieldRequired", err)
	}
}

func TestNewGenesisRequestRejectsMalformedCryptoKey(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	params := fx.params(t)
	params.ApprovedSigningCryptoKey = "not-a-crypto-key"
	if _, err := NewGenesisRequest(params, fx.now); !errors.Is(err, ErrGenesisRequestFieldRequired) {
		t.Fatalf("err = %v, want ErrGenesisRequestFieldRequired", err)
	}
}

func TestNewGenesisRequestRejectsMissingApprovals(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	params := fx.params(t)
	params.Approvals = nil
	if _, err := NewGenesisRequest(params, fx.now); !errors.Is(err, ErrDualControlRolesMissing) {
		t.Fatalf("err = %v, want ErrDualControlRolesMissing", err)
	}
}

// TestNewGenesisRequestApprovalMustBindExactRequest proves an approval
// captured for one set of field values cannot be reused verbatim after any
// single field (here, the approved signing key) changes -- ATTACK_Q.
func TestNewGenesisRequestApprovalMustBindExactRequest(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	params := fx.params(t)
	otherKeyID, err := protocol.NewSigningKeyID(testCryptoKey + "/cryptoKeyVersions/2")
	if err != nil {
		t.Fatal(err)
	}
	params.SigningKeyID = otherKeyID.String()
	if _, err := NewGenesisRequest(params, fx.now); !errors.Is(err, ErrApprovalRequestMismatch) {
		t.Fatalf("err = %v, want ErrApprovalRequestMismatch", err)
	}
}

func TestWitnessKeyIsDeterministicAndUniquePerAttempt(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	req1 := fx.request(t)
	req2 := fx.request(t) // a second, freshly-minted attempt

	if req1.WitnessKey() != req1.WitnessKey() {
		t.Fatal("WitnessKey must be a pure function of req1's own fields")
	}
	if req1.WitnessKey() == req2.WitnessKey() {
		t.Fatal("two independently-generated genesis attempts must never share a witness key")
	}
}

func TestGenerateFreshIdentifiersProducesParseableUUIDv7(t *testing.T) {
	t.Parallel()
	epoch1, op1, err := GenerateFreshIdentifiers()
	if err != nil {
		t.Fatal(err)
	}
	epoch2, op2, err := GenerateFreshIdentifiers()
	if err != nil {
		t.Fatal(err)
	}
	if epoch1.String() == epoch2.String() {
		t.Fatal("two calls must not produce the same authority epoch")
	}
	if op1.String() == op2.String() {
		t.Fatal("two calls must not produce the same operation id")
	}
}

func TestComputeRequestDigestIsSensitiveToEveryField(t *testing.T) {
	t.Parallel()
	base := []string{"env", "resource", "epoch", "op", "db", "key", "cryptokey"}
	baseDigest := computeRequestDigest(base...)
	for i := range base {
		mutated := append([]string(nil), base...)
		mutated[i] = mutated[i] + "-changed"
		if computeRequestDigest(mutated...) == baseDigest {
			t.Fatalf("changing field %d did not change the digest", i)
		}
	}
}

func TestGenesisPredecessorSentinelsAreFixed(t *testing.T) {
	t.Parallel()
	if GenesisPredecessorRevision.Uint64() != 0 {
		t.Fatalf("GenesisPredecessorRevision = %d, want 0", GenesisPredecessorRevision.Uint64())
	}
	if GenesisRevision.Uint64() != 1 {
		t.Fatalf("GenesisRevision = %d, want 1", GenesisRevision.Uint64())
	}
	zero := protocol.Digest32{}
	if GenesisPredecessorDigest != zero {
		t.Fatal("GenesisPredecessorDigest must be the zero Digest32 sentinel")
	}
}
