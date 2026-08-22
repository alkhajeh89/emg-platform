// Package gcswitness is the bounded ADR-043 GCS witness adapter. It
// implements exactly two operations against Google Cloud Storage --
// create-if-absent and exact-key read -- and nothing else. Per the frozen
// ADR-043 architecture, GCS is a passive, immutable rollback witness only:
// this package cannot decide Spanner CAS success, cannot construct an
// AcceptedRotationContext, cannot sign a COMMITTED payload, and cannot
// alter Spanner in any way. It only ever persists and reads back opaque,
// already-signed bytes handed to it by the caller.
//
// This package uses only the qualified SDK path: cloud.google.com/go/storage
// v1.64.0 (see the ADR-043 GCS SDK qualification), storage.NewClient (never
// storage.NewGRPCClient), Writer.ChunkSize = 0 (a single, non-resumable,
// SDK-non-retryable multipart request -- see the qualification's
// UPLOAD_MODE_RESULT/RETRY_ANALYSIS), and storage.Conditions{DoesNotExist:
// true} (which the SDK translates to ifGenerationMatch=0 on the wire).
//
// No *storage.Client, *storage.BucketHandle, or *storage.ObjectHandle ever
// leaves this package. No Delete, Update, Compose, Copy, ACL, retention, or
// bucket-mutation method is ever called here.
package gcswitness

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"

	"cloud.google.com/go/storage"
	"google.golang.org/api/googleapi"
	"google.golang.org/api/option"
)

// MaxPayloadBytes bounds the size of any object this adapter will create or
// read. ADR-043 witness records (PREPARED/COMMITTED) are small, deterministic
// CBOR records; this ceiling exists to fail closed on anything else rather
// than silently accept or attempt to buffer an unbounded read.
const MaxPayloadBytes = 64 * 1024

// CreateOutcome classifies the result of one CreateExactIfAbsent call.
//
// The zero value, AmbiguousCreate, is deliberately the safest possible
// default -- consistent with every other security-relevant enum in this
// codebase (protocol.AmbiguousCommitOutcome, epoch.StateUnresolvablePreparedOperation):
// any outcome not affirmatively classified as success or a definitive
// failure is treated as unresolved.
type CreateOutcome int

const (
	// AmbiguousCreate means the create's outcome could not be determined
	// (transient transport/network/deadline failure, or a 412 whose
	// follow-up read could not confirm either identical or conflicting
	// content). The caller must not treat this as success.
	AmbiguousCreate CreateOutcome = iota

	// CreateSuccess means the object was newly created by this call, or an
	// ambiguous create was safely resolved by an exact-key read that found
	// byte-identical content to what this call attempted to write.
	CreateSuccess

	// AlreadyExistsIdentical means the precondition failed (object already
	// exists) and an exact-key read confirmed the existing bytes are
	// byte-identical to what this call attempted to write -- a safe,
	// idempotent outcome.
	AlreadyExistsIdentical

	// AlreadyExistsConflict means the precondition failed (object already
	// exists) and an exact-key read found different bytes than what this
	// call attempted to write. This is a fail-closed condition: the caller
	// must never treat this as success, must never overwrite, and must
	// never fall back to an alternate key.
	AlreadyExistsConflict

	// HardFailure means a definitive, non-retryable, non-ambiguous failure
	// (authentication, authorization, malformed request, or similar
	// configuration-level error) that a later read cannot resolve.
	HardFailure
)

func (o CreateOutcome) String() string {
	switch o {
	case CreateSuccess:
		return "CREATE_SUCCESS"
	case AlreadyExistsIdentical:
		return "ALREADY_EXISTS_IDENTICAL"
	case AlreadyExistsConflict:
		return "ALREADY_EXISTS_CONFLICT"
	case HardFailure:
		return "HARD_FAILURE"
	default:
		return "AMBIGUOUS_CREATE"
	}
}

// Sentinel errors. Callers should use errors.Is against these, never parse
// error message strings.
var (
	ErrNotFound        = errors.New("gcswitness: object not found")
	ErrPayloadTooLarge = errors.New("gcswitness: payload exceeds maximum size")
	ErrCorruptRead     = errors.New("gcswitness: corrupt or partial read")
	ErrConflict        = errors.New("gcswitness: object exists with conflicting content")
	ErrEmptyPayload    = errors.New("gcswitness: payload must not be empty")
)

// ImmutableWitness is the narrow, provider-independent capability this
// package provides. Nothing in this codebase should ever need more than
// this from a witness store.
type ImmutableWitness interface {
	CreateExactIfAbsent(ctx context.Context, key string, payload []byte) (CreateOutcome, error)
	ReadExact(ctx context.Context, key string) ([]byte, error)
	Exists(ctx context.Context, key string) (bool, error)
}

