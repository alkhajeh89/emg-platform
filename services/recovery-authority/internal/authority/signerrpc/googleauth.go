package signerrpc

import (
	"context"
	"errors"
	"fmt"

	"golang.org/x/oauth2"
	"google.golang.org/api/idtoken"
)

// GoogleIDTokenSource is the production TokenSource: it mints a
// Google-signed OIDC ID token for the calling workload's own identity
// (Application Default Credentials -- GKE Workload Identity, or any other
// ADC-compatible source), scoped to audience (normally the signing
// service's own URL). No static key file is read; NewGoogleIDTokenSource
// never accepts one.
type GoogleIDTokenSource struct {
	source oauth2.TokenSource
}

// NewGoogleIDTokenSource constructs a GoogleIDTokenSource using ADC only.
func NewGoogleIDTokenSource(ctx context.Context, audience string) (*GoogleIDTokenSource, error) {
	if audience == "" {
		return nil, errors.New("signerrpc: audience is required")
	}
	source, err := idtoken.NewTokenSource(ctx, audience)
	if err != nil {
		return nil, fmt.Errorf("signerrpc: construct ADC ID token source: %w", err)
	}
	return &GoogleIDTokenSource{source: source}, nil
}

func (g *GoogleIDTokenSource) Token(_ context.Context) (string, error) {
	token, err := g.source.Token()
	if err != nil {
		return "", fmt.Errorf("signerrpc: mint ID token: %w", err)
	}
	if token.AccessToken == "" {
		return "", errors.New("signerrpc: ADC ID token source returned an empty token")
	}
	return token.AccessToken, nil
}

var _ TokenSource = (*GoogleIDTokenSource)(nil)

// GoogleIDTokenVerifier is the production IdentityVerifier: it
// cryptographically verifies a Google-signed OIDC ID token against
// Google's own public keys (fetched and cached internally by the
// idtoken package -- never a locally-stored key), checks the audience,
// and requires the token's "email" claim be a member of an explicit,
// caller-supplied allow-list. There is no wildcard/any-caller mode.
type GoogleIDTokenVerifier struct {
	audience      string
	allowedEmails map[string]bool
}

var ErrEmptyAllowedCallerList = errors.New("signerrpc: at least one allowed caller identity is required")

// NewGoogleIDTokenVerifier constructs a verifier that accepts only
// tokens whose "email" claim is in allowedCallerEmails and whose
// audience matches audience exactly.
func NewGoogleIDTokenVerifier(audience string, allowedCallerEmails []string) (*GoogleIDTokenVerifier, error) {
	if audience == "" {
		return nil, errors.New("signerrpc: audience is required")
	}
	if len(allowedCallerEmails) == 0 {
		return nil, ErrEmptyAllowedCallerList
	}
	allowed := make(map[string]bool, len(allowedCallerEmails))
	for _, email := range allowedCallerEmails {
		if email == "" {
			return nil, errors.New("signerrpc: allowed caller email must not be empty")
		}
		allowed[email] = true
	}
	return &GoogleIDTokenVerifier{audience: audience, allowedEmails: allowed}, nil
}

func (g *GoogleIDTokenVerifier) Verify(ctx context.Context, bearerToken string) (string, error) {
	if bearerToken == "" {
		return "", ErrMissingBearerToken
	}
	payload, err := idtoken.Validate(ctx, bearerToken, g.audience)
	if err != nil {
		return "", fmt.Errorf("%w: %v", ErrCallerNotAuthorized, err)
	}
	email, _ := payload.Claims["email"].(string)
	if email == "" || !g.allowedEmails[email] {
		return "", fmt.Errorf("%w: identity %q is not on the allowed caller list", ErrCallerNotAuthorized, email)
	}
	emailVerified, _ := payload.Claims["email_verified"].(bool)
	if !emailVerified {
		return "", fmt.Errorf("%w: token's email claim is not verified", ErrCallerNotAuthorized)
	}
	return email, nil
}

var _ IdentityVerifier = (*GoogleIDTokenVerifier)(nil)
