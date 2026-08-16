// Package kmsverifier is the production realization of
// recovery.CommittedSignatureVerifier (ADR-045 §7A steps 4-6), wiring
// keypinning (step 4: resolve the exact historical public key from durable
// pinned material, never a live provider call) and compromiseledger (step
// 5: apply compromise/distrust semantics) together with cryptographic
// verification (step 6) in the exact order ADR-045 §7A mandates. Steps 1-3
// (content binding, key authorization/lineage, digest recomputation) are
// recovery.VerifyPersistedCommitted's responsibility, upstream of this
// package -- this Verifier is only ever reached after those already
// passed, and it has no ability to skip back and re-decide them.
//
// This package has NO signing capability: it never imports kmssigner and
// never calls AsymmetricSign (see boundary_test.go).
package kmsverifier

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/compromiseledger"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

var (
	// ErrNoPinnedKey means no pinned public key exists for the payload's
	// SigningKeyID. Fails closed (ADR-045 §7C, Attack 21): a missing pin
	// for a key that would otherwise need historical verification is never
	// treated as "not yet compromised, therefore acceptable."
	ErrNoPinnedKey = errors.New("kmsverifier: no pinned public key exists for this SigningKeyID")

	// ErrRequiresManualReview means the compromise ledger reports this
	// record's trusted commit_timestamp is at or after a declared
	// distrust-effective-time for its signing key (or lineage). ADR-045
	// §7: this is NOT auto-accepted and NOT auto-rejected by ordinary
	// automated verification -- callers MUST route this to separate,
	// manual, audited review, and MUST NOT treat a nil error / successful
	// activation as available in this case. VerifyCommittedSignature
	// always returns this (or another non-nil error) here; it never
	// returns nil.
	ErrRequiresManualReview = errors.New("kmsverifier: signing key or lineage requires manual compromise review for this record's timestamp")

	// ErrCompromiseLedgerUnavailable means the ledger itself could not be
	// consulted. Fails closed (ADR-045 §7's fail-closed scope): an
	// inability to rule out an undetected compromise is itself a
	// verification failure, never treated as "not distrusted."
	ErrCompromiseLedgerUnavailable = errors.New("kmsverifier: compromise ledger unavailable")

	// ErrSignatureInvalid wraps a cryptographic verification failure.
	ErrSignatureInvalid = errors.New("kmsverifier: signature verification failed")
)

// Verifier is the production CommittedSignatureVerifier realization,
// verified via compile-time assertion against that exact interface in
// verifier_test.go, without this package importing recovery's Go type
// beyond that assertion (structural typing keeps this package usable
// without a hard dependency on recovery's other exports).
type Verifier struct {
	pins   keypinning.Store
	ledger compromiseledger.Ledger
}

// New wires a Verifier from a pinned-key store and a compromise ledger.
// Neither argument may be nil -- a Verifier with no ledger configured
// would silently skip ADR-045 §7's mandatory compromise check, which this
// constructor refuses to allow.
func New(pins keypinning.Store, ledger compromiseledger.Ledger) (*Verifier, error) {
	if pins == nil {
		return nil, errors.New("kmsverifier: pins store is required")
	}
	if ledger == nil {
		return nil, errors.New("kmsverifier: compromise ledger is required")
	}
	return &Verifier{pins: pins, ledger: ledger}, nil
}

// VerifyCommittedSignature implements ADR-045 §7A steps 4-6, strictly in
// order: (4) resolve the pinned historical public key for keyID; (5) apply
// compromise/distrust semantics via the ledger, using signedAt (the
// payload's own trusted commit_timestamp) as the comparison anchor; only
// if that check clears does it (6) cryptographically verify signature
// against digest and the resolved public key. No step is skipped, and a
// failure at step 4 or 5 never proceeds to step 6 -- ADR-045 §7A: "No step
// may be skipped, reordered around, or treated as redundant with another."
func (v *Verifier) VerifyCommittedSignature(
	ctx context.Context,
	keyID protocol.SigningKeyID,
	signedAt time.Time,
	digest protocol.Digest32,
	signature []byte,
) error {
	// Step 4: resolve the pinned public key. Never a live provider call.
	pin, err := v.pins.Get(ctx, keyID)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrNoPinnedKey, err)
	}

	// Step 5: apply compromise/distrust semantics BEFORE cryptographic
	// verification, exactly as ADR-045 §7A orders it.
	status, err := v.ledger.Status(ctx, compromiseledger.SigningKeyIDSubject(keyID), signedAt)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrCompromiseLedgerUnavailable, err)
	}
	if status == compromiseledger.StatusRequiresManualReview {
		return ErrRequiresManualReview
	}

	// Step 6: cryptographic verification against the pinned material.
	publicKey, err := keypinning.ParsePEMPublicKey([]byte(pin.PublicKeyPEM))
	if err != nil {
		return fmt.Errorf("kmsverifier: pinned public key material is malformed: %w", err)
	}
	if err := pin.Algorithm.VerifyDigestSignature(publicKey, digest.Bytes(), signature); err != nil {
		return fmt.Errorf("%w: %v", ErrSignatureInvalid, err)
	}
	return nil
}