// NewClient is the sole call site in this package permitted to construct a
// *storage.Client. It always uses storage.NewClient -- the qualified
// HTTP/JSON transport -- and never storage.NewGRPCClient. Passing
// option.WithEndpoint / option.WithoutAuthentication / option.WithHTTPClient
// here is how emulator-tier tests point this at a local fake; production
// credential wiring is out of scope for this package.
func NewClient(ctx context.Context, opts ...option.ClientOption) (*storage.Client, error) {
	return storage.NewClient(ctx, opts...)
}

// Adapter implements ImmutableWitness against one GCS bucket. Its only
// state is an unexported *storage.BucketHandle -- callers never receive it,
// and nothing broader than the two methods below is reachable through this
// type.
type Adapter struct {
	bucket          *storage.BucketHandle
	maxPayloadBytes int
}

// New wraps an already-constructed *storage.Client (see NewClient) and a
// bucket name into an Adapter. The client is not retained beyond deriving
// the bucket handle; nothing about it is exposed.
func New(client *storage.Client, bucketName string) *Adapter {
	return &Adapter{
		bucket:          client.Bucket(bucketName),
		maxPayloadBytes: MaxPayloadBytes,
	}
}

var _ ImmutableWitness = (*Adapter)(nil)

// CreateExactIfAbsent is the only write path this package exposes. It
// writes payload to key using storage.Conditions{DoesNotExist: true}
// (ifGenerationMatch=0 on the wire) and Writer.ChunkSize = 0 (a single,
// non-resumable, SDK-non-retryable request -- see the package doc). It
// never regenerates or transforms payload, never retries Writer.Close
// internally, and never creates a second key on conflict.
func (a *Adapter) CreateExactIfAbsent(ctx context.Context, key string, payload []byte) (CreateOutcome, error) {
	if len(payload) == 0 {
		return HardFailure, ErrEmptyPayload
	}
	if len(payload) > a.maxPayloadBytes {
		return HardFailure, fmt.Errorf("%w: %d bytes", ErrPayloadTooLarge, len(payload))
	}
	// Defensive copy: this call must never be affected by the caller
	// mutating its slice concurrently with the write.
	body := append([]byte(nil), payload...)

	writer := a.bucket.Object(key).If(storage.Conditions{DoesNotExist: true}).NewWriter(ctx)
	writer.ChunkSize = 0

	_, writeErr := writer.Write(body)
	closeErr := writer.Close()
	err := closeErr
	if err == nil {
		err = writeErr
	}
	if err == nil {
		return CreateSuccess, nil
	}
	return a.classifyCreateError(ctx, key, body, err)
}

// classifyCreateError implements the required outcome table: a precondition
// failure (412) or any other non-definitive failure is resolved, and only
// resolved, by an exact-key read compared byte-for-byte against the exact
// bytes this call attempted to write. A definitive hard failure (bad
// request, auth, permission) is never sent through read-resolution --
// resolving those via a later read would be exactly the kind of
// "later-read-changes-the-classification" reasoning ADR-043 forbids for
// Spanner Commit, and it is equally forbidden here.
func (a *Adapter) classifyCreateError(ctx context.Context, key string, attempted []byte, err error) (CreateOutcome, error) {
	if isHardFailure(err) {
		return HardFailure, fmt.Errorf("gcswitness: create failed: %w", err)
	}

	// Either a 412 (object already exists) or a transient/ambiguous
	// transport failure: in both cases the only safe next step is an
	// exact-key read compared against the bytes we ourselves hold, never a
	// LIST, never trusting the error message text.
	existing, readErr := a.ReadExact(ctx, key)
	switch {
	case errors.Is(readErr, ErrNotFound):
		// The object is not there. This does NOT prove the original create
		// never reached GCS -- e.g. the request could still be in flight at
		// the server, or reads could lag a write that has not yet been
		// acknowledged locally. Per the required rule, absence must never
		// be silently treated as proof of non-creation. Remain ambiguous.
		return AmbiguousCreate, fmt.Errorf("gcswitness: create ambiguous, object absent on read: %w", err)
	case readErr != nil:
		return AmbiguousCreate, fmt.Errorf("gcswitness: create ambiguous, read-resolution failed: %w", errors.Join(err, readErr))
	case bytes.Equal(existing, attempted):
		if isPreconditionFailed(err) {
			return AlreadyExistsIdentical, nil
		}
		// An ambiguous transport failure whose retry-shaped read found our
		// own exact bytes already present -- safe success resolution, per
		// the qualification's AMBIGUOUS_WRITE_ANALYSIS: this is possible
		// only because the create was itself precondition-gated, the key is
		// deterministic, and the bytes being compared are the exact bytes
		// already held by the live writer, not a trust decision about
		// provenance.
		return CreateSuccess, nil
	default:
		return AlreadyExistsConflict, fmt.Errorf("%w: key=%q", ErrConflict, key)
	}
}

