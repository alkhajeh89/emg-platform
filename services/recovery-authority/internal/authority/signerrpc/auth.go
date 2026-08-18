package signerrpc

import (
	"context"
)

// TokenSource supplies a bearer credential Client attaches to every
// outgoing request. Production callers use GoogleIDTokenSource
// (Application Default Credentials / Workload Identity Federation --
// never a static key). Tests inject a fake.
type TokenSource interface {
	Token(ctx context.Context) (string, error)
}

// IdentityVerifier authenticates an incoming bearer token and returns the
// caller's verified identity (e.g. a service-account email), or an error
// if the token is invalid, expired, or names an unrecognized caller.
// Server rejects every request an IdentityVerifier does not affirmatively
// approve -- there is no "unauthenticated but allowed" path.
type IdentityVerifier interface {
	Verify(ctx context.Context, bearerToken string) (callerIdentity string, err error)
}
