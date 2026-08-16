package keypinning

import (
	"errors"
	"fmt"
	"regexp"
	"strings"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/recovery"
)

// cryptoKeyResourceName matches a Cloud KMS CryptoKey resource name (no
// trailing CryptoKeyVersion segment).
var cryptoKeyResourceName = regexp.MustCompile(
	`^projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/]+$`,
)

// cryptoKeyVersionResourceName matches a full CryptoKeyVersion resource
// name -- exactly the shape a SigningKeyID must have for the GCP-native
// realization this package targets.
var cryptoKeyVersionResourceName = regexp.MustCompile(
	`^projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/]+/cryptoKeyVersions/[^/]+$`,
)

var ErrInvalidCryptoKeyResourceName = errors.New("keypinning: not a well-formed Cloud KMS CryptoKey resource name")

// CryptoKeyLineage builds the caller-independent recovery.ApprovedSigningLineage
// predicate ADR-045 §7A requires: every legitimate SigningKeyID for this
// environment/resource must be a CryptoKeyVersion under exactly this one
// approved CryptoKey. approvedCryptoKey must be the full CryptoKey resource
// name (no /cryptoKeyVersions/... suffix); this function computes the
// version-scoped prefix itself, including the disambiguating trailing
// "/cryptoKeyVersions/" segment boundary, so a key named e.g. "my-key-2"
// can never satisfy a lineage approved for "my-key" merely by sharing a
// string prefix (Attack B, key-lineage confusion).
func CryptoKeyLineage(approvedCryptoKey string) (recovery.ApprovedSigningLineage, error) {
	if !cryptoKeyResourceName.MatchString(approvedCryptoKey) {
		return nil, fmt.Errorf("%w: %q", ErrInvalidCryptoKeyResourceName, approvedCryptoKey)
	}
	prefix := approvedCryptoKey + "/cryptoKeyVersions/"
	return func(keyID protocol.SigningKeyID) bool {
		candidate := keyID.String()
		if !cryptoKeyVersionResourceName.MatchString(candidate) {
			return false
		}
		return strings.HasPrefix(candidate, prefix)
	}, nil
}