// isPreconditionFailed reports whether err is the structural HTTP 412 /
// conditionNotMet response. No string parsing: only the typed status code
// is inspected.
func isPreconditionFailed(err error) bool {
	var apiErr *googleapi.Error
	return errors.As(err, &apiErr) && apiErr.Code == 412
}

// isHardFailure reports whether err is a definitive, non-ambiguous failure
// that a later read must never be used to resolve. Deliberately a narrow
// allowlist (bad request, unauthenticated, forbidden, not found at the
// bucket/config level) -- everything else, including unrecognized status
// codes, defaults to ambiguous and goes through read-resolution, matching
// this codebase's established fail-closed-by-default idiom.
func isHardFailure(err error) bool {
	var apiErr *googleapi.Error
	if errors.As(err, &apiErr) {
		switch apiErr.Code {
		case 400, 401, 403, 404:
			return true
		}
	}
	return false
}

// confirmBucketExists independently verifies, via the bucket resource
// endpoint (BucketHandle.Attrs), that this Adapter's bucket genuinely
// exists and is reachable. It exists solely to resolve one specific
// ambiguity the object resource endpoint cannot: cloud.google.com/go/storage
// returns the identical storage.ErrObjectNotExist sentinel (HTTP 404) from
// an object-level call (ObjectHandle.Attrs / NewReader) whether the named
// object is genuinely absent from an existing bucket, OR the bucket itself
// does not exist at all -- confirmed empirically against real GCS (Wave 2
// Track C real-cloud qualification) and consistent with the SDK's own
// design: storage.ErrBucketNotExist is documented as the bucket-resource
// endpoint's distinct sentinel, never returned by an object-resource call.
// A missing/unreachable bucket must never be silently reported as "object
// absent" -- ADR-044/045's fail-closed model requires provider
// unavailability to surface as an error, never be reinterpreted as an
// empty governance state (compromiseledger's compromise ledger, keypinning's
// pin store, and the ADR-044 witness bucket all depend on this
// distinction). Any non-nil result here -- bucket genuinely missing,
// permission denied on the bucket itself, or a transient failure -- is
// treated identically: this call cannot confirm object absence, so the
// caller must fail closed rather than proceed as if the object were simply
// not yet created.
func (a *Adapter) confirmBucketExists(ctx context.Context) error {
	if _, err := a.bucket.Attrs(ctx); err != nil {
		return fmt.Errorf("gcswitness: bucket unavailable or unreachable: %w", err)
	}
	return nil
}

// ReadExact returns the exact bytes stored at key. It addresses only the
// exact deterministic key given -- it never uses LIST for correctness. It
// fails closed on a partial or corrupt read: the SDK's own CRC32C
// validation (performed on Reader.Close by default) is checked before any
// bytes are returned as successful.
func (a *Adapter) ReadExact(ctx context.Context, key string) ([]byte, error) {
	reader, err := a.bucket.Object(key).NewReader(ctx)
	if err != nil {
		if errors.Is(err, storage.ErrObjectNotExist) {
			if bucketErr := a.confirmBucketExists(ctx); bucketErr != nil {
				return nil, bucketErr
			}
			return nil, fmt.Errorf("gcswitness: %w", ErrNotFound)
		}
		return nil, fmt.Errorf("gcswitness: open reader: %w", err)
	}

	// Read at most maxPayloadBytes+1 so an oversized object is detected
	// (and rejected) rather than fully buffered into memory.
	limited := io.LimitReader(reader, int64(a.maxPayloadBytes)+1)
	data, readErr := io.ReadAll(limited)
	closeErr := reader.Close()

	if readErr != nil {
		return nil, fmt.Errorf("gcswitness: %w: %v", ErrCorruptRead, readErr)
	}
	if closeErr != nil {
		// Reader.Close performs the SDK's checksum validation; a non-nil
		// error here means the bytes already handed back do not match the
		// object's own checksum. Fail closed: never return data alongside
		// a corruption error.
		return nil, fmt.Errorf("gcswitness: %w: %v", ErrCorruptRead, closeErr)
	}
	if len(data) > a.maxPayloadBytes {
		return nil, fmt.Errorf("%w: object at %q", ErrPayloadTooLarge, key)
	}
	return data, nil
}

// Exists reports whether an object is present at key, without exposing its
// content. A missing/unreachable bucket is never reported as (false, nil)
// -- see confirmBucketExists's doc comment for why that specific ambiguity
// requires an independent bucket-resource check.
func (a *Adapter) Exists(ctx context.Context, key string) (bool, error) {
	_, err := a.bucket.Object(key).Attrs(ctx)
	if err == nil {
		return true, nil
	}
	if errors.Is(err, storage.ErrObjectNotExist) {
		if bucketErr := a.confirmBucketExists(ctx); bucketErr != nil {
			return false, bucketErr
		}
		return false, nil
	}
	return false, fmt.Errorf("gcswitness: exists: %w", err)
}
