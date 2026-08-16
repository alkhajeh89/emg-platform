package protocol

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"sort"
)

// DomainSeparator identifies one canonical ADR-043 record family.
type DomainSeparator string

const (
	DomainPrepared           DomainSeparator = "EMG-ADR043-PREPARED-V1"
	DomainCommitted          DomainSeparator = "EMG-ADR043-COMMITTED-V1"
	DomainAmbiguousTombstone DomainSeparator = "EMG-ADR043-AMBIGUOUS-TOMBSTONE-V1"
	DomainEpochTermination   DomainSeparator = "EMG-ADR043-EPOCH-TERMINATION-V1"
	DomainNewEpochGenesis    DomainSeparator = "EMG-ADR043-NEW-EPOCH-GENESIS-V1"
	DomainAuthorityState     DomainSeparator = "EMG-ADR043-AUTHORITY-STATE-V1"
	DomainRotationCandidate  DomainSeparator = "EMG-ADR043-ROTATION-CANDIDATE-V1"

	// DomainCommittedV2 is the additive V2 COMMITTED domain separator
	// (ADR-045 §9): a new, disjoint digest namespace binding signing_key_id
	// into the canonical record. It never replaces, and is never confused
	// with, DomainCommitted (V1) above -- V1 records remain byte-for-byte
	// governed by DomainCommitted forever.
	DomainCommittedV2 DomainSeparator = "EMG-ADR044-COMMITTED-V2"
)

var ErrUnsupportedCanonicalValue = errors.New("unsupported deterministic CBOR value")

// EncodeDeterministicCBOR encodes the deliberately small protocol value set
// using RFC 8949 deterministic ordering and shortest-length integer forms.
// Decoders are intentionally deferred; future decoders must reject unknown or
// duplicate fields rather than silently accepting them.
func EncodeDeterministicCBOR(value any) ([]byte, error) {
	var output bytes.Buffer
	if err := encodeCBORValue(&output, value); err != nil {
		return nil, err
	}
	return output.Bytes(), nil
}

func encodeCBORValue(output *bytes.Buffer, value any) error {
	switch typed := value.(type) {
	case nil:
		output.WriteByte(0xf6)
	case bool:
		if typed {
			output.WriteByte(0xf5)
		} else {
			output.WriteByte(0xf4)
		}
	case uint64:
		writeCBORHead(output, 0, typed)
	case uint32:
		writeCBORHead(output, 0, uint64(typed))
	case uint:
		writeCBORHead(output, 0, uint64(typed))
	case int:
		if typed >= 0 {
			writeCBORHead(output, 0, uint64(typed))
		} else {
			writeCBORHead(output, 1, uint64(-1-typed))
		}
	case string:
		writeCBORHead(output, 3, uint64(len(typed)))
		output.WriteString(typed)
	case []byte:
		writeCBORHead(output, 2, uint64(len(typed)))
		output.Write(typed)
	case []any:
		writeCBORHead(output, 4, uint64(len(typed)))
		for _, item := range typed {
			if err := encodeCBORValue(output, item); err != nil {
				return err
			}
		}
	case map[string]any:
		return encodeCBORMap(output, typed)
	default:
		return fmt.Errorf("%w: %T", ErrUnsupportedCanonicalValue, value)
	}
	return nil
}

type encodedMapEntry struct {
	key   []byte
	value any
}

func encodeCBORMap(output *bytes.Buffer, value map[string]any) error {
	entries := make([]encodedMapEntry, 0, len(value))
	for key, item := range value {
		encodedKey, err := EncodeDeterministicCBOR(key)
		if err != nil {
			return err
		}
		entries = append(entries, encodedMapEntry{key: encodedKey, value: item})
	}
	sort.Slice(entries, func(left, right int) bool {
		if len(entries[left].key) != len(entries[right].key) {
			return len(entries[left].key) < len(entries[right].key)
		}
		return bytes.Compare(entries[left].key, entries[right].key) < 0
	})
	writeCBORHead(output, 5, uint64(len(entries)))
	for _, entry := range entries {
		output.Write(entry.key)
		if err := encodeCBORValue(output, entry.value); err != nil {
			return err
		}
	}
	return nil
}

func writeCBORHead(output *bytes.Buffer, major byte, value uint64) {
	switch {
	case value < 24:
		output.WriteByte(major<<5 | byte(value))
	case value <= 0xff:
		output.WriteByte(major<<5 | 24)
		output.WriteByte(byte(value))
	case value <= 0xffff:
		output.WriteByte(major<<5 | 25)
		var encoded [2]byte
		binary.BigEndian.PutUint16(encoded[:], uint16(value))
		output.Write(encoded[:])
	case value <= 0xffffffff:
		output.WriteByte(major<<5 | 26)
		var encoded [4]byte
		binary.BigEndian.PutUint32(encoded[:], uint32(value))
		output.Write(encoded[:])
	default:
		output.WriteByte(major<<5 | 27)
		var encoded [8]byte
		binary.BigEndian.PutUint64(encoded[:], value)
		output.Write(encoded[:])
	}
}

// HashCanonical hashes a canonical encoding with a NUL-delimited domain.
func HashCanonical(domain DomainSeparator, encoded []byte) Digest32 {
	hasher := sha256.New()
	hasher.Write([]byte(domain))
	hasher.Write([]byte{0})
	hasher.Write(encoded)
	digest, err := NewDigest32(hasher.Sum(nil))
	if err != nil {
		panic("sha256 returned a non-32-byte digest")
	}
	return digest
}
