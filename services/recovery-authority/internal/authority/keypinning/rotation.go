package keypinning

import (
	"context"
	"fmt"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// SafeToDisable implements ADR-045 §7C step (f): the required, auditable
// confirmation gate that a retiring CryptoKeyVersion's public key was
// durably pinned BEFORE that version may be disabled (step g). It never
// trusts a caller's assertion that a pin was made -- it independently
// re-reads store and cross-checks the material against expectedMaterialPEM
// (the exact bytes the caller believes were pinned), so a caller cannot be
// fooled by, for example, a pin write that silently failed or a
// differently-keyed pin. This package does not, and by design cannot,
// perform the disable action itself (see kmssigner/keypinning package docs:
// no key-administration capability exists in this codebase) -- SafeToDisable
// only answers whether it would be safe to do so, for an external,
// separately-authorized administrative action to consult.
//
// A false return here MUST block disablement. There is no override.
func SafeToDisable(ctx context.Context, store Store, keyID protocol.SigningKeyID, expectedMaterialPEM string) (bool, error) {
	if keyID.IsZero() {
		return false, fmt.Errorf("keypinning: SafeToDisable requires a non-zero SigningKeyID")
	}
	pin, err := store.Get(ctx, keyID)
	if err != nil {
		// Not found, integrity failure, or any other store error: none of
		// these can be treated as "safe" -- ADR-045 §7C's confirmation gate
		// is affirmative-proof-required, not absence-of-evidence-permits.
		return false, nil
	}
	if computeFingerprint(expectedMaterialPEM) != computeFingerprint(pin.PublicKeyPEM) {
		return false, nil
	}
	return true, nil
}
