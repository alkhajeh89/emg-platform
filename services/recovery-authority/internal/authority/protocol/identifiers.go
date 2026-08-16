package protocol

import (
	"encoding/hex"
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

var environmentIDPattern = regexp.MustCompile(`^[a-z][a-z0-9-]{0,62}$`)

var (
	ErrInvalidEnvironmentID = errors.New("invalid environment ID")
	ErrInvalidUUIDv7        = errors.New("invalid canonical UUIDv7")
	ErrInvalidRevision      = errors.New("invalid canonical revision number")
	ErrInvalidDigest        = errors.New("invalid digest")
	ErrInvalidSigningKeyID  = errors.New("invalid signing key ID")
)

// maxSigningKeyIDLength bounds SigningKeyID (ADR-045 §6: "validated, opaque,
// non-empty, bounded-length string"). 512 bytes is generous headroom over
// any real Cloud KMS CryptoKeyVersion resource name
// (projects/.../locations/.../keyRings/.../cryptoKeys/.../cryptoKeyVersions/N)
// while still being a concrete, enforced bound.
const maxSigningKeyIDLength = 512

// SigningKeyID is a validated, opaque, non-empty, bounded-length identifier
// for the exact signing key version that produced (or will produce) one
// COMMITTED V2 signature (ADR-045 §6, §8). It deliberately encodes no
// provider-specific parsing semantics -- a future non-GCP signing
// realization remains representable without a protocol change. Possession
// of a syntactically valid SigningKeyID never by itself establishes that the
// identified key is authorized to represent the Recovery Authority; that is
// the independent key-authorization check the recovery package performs
// (ADR-045 §7A).
type SigningKeyID struct{ value string }

// NewSigningKeyID validates and constructs a SigningKeyID. Every byte must
// be printable, non-whitespace ASCII (0x21-0x7e) -- broad enough to hold any
// GCP resource name or a future provider's own identifier syntax, narrow
// enough to keep the value safely, unambiguously serializable in the
// deterministic canonical encoding.
func NewSigningKeyID(value string) (SigningKeyID, error) {
	if value == "" || len(value) > maxSigningKeyIDLength {
		return SigningKeyID{}, ErrInvalidSigningKeyID
	}
	for i := 0; i < len(value); i++ {
		if value[i] < 0x21 || value[i] > 0x7e {
			return SigningKeyID{}, ErrInvalidSigningKeyID
		}
	}
	return SigningKeyID{value: value}, nil
}

func (id SigningKeyID) String() string { return id.value }

// IsZero reports whether id is the unset zero value -- never a valid,
// constructed SigningKeyID, since NewSigningKeyID rejects the empty string.
func (id SigningKeyID) IsZero() bool { return id.value == "" }

// EnvironmentID is a validated, canonical deployment-environment identifier.
type EnvironmentID struct{ value string }

func NewEnvironmentID(value string) (EnvironmentID, error) {
	if !environmentIDPattern.MatchString(value) {
		return EnvironmentID{}, ErrInvalidEnvironmentID
	}
	return EnvironmentID{value: value}, nil
}

func (id EnvironmentID) String() string { return id.value }

type uuidV7 struct{ value string }

func parseUUIDv7(value string) (uuidV7, error) {
	if len(value) != 36 || strings.ToLower(value) != value ||
		value[8] != '-' || value[13] != '-' || value[18] != '-' || value[23] != '-' {
		return uuidV7{}, ErrInvalidUUIDv7
	}
	hexText := strings.ReplaceAll(value, "-", "")
	if len(hexText) != 32 {
		return uuidV7{}, ErrInvalidUUIDv7
	}
	if _, err := hex.DecodeString(hexText); err != nil {
		return uuidV7{}, ErrInvalidUUIDv7
	}
	if value[14] != '7' || !strings.ContainsRune("89ab", rune(value[19])) {
		return uuidV7{}, ErrInvalidUUIDv7
	}
	return uuidV7{value: value}, nil
}

// AuthorityEpoch is the UUIDv7 identity of one authority epoch.
type AuthorityEpoch struct{ uuidV7 }

func NewAuthorityEpoch(value string) (AuthorityEpoch, error) {
	id, err := parseUUIDv7(value)
	return AuthorityEpoch{uuidV7: id}, err
}

func (id AuthorityEpoch) String() string { return id.value }

// OperationID is the UUIDv7 identity of one authorized rotation.
type OperationID struct{ uuidV7 }

func NewOperationID(value string) (OperationID, error) {
	id, err := parseUUIDv7(value)
	return OperationID{uuidV7: id}, err
}

func (id OperationID) String() string { return id.value }

// ResourceIncarnationID binds an epoch to one fresh provider resource.
type ResourceIncarnationID struct{ uuidV7 }

func NewResourceIncarnationID(value string) (ResourceIncarnationID, error) {
	id, err := parseUUIDv7(value)
	return ResourceIncarnationID{uuidV7: id}, err
}

func (id ResourceIncarnationID) String() string { return id.value }

// RevisionNumber is an unsigned logical revision within one authority epoch.
type RevisionNumber struct{ value uint64 }

func NewRevisionNumber(value uint64) RevisionNumber { return RevisionNumber{value: value} }

func ParseRevisionNumber(value string) (RevisionNumber, error) {
	if value == "" || (len(value) > 1 && value[0] == '0') || strings.HasPrefix(value, "+") {
		return RevisionNumber{}, ErrInvalidRevision
	}
	parsed, err := strconv.ParseUint(value, 10, 64)
	if err != nil {
		return RevisionNumber{}, fmt.Errorf("%w: %v", ErrInvalidRevision, err)
	}
	return NewRevisionNumber(parsed), nil
}

func (revision RevisionNumber) Uint64() uint64 { return revision.value }

func (revision RevisionNumber) String() string {
	return strconv.FormatUint(revision.value, 10)
}

// Digest32 stores a SHA-256-compatible digest as exactly 32 bytes.
type Digest32 struct{ value [32]byte }

func NewDigest32(value []byte) (Digest32, error) {
	if len(value) != 32 {
		return Digest32{}, ErrInvalidDigest
	}
	var digest [32]byte
	copy(digest[:], value)
	return Digest32{value: digest}, nil
}

func ParseDigest32(value string) (Digest32, error) {
	if len(value) != 64 || strings.ToLower(value) != value {
		return Digest32{}, ErrInvalidDigest
	}
	decoded, err := hex.DecodeString(value)
	if err != nil {
		return Digest32{}, ErrInvalidDigest
	}
	return NewDigest32(decoded)
}

func (digest Digest32) Bytes() []byte {
	result := make([]byte, len(digest.value))
	copy(result, digest.value[:])
	return result
}

func (digest Digest32) String() string { return hex.EncodeToString(digest.value[:]) }
