// Package signerrpc is the narrow, internal RPC boundary between the
// Recovery Authority runtime process (Spanner Commit + GCS witness) and
// the separately-deployed signing process (Cloud KMS AsymmetricSign).
//
// Why this package exists (S5 process-role analysis): ADR-045 §10's
// corrected construction sequence (rotationcommit.buildCommittedPayload)
// must run inside the same OS process that holds the live
// acceptedRotationContext -- that type is deliberately impossible to
// serialize or reconstruct outside rotationcommit, by design (ADR-044
// §7), so it can never cross a process boundary. That function calls a
// rotationcommit.Signer directly and synchronously. ADR-045's own threat
// model (§13, Attack 3: "Signer workload replaced by a malicious
// signer... cannot reach Spanner/GCS") describes the signer as a
// SEPARATE workload from the Spanner/witness runtime -- if signing ran
// in the same process as the Spanner-committing code, a compromise of
// that process would trivially reach both, contradicting Attack 3's own
// containment claim and ADR-044 §15's "the witness/recovery runtime MUST
// NOT possess private signing authority."
//
// This package resolves that by keeping buildCommittedPayload's Signer
// argument entirely satisfiable in-process (no protocol change, no
// interface change) while making the CONCRETE implementation a thin
// network client: Client (this package) implements the same two-method
// shape kmssigner.Signer does, but forwards each call over an
// authenticated HTTPS request to a separately-deployed process running
// Server (this package), which wraps the real kmssigner.Signer and holds
// the only credential capable of Cloud KMS AsymmetricSign. Only a digest
// and a signature ever cross this wire -- never acceptedRotationContext,
// never private key material.
package signerrpc

import (
	"context"
	"errors"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// Signer is the same two-method shape rotationcommit.Signer requires
// (ADR-045 §10), restated locally so this package never needs to import
// rotationcommit (avoiding any coupling to Spanner-adjacent code) or
// kmssigner (avoiding any coupling to KMS-adjacent code). Both already
// satisfy this interface structurally.
type Signer interface {
	ActiveKeyID(ctx context.Context) (protocol.SigningKeyID, error)
	SignCommittedDigest(ctx context.Context, digest protocol.Digest32) (signature []byte, keyID protocol.SigningKeyID, err error)
}

var (
	ErrCallerNotAuthorized = errors.New("signerrpc: caller identity is not authorized to invoke the signing service")
	ErrMissingBearerToken  = errors.New("signerrpc: request has no bearer token")
	ErrRemoteSigner        = errors.New("signerrpc: remote signer returned an error")
	ErrMalformedResponse   = errors.New("signerrpc: malformed response from signing service")
)

// activeKeyIDResponse and signRequest/signResponse are the wire shapes.
// Only public, non-sensitive values ever appear here: a digest is a
// public SHA-256 hash, a SigningKeyID is a public Cloud KMS resource
// name, and a signature is the public output of a signing operation --
// never a private key, never acceptedRotationContext.
type activeKeyIDResponse struct {
	KeyID string `json:"key_id"`
}

type signRequest struct {
	DigestHex string `json:"digest_hex"`
}

type signResponse struct {
	SignatureHex string `json:"signature_hex"`
	KeyID        string `json:"key_id"`
}

type errorResponse struct {
	Error string `json:"error"`
}
