package keypinning

import (
	"context"
	"errors"
	"fmt"
	"time"

	"cloud.google.com/go/kms/apiv1/kmspb"
	gax "github.com/googleapis/gax-go/v2"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/recovery"
)

// PublicKeyClient is the minimal, read-only Cloud KMS boundary this package
// needs to capture a pin: retrieving a version's lifecycle state and its
// public key. It deliberately has NO AsymmetricSign method and NO
// key-administration method (create/update/destroy/enable/disable/IAM) --
// this is what makes it structurally impossible for the pin-capture path to
// also sign or administer keys, not merely a convention (see
// boundary_test.go). A *kms.KeyManagementClient satisfies this interface
// without any adapter code, because it already implements every method
// below with an identical signature.
type PublicKeyClient interface {
	GetCryptoKeyVersion(ctx context.Context, req *kmspb.GetCryptoKeyVersionRequest, opts ...gax.CallOption) (*kmspb.CryptoKeyVersion, error)
	GetPublicKey(ctx context.Context, req *kmspb.GetPublicKeyRequest, opts ...gax.CallOption) (*kmspb.PublicKey, error)
}

var (
	// ErrKeyVersionNotEnabled means CaptureFromKMS was asked to pin a
	// version that is not currently ENABLED. ADR-045 §7C requires capturing
	// the public key material WHILE the version is ENABLED (step b); a
	// version already disabled or destroyed by the time capture is
	// attempted has, per §7C, already suffered the operational governance
	// violation §7C describes -- this function refuses to proceed rather
	// than attempt a capture that cannot satisfy the requirement.
	ErrKeyVersionNotEnabled = errors.New("keypinning: CryptoKeyVersion is not ENABLED; its public key cannot be captured for pinning")

	// ErrKeyOutsideApprovedLineage means the CryptoKeyVersion named for
	// capture does not belong to the caller-supplied approved signing
	// lineage. Capturing (and later trusting) a pin requires the same
	// out-of-band authorization anchor verification used at record
	// verification time (ADR-045 §7A) -- a pin is provenance evidence, not
	// a source of authorization, and this function never pins material for
	// a key it cannot show belongs to the approved lineage.
	ErrKeyOutsideApprovedLineage = errors.New("keypinning: CryptoKeyVersion is outside the approved signing lineage; refusing to capture a pin for it")
)

// algorithmFromKMS maps the provider's algorithm enum to this package's own
// provider-agnostic Algorithm type, rejecting anything this Recovery
// Authority protocol cannot use (see Algorithm.Supported).
func algorithmFromKMS(alg kmspb.CryptoKeyVersion_CryptoKeyVersionAlgorithm) (Algorithm, error) {
	mapped := Algorithm(alg.String())
	if !mapped.Supported() {
		return "", fmt.Errorf("%w: %s", ErrUnsupportedAlgorithm, alg.String())
	}
	return mapped, nil
}

// CaptureFromKMS implements ADR-045 §7C's rotation-order steps (b)–(c):
// retrieve a CryptoKeyVersion's public key while it is ENABLED, and produce
// a validated PinnedKey ready for Store.Pin. It does not itself write to a
// Store -- the caller performs that step, and step (f)'s confirmation gate
// is SafeToDisable, re-reading the store independently rather than trusting
// this function's return value alone.
//
// approvedLineage MUST be the same caller-independent trust anchor used at
// verification time (ADR-045 §7A) -- this function refuses to pin material
// for a key outside it, so a pin can never be captured for an unauthorized
// key even by administrative accident.
func CaptureFromKMS(
	ctx context.Context,
	client PublicKeyClient,
	keyVersionResourceName string,
	approvedLineage recovery.ApprovedSigningLineage,
	provenanceNote string,
) (PinnedKey, error) {
	keyID, err := protocol.NewSigningKeyID(keyVersionResourceName)
	if err != nil {
		return PinnedKey{}, fmt.Errorf("keypinning: %w", err)
	}
	if approvedLineage == nil {
		return PinnedKey{}, errors.New("keypinning: approvedLineage must be supplied -- capture never pins material for an unauthorized key")
	}
	if !approvedLineage(keyID) {
		return PinnedKey{}, fmt.Errorf("%w: %s", ErrKeyOutsideApprovedLineage, keyID.String())
	}

	version, err := client.GetCryptoKeyVersion(ctx, &kmspb.GetCryptoKeyVersionRequest{Name: keyVersionResourceName})
	if err != nil {
		return PinnedKey{}, fmt.Errorf("keypinning: get CryptoKeyVersion state: %w", err)
	}
	if version.GetState() != kmspb.CryptoKeyVersion_ENABLED {
		return PinnedKey{}, fmt.Errorf("%w: state is %s", ErrKeyVersionNotEnabled, version.GetState())
	}
	algorithm, err := algorithmFromKMS(version.GetAlgorithm())
	if err != nil {
		return PinnedKey{}, err
	}

	publicKey, err := client.GetPublicKey(ctx, &kmspb.GetPublicKeyRequest{Name: keyVersionResourceName})
	if err != nil {
		return PinnedKey{}, fmt.Errorf("keypinning: get public key: %w", err)
	}
	if publicKey.GetName() != keyVersionResourceName {
		return PinnedKey{}, fmt.Errorf("keypinning: provider returned a public key for %q, requested %q", publicKey.GetName(), keyVersionResourceName)
	}
	if Algorithm(publicKey.GetAlgorithm().String()) != algorithm {
		return PinnedKey{}, fmt.Errorf("keypinning: GetCryptoKeyVersion and GetPublicKey disagree on algorithm (%s vs %s)", algorithm, publicKey.GetAlgorithm())
	}

	return newValidatedPin(keyID, algorithm, publicKey.GetPem(), provenanceNote, time.Now().UTC())
}
