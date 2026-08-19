package provisioning

import (
	"strings"
	"testing"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/iam"
)

func TestLoadSucceeds(t *testing.T) {
	t.Parallel()
	if _, err := Load(); err != nil {
		t.Fatal(err)
	}
}

func TestExecutionOrderIsAcyclicAndFullyResolved(t *testing.T) {
	t.Parallel()
	contract := mustLoad(t)
	ordered, err := contract.OrderedSteps()
	if err != nil {
		t.Fatal(err)
	}
	if len(ordered) != len(contract.ExecutionOrder) {
		t.Fatalf("OrderedSteps returned %d steps, want %d", len(ordered), len(contract.ExecutionOrder))
	}
	seenBefore := make(map[string]bool)
	for _, step := range ordered {
		for _, dep := range step.DependsOn {
			if !seenBefore[dep] {
				t.Fatalf("step %s ordered before its dependency %s", step.ID, dep)
			}
		}
		seenBefore[step.ID] = true
	}
}

// TestExecuteGenesisTransitivelyRequiresPinStoreAndLedgerProvisioning is the
// direct Phase 6 regression test (P1 remediation, this task): genesis
// cannot proceed unless the pin-store and compromise-ledger durable
// providers exist and their administrative owners are established --
// proven here as a real, transitive dependency-graph property, not merely
// an assertion in prose.
func TestExecuteGenesisTransitivelyRequiresPinStoreAndLedgerProvisioning(t *testing.T) {
	t.Parallel()
	contract := mustLoad(t)
	ordered, err := contract.OrderedSteps()
	if err != nil {
		t.Fatal(err)
	}
	index := make(map[string]int, len(ordered))
	for i, step := range ordered {
		index[step.ID] = i
	}
	genesisIdx, ok := index["execute-genesis"]
	if !ok {
		t.Fatal("execute-genesis step not found")
	}
	for _, prerequisite := range []string{
		"provision-pin-store-bucket",
		"provision-compromise-ledger-bucket",
		"bind-pin-capture-principal",
		"bind-ledger-writer-principal",
		"capture-and-pin-signing-key",
	} {
		idx, ok := index[prerequisite]
		if !ok {
			t.Fatalf("prerequisite step %s not found", prerequisite)
		}
		if idx >= genesisIdx {
			t.Fatalf("execute-genesis must be transitively ordered after %s", prerequisite)
		}
	}
}

// TestPinStoreAndLedgerBucketsAreDistinctThreeWayIsolated proves the three
// GCS-backed resource_requirements (witness, pin-store, compromise-ledger)
// all live under distinct project placeholders -- the same three-domain
// isolation iam/manifest.json's own TestAttackCD proves at the IAM layer,
// re-proven here at the provisioning-contract layer so the two documents
// cannot silently drift apart.
func TestPinStoreAndLedgerBucketsAreDistinctThreeWayIsolated(t *testing.T) {
	t.Parallel()
	contract := mustLoad(t)
	expectedPlaceholder := map[string]string{
		"witness-gcs-bucket":       "{authority_project}",
		"pin-store-bucket":         "{signing_project}",
		"compromise-ledger-bucket": "{compromise_ledger_project}",
	}
	found := make(map[string]bool, 3)
	for _, req := range contract.ResourceRequirements {
		want, ok := expectedPlaceholder[req.ID]
		if !ok {
			continue
		}
		found[req.ID] = true
		if !strings.Contains(req.Pattern, want) {
			t.Errorf("%s pattern %q does not contain expected placeholder %q", req.ID, req.Pattern, want)
		}
		for otherID, otherPlaceholder := range expectedPlaceholder {
			if otherID == req.ID {
				continue
			}
			if strings.Contains(req.Pattern, otherPlaceholder) {
				t.Errorf("%s pattern %q unexpectedly contains %s's placeholder %q", req.ID, req.Pattern, otherID, otherPlaceholder)
			}
		}
	}
	for id := range expectedPlaceholder {
		if !found[id] {
			t.Errorf("resource_requirement %s not found", id)
		}
	}
}

func TestExecuteGenesisStepIsAutomatedAndDependsOnBootstrapBinding(t *testing.T) {
	t.Parallel()
	contract := mustLoad(t)
	step, found := contract.Get("execute-genesis")
	if !found {
		t.Fatal("execute-genesis step not found")
	}
	if !step.Automated {
		t.Fatal("execute-genesis must be automated=true (bootstrap.ExecuteGenesis)")
	}
	if step.Owner != "recovery-bootstrap-deployment" {
		t.Fatalf("execute-genesis owner = %q, want recovery-bootstrap-deployment", step.Owner)
	}
	requiresApprovals := false
	for _, dep := range step.DependsOn {
		if dep == "obtain-dual-control-approvals" {
			requiresApprovals = true
		}
	}
	if !requiresApprovals {
		t.Fatal("execute-genesis must depend on obtain-dual-control-approvals")
	}
}

func TestRevokeBootstrapPrincipalRunsAfterGenesis(t *testing.T) {
	t.Parallel()
	contract := mustLoad(t)
	step, found := contract.Get("revoke-bootstrap-principal")
	if !found {
		t.Fatal("revoke-bootstrap-principal step not found")
	}
	dependsOnGenesis := false
	for _, dep := range step.DependsOn {
		if dep == "execute-genesis" {
			dependsOnGenesis = true
		}
	}
	if !dependsOnGenesis {
		t.Fatal("revoke-bootstrap-principal must depend on execute-genesis -- S6 Phase 2 requires no permanent bootstrap privilege")
	}
}

