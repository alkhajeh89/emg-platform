package bootstrap

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestWriteEvidenceProducesReadableNonSecretRecord(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	req := fx.request(t)
	dir := t.TempDir()

	evidence := evidenceFor(req, fx.now, fx.now.Add(time.Second), OutcomeCompleted.String())
	if err := WriteEvidence(dir, evidence); err != nil {
		t.Fatal(err)
	}

	path := filepath.Join(dir, req.AuthorityEpoch.String()+".json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	raw := string(data)
	for _, secretMarker := range []string{"private", "PRIVATE KEY", "token", "bearer", "credential", "Authorization"} {
		if strings.Contains(strings.ToLower(raw), strings.ToLower(secretMarker)) {
			t.Fatalf("evidence file contains a secret-looking marker %q:\n%s", secretMarker, raw)
		}
	}

	var decoded Evidence
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded.EnvironmentID != req.EnvironmentID.String() {
		t.Fatalf("environment id = %q", decoded.EnvironmentID)
	}
	if decoded.EvidenceDigestSHA256 == "" {
		t.Fatal("expected a non-empty evidence digest")
	}
}

func TestWriteEvidenceNeverOverwritesAnExistingRecord(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	req := fx.request(t)
	dir := t.TempDir()

	first := evidenceFor(req, fx.now, fx.now.Add(time.Second), OutcomeCompleted.String())
	if err := WriteEvidence(dir, first); err != nil {
		t.Fatal(err)
	}
	second := evidenceFor(req, fx.now, fx.now.Add(2*time.Second), OutcomeUnresolved.String())
	err := WriteEvidence(dir, second)
	if !errors.Is(err, ErrEvidenceAlreadyExists) {
		t.Fatalf("err = %v, want ErrEvidenceAlreadyExists", err)
	}

	path := filepath.Join(dir, req.AuthorityEpoch.String()+".json")
	data, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatal(readErr)
	}
	var decoded Evidence
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded.Outcome != OutcomeCompleted.String() {
		t.Fatalf("stored outcome = %q, want the FIRST write's outcome (COMPLETED), proving no overwrite occurred", decoded.Outcome)
	}
}

func TestEvidenceDigestChangesWithContent(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	req := fx.request(t)
	base := evidenceFor(req, fx.now, fx.now.Add(time.Second), OutcomeCompleted.String())
	baseDigest := base.finalize().EvidenceDigestSHA256

	mutated := base
	mutated.FailureReason = "something changed"
	mutatedDigest := mutated.finalize().EvidenceDigestSHA256

	if baseDigest == mutatedDigest {
		t.Fatal("evidence digest did not change when content changed")
	}
}
