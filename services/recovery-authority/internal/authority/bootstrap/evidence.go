package bootstrap

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// ErrEvidenceAlreadyExists means an evidence record already exists for this
// exact AuthorityEpoch. Since AuthorityEpoch is freshly minted per genesis
// attempt (GenerateFreshIdentifiers), this can only happen on a retry of
// the very same attempt -- callers on that path (see ExecuteGenesis) treat
// it as informational, never as silent overwrite: the original evidence
// file is left untouched either way.
var ErrEvidenceAlreadyExists = errors.New("bootstrap: evidence already recorded for this authority epoch")

// Evidence is the durable, non-secret audit record S6 Phase 10 requires for
// every genesis attempt, successful or not. It never includes credentials,
// tokens, private key material, service-account keys, bearer headers, or
// any other secret configuration value -- every field here is either a
// public resource identifier, a protocol identifier, a digest, an approver
// identity, or a timestamp.
type Evidence struct {
	EnvironmentID            string             `json:"environment_id"`
	ResourceIncarnation      string             `json:"resource_incarnation"`
	AuthorityEpoch           string             `json:"authority_epoch"`
	OperationID              string             `json:"operation_id"`
	SpannerDatabase          string             `json:"spanner_database"`
	SigningKeyID             string             `json:"signing_key_id"`
	ApprovedSigningCryptoKey string             `json:"approved_signing_crypto_key"`
	WitnessKey               string             `json:"witness_key"`
	Approvals                []approvalEvidence `json:"approvals"`
	StartedAt                time.Time          `json:"started_at"`
	CompletedAt              time.Time          `json:"completed_at"`
	Outcome                  string             `json:"outcome"`
	CommitClassification     string             `json:"commit_classification,omitempty"`
	WitnessCreateOutcome     string             `json:"witness_create_outcome,omitempty"`
	FinalEpochState          string             `json:"final_epoch_state"`
	StateDigestHex           string             `json:"state_digest_hex,omitempty"`
	FailureReason            string             `json:"failure_reason,omitempty"`
	EvidenceDigestSHA256     string             `json:"evidence_digest_sha256"`
}

func evidenceFor(req GenesisRequest, startedAt, completedAt time.Time, outcome string) Evidence {
	return Evidence{
		EnvironmentID:            req.EnvironmentID.String(),
		ResourceIncarnation:      req.ResourceIncarnation.String(),
		AuthorityEpoch:           req.AuthorityEpoch.String(),
		OperationID:              req.OperationID.String(),
		SpannerDatabase:          req.SpannerDatabase,
		SigningKeyID:             req.SigningKeyID.String(),
		ApprovedSigningCryptoKey: req.ApprovedSigningCryptoKey,
		WitnessKey:               req.WitnessKey(),
		Approvals:                approvalEvidenceFor(req.Approvals),
		StartedAt:                startedAt.UTC(),
		CompletedAt:              completedAt.UTC(),
		Outcome:                  outcome,
	}
}

// finalize computes the evidence's own tamper-evidence digest over every
// other field, using a stable, explicit field order (never Go's map
// iteration, which is randomized) so the digest is reproducible.
func (e Evidence) finalize() Evidence {
	e.EvidenceDigestSHA256 = ""
	canonical := fmt.Sprintf(
		"%s|%s|%s|%s|%s|%s|%s|%s|%v|%s|%s|%s|%s|%s|%s|%s|%s",
		e.EnvironmentID, e.ResourceIncarnation, e.AuthorityEpoch, e.OperationID,
		e.SpannerDatabase, e.SigningKeyID, e.ApprovedSigningCryptoKey, e.WitnessKey,
		e.Approvals, e.StartedAt.Format(time.RFC3339Nano), e.CompletedAt.Format(time.RFC3339Nano),
		e.Outcome, e.CommitClassification, e.WitnessCreateOutcome, e.FinalEpochState,
		e.StateDigestHex, e.FailureReason,
	)
	sum := sha256.Sum256([]byte(canonical))
	e.EvidenceDigestSHA256 = base64.StdEncoding.EncodeToString(sum[:])
	return e
}

// WriteEvidence durably persists evidence as an indented JSON file named
// after the genesis attempt's AuthorityEpoch, using the same write-once
// (O_CREATE|O_EXCL) filesystem discipline keypinning.FileStore and
// compromiseledger.FileLedger already use elsewhere in this codebase: an
// evidence record, once written, is never silently overwritten by a second
// call for the same epoch.
func WriteEvidence(dir string, evidence Evidence) error {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("bootstrap: create evidence directory: %w", err)
	}
	finalized := evidence.finalize()
	data, err := json.MarshalIndent(finalized, "", "  ")
	if err != nil {
		return fmt.Errorf("bootstrap: encode evidence: %w", err)
	}
	path := filepath.Join(dir, finalized.AuthorityEpoch+".json")
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o400)
	if err != nil {
		if errors.Is(err, os.ErrExist) {
			return ErrEvidenceAlreadyExists
		}
		return fmt.Errorf("bootstrap: create evidence file: %w", err)
	}
	defer file.Close()
	if _, err := file.Write(data); err != nil {
		return fmt.Errorf("bootstrap: write evidence file: %w", err)
	}
	return file.Sync()
}