// TestBootstrapPrincipalBindingIsNeverAStandingGrant is the provisioning
// contract's own record of ATTACK_O (bootstrap privilege persists into
// ordinary runtime) at the design level, complementing
// bootstrap.TestOrdinaryRuntimeBinariesNeverImportBootstrap's code-level
// guarantee.
func TestBootstrapPrincipalBindingIsNeverAStandingGrant(t *testing.T) {
	t.Parallel()
	contract := mustLoad(t)
	for _, binding := range contract.PrincipalBindings {
		if binding.PrincipalID != "recovery-bootstrap-deployment" {
			continue
		}
		if binding.StandingGrant {
			t.Fatal("recovery-bootstrap-deployment must never be a standing_grant binding")
		}
		return
	}
	t.Fatal("recovery-bootstrap-deployment binding not found")
}

// TestPrincipalBindingsCrossReferenceRealIAMPrincipals proves every
// principal_id this contract names actually exists in iam/manifest.json --
// the contract can never drift into referencing a principal the IAM
// design doesn't define.
func TestPrincipalBindingsCrossReferenceRealIAMPrincipals(t *testing.T) {
	t.Parallel()
	contract := mustLoad(t)
	manifest, err := iam.Load()
	if err != nil {
		t.Fatal(err)
	}
	for _, binding := range contract.PrincipalBindings {
		if _, found := manifest.Get(binding.PrincipalID); !found {
			t.Errorf("principal_binding references unknown iam principal %q", binding.PrincipalID)
		}
	}
	for _, d := range contract.DeploymentManifests {
		if _, found := manifest.Get(d.PrincipalID); !found {
			t.Errorf("deployment_manifest %s references unknown iam principal %q", d.WorkloadID, d.PrincipalID)
		}
	}
}

// TestEveryMustExistResourceHasAWhyNotAutomatedManualStep proves the
// contract does not silently assume a prerequisite resource into
// existence: every resource_requirement marked must_exist_before_genesis
// is provisioned by some manual_steps entry with a stated reason.
func TestEveryMustExistResourceHasAWhyNotAutomatedManualStep(t *testing.T) {
	t.Parallel()
	contract := mustLoad(t)
	if len(contract.ManualSteps) == 0 {
		t.Fatal("expected at least one manual step")
	}
	for _, req := range contract.ResourceRequirements {
		if !req.MustExistBeforeGenesis {
			continue
		}
		if req.Description == "" || req.Pattern == "" {
			t.Errorf("resource_requirement %s missing description/pattern", req.ID)
		}
	}
}

func TestValidateRejectsUnknownDependency(t *testing.T) {
	t.Parallel()
	contract := mustLoad(t)
	contract.ExecutionOrder = append(contract.ExecutionOrder, ExecutionStep{
		ID: "broken-step", Description: "x", Automated: true, Owner: "x",
		DependsOn: []string{"does-not-exist"},
	})
	if err := contract.Validate(); err == nil {
		t.Fatal("expected an error for a dependency on an unknown step id")
	}
}

func TestValidateRejectsDependencyCycle(t *testing.T) {
	t.Parallel()
	contract := Contract{
		Version: 1,
		ResourceRequirements: []ResourceRequirement{
			{ID: "r", ResourceType: "gcs_bucket", Domain: "authority_witness", Description: "x", Pattern: "projects/{p}", MustExistBeforeGenesis: true},
		},
		PrincipalBindings: []PrincipalBinding{
			{PrincipalID: "p", KubernetesServiceAccount: "none", GCPServiceAccountPlaceholder: "p@{x}", StandingGrant: true},
		},
		DeploymentManifests: []DeploymentManifest{
			{WorkloadID: "w", KubernetesManifestPath: "x.yaml", PrincipalID: "p"},
		},
		ManualSteps: []ManualStep{
			{ID: "m", Description: "x", WhyNotAutomated: "x"},
		},
		ExecutionOrder: []ExecutionStep{
			{ID: "a", Description: "x", Automated: false, Owner: "x", DependsOn: []string{"b"}, ManualStepRef: "m"},
			{ID: "b", Description: "x", Automated: false, Owner: "x", DependsOn: []string{"a"}, ManualStepRef: "m"},
		},
	}
	if err := contract.Validate(); err == nil {
		t.Fatal("expected an error for a dependency cycle")
	}
}

func TestValidateRejectsAutomatedStepWithManualStepRef(t *testing.T) {
	t.Parallel()
	contract := mustLoad(t)
	contract.ExecutionOrder = append(contract.ExecutionOrder, ExecutionStep{
		ID: "bad-step", Description: "x", Automated: true, Owner: "x",
		ManualStepRef: "apply-authority-schema",
	})
	if err := contract.Validate(); err == nil {
		t.Fatal("expected an error for automated=true carrying a manual_step_ref")
	}
}

func TestValidateRejectsManualStepMissingRef(t *testing.T) {
	t.Parallel()
	contract := mustLoad(t)
	contract.ExecutionOrder = append(contract.ExecutionOrder, ExecutionStep{
		ID: "bad-step", Description: "x", Automated: false, Owner: "x",
	})
	if err := contract.Validate(); err == nil {
		t.Fatal("expected an error for automated=false missing a manual_step_ref")
	}
}

func mustLoad(t *testing.T) Contract {
	t.Helper()
	contract, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	return contract
}
