package signerrpc

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strings"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// Server exposes Signer over HTTPS, authenticating every request via
// IdentityVerifier before ever touching signer. It has exactly two
// routes and no other capability -- it never imports, constructs, or
// forwards to anything Spanner- or GCS-related, so a compromise of this
// process's HTTP surface cannot reach the authority/witness domain
// through this package (ADR-045 §13 Attack 3's containment property).
type Server struct {
	signer   Signer
	verifier IdentityVerifier
	logger   *slog.Logger
}

func NewServer(signer Signer, verifier IdentityVerifier, logger *slog.Logger) (*Server, error) {
	if signer == nil {
		return nil, errors.New("signerrpc: signer is required")
	}
	if verifier == nil {
		return nil, errors.New("signerrpc: verifier is required")
	}
	if logger == nil {
		logger = slog.Default()
	}
	return &Server{signer: signer, verifier: verifier, logger: logger}, nil
}

// Handler returns the http.Handler to mount. It is the caller's
// responsibility to serve it only over TLS in production.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	s.RegisterRoutes(mux)
	return mux
}

// RegisterRoutes mounts this server's two routes onto a caller-supplied
// mux, so a binary serving other routes (e.g. lifecycle health/readiness)
// on the same listener can combine them without path-pattern duplication.
func (s *Server) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /v1/active-key-id", s.handleActiveKeyID)
	mux.HandleFunc("POST /v1/sign", s.handleSign)
}

// authenticate extracts and verifies the bearer token. It never logs the
// token itself -- only the resulting caller identity or the fact of
// failure.
func (s *Server) authenticate(w http.ResponseWriter, r *http.Request) (string, bool) {
	authHeader := r.Header.Get("Authorization")
	const prefix = "Bearer "
	if !strings.HasPrefix(authHeader, prefix) {
		s.writeError(w, http.StatusUnauthorized, ErrMissingBearerToken)
		return "", false
	}
	token := strings.TrimPrefix(authHeader, prefix)
	identity, err := s.verifier.Verify(r.Context(), token)
	if err != nil {
		s.logger.Warn("signerrpc: rejected unauthenticated/unauthorized caller", "error", err)
		s.writeError(w, http.StatusForbidden, ErrCallerNotAuthorized)
		return "", false
	}
	return identity, true
}

func (s *Server) handleActiveKeyID(w http.ResponseWriter, r *http.Request) {
	identity, ok := s.authenticate(w, r)
	if !ok {
		return
	}
	keyID, err := s.signer.ActiveKeyID(r.Context())
	if err != nil {
		s.logger.Error("signerrpc: ActiveKeyID failed", "caller", identity, "error", err)
		s.writeError(w, http.StatusInternalServerError, ErrRemoteSigner)
		return
	}
	s.writeJSON(w, http.StatusOK, activeKeyIDResponse{KeyID: keyID.String()})
}

func (s *Server) handleSign(w http.ResponseWriter, r *http.Request) {
	identity, ok := s.authenticate(w, r)
	if !ok {
		return
	}
	var req signRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.writeError(w, http.StatusBadRequest, errors.New("signerrpc: malformed request body"))
		return
	}
	digestBytes, err := hex.DecodeString(req.DigestHex)
	if err != nil {
		s.writeError(w, http.StatusBadRequest, errors.New("signerrpc: digest_hex is not valid hex"))
		return
	}
	digest, err := protocol.NewDigest32(digestBytes)
	if err != nil {
		s.writeError(w, http.StatusBadRequest, errors.New("signerrpc: digest is not a well-formed 32-byte digest"))
		return
	}
	signature, keyID, err := s.signer.SignCommittedDigest(r.Context(), digest)
	if err != nil {
		s.logger.Error("signerrpc: SignCommittedDigest failed", "caller", identity, "error", err)
		s.writeError(w, http.StatusInternalServerError, ErrRemoteSigner)
		return
	}
	s.writeJSON(w, http.StatusOK, signResponse{
		SignatureHex: hex.EncodeToString(signature),
		KeyID:        keyID.String(),
	})
}

func (s *Server) writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func (s *Server) writeError(w http.ResponseWriter, status int, err error) {
	s.writeJSON(w, status, errorResponse{Error: err.Error()})
}
