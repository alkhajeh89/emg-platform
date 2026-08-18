package signerrpc

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// Client implements Signer (and therefore, structurally,
// rotationcommit.Signer) by forwarding every call over HTTPS to a
// separately-deployed Server. It never holds, imports, or constructs
// anything KMS-related -- the only capability this type has is "ask the
// remote signing service to sign a digest," authenticated by tokens
// TokenSource supplies.
type Client struct {
	httpClient *http.Client
	baseURL    string
	tokens     TokenSource
}

// NewClient constructs a Client. baseURL must be an https:// URL unless
// allowInsecure is true (non-production/local-development use only --
// see Attack G in the S5 adversarial matrix: production configuration
// must never permit this).
func NewClient(httpClient *http.Client, baseURL string, tokens TokenSource, allowInsecure bool) (*Client, error) {
	if httpClient == nil {
		return nil, errors.New("signerrpc: httpClient is required")
	}
	if tokens == nil {
		return nil, errors.New("signerrpc: tokens (TokenSource) is required")
	}
	parsed, err := url.Parse(baseURL)
	if err != nil {
		return nil, fmt.Errorf("signerrpc: invalid baseURL: %w", err)
	}
	if parsed.Scheme != "https" && !(allowInsecure && parsed.Scheme == "http") {
		return nil, fmt.Errorf("signerrpc: baseURL must use https (got %q); http is only permitted when allowInsecure is explicitly set", parsed.Scheme)
	}
	return &Client{httpClient: httpClient, baseURL: baseURL, tokens: tokens}, nil
}

func (c *Client) do(ctx context.Context, method, path string, body []byte) (*http.Response, error) {
	token, err := c.tokens.Token(ctx)
	if err != nil {
		return nil, fmt.Errorf("signerrpc: obtain bearer token: %w", err)
	}
	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, reader)
	if err != nil {
		return nil, fmt.Errorf("signerrpc: build request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	return c.httpClient.Do(req)
}

func (c *Client) ActiveKeyID(ctx context.Context) (protocol.SigningKeyID, error) {
	resp, err := c.do(ctx, http.MethodGet, "/v1/active-key-id", nil)
	if err != nil {
		return protocol.SigningKeyID{}, fmt.Errorf("%w: %v", ErrRemoteSigner, err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return protocol.SigningKeyID{}, fmt.Errorf("%w: read response: %v", ErrRemoteSigner, err)
	}
	if resp.StatusCode != http.StatusOK {
		return protocol.SigningKeyID{}, fmt.Errorf("%w: status %d: %s", ErrRemoteSigner, resp.StatusCode, decodeErrorMessage(data))
	}
	var parsed activeKeyIDResponse
	if err := json.Unmarshal(data, &parsed); err != nil {
		return protocol.SigningKeyID{}, fmt.Errorf("%w: %v", ErrMalformedResponse, err)
	}
	keyID, err := protocol.NewSigningKeyID(parsed.KeyID)
	if err != nil {
		return protocol.SigningKeyID{}, fmt.Errorf("%w: %v", ErrMalformedResponse, err)
	}
	return keyID, nil
}

func (c *Client) SignCommittedDigest(ctx context.Context, digest protocol.Digest32) ([]byte, protocol.SigningKeyID, error) {
	body, err := json.Marshal(signRequest{DigestHex: hex.EncodeToString(digest.Bytes())})
	if err != nil {
		return nil, protocol.SigningKeyID{}, fmt.Errorf("signerrpc: encode request: %w", err)
	}
	resp, err := c.do(ctx, http.MethodPost, "/v1/sign", body)
	if err != nil {
		return nil, protocol.SigningKeyID{}, fmt.Errorf("%w: %v", ErrRemoteSigner, err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, protocol.SigningKeyID{}, fmt.Errorf("%w: read response: %v", ErrRemoteSigner, err)
	}
	if resp.StatusCode != http.StatusOK {
		return nil, protocol.SigningKeyID{}, fmt.Errorf("%w: status %d: %s", ErrRemoteSigner, resp.StatusCode, decodeErrorMessage(data))
	}
	var parsed signResponse
	if err := json.Unmarshal(data, &parsed); err != nil {
		return nil, protocol.SigningKeyID{}, fmt.Errorf("%w: %v", ErrMalformedResponse, err)
	}
	signature, err := hex.DecodeString(parsed.SignatureHex)
	if err != nil {
		return nil, protocol.SigningKeyID{}, fmt.Errorf("%w: signature not valid hex: %v", ErrMalformedResponse, err)
	}
	keyID, err := protocol.NewSigningKeyID(parsed.KeyID)
	if err != nil {
		return nil, protocol.SigningKeyID{}, fmt.Errorf("%w: %v", ErrMalformedResponse, err)
	}
	return signature, keyID, nil
}

func decodeErrorMessage(data []byte) string {
	var parsed errorResponse
	if json.Unmarshal(data, &parsed) == nil && parsed.Error != "" {
		return parsed.Error
	}
	return string(data)
}

var _ Signer = (*Client)(nil)
