// Package provisioning loads and validates the Recovery Authority's
// governed provisioning contract (ADR-044/ADR-045 S6 Phase 8): the single
// authoritative, declarative source of what must exist, be bound, be
// deployed, and be executed -- and in what order -- before a Recovery
// Authority environment's first legitimate genesis
// (bootstrap.ExecuteGenesis) can run.
//
// This package DOES NOT create, apply, bind, or provision any real GCP
// resource, IAM policy, or Kubernetes object -- it parses and validates a
// committed JSON contract (contract.json, embedded at build time) entirely
// offline, exactly like iam.Load already does for the IAM principal
// inventory this contract cross-references. No network call, no cloud SDK
// import, and no credential of any kind exists anywhere in this package.
//
// Why this exists as JSON rather than Terraform/Pulumi/another IaC engine:
// see README.md. In short, S4 already established that no executable GCP
// IaC framework exists anywhere in this repository, and S6 Phase 8's own
// authorization requires STOPPING before introducing one rather than doing
// so as a side effect of building this contract -- so this package follows
// the same JSON-manifest + Go-validator shape iam already established,
// rather than generating or requiring a new tool.
package provisioning

import (
	"embed"
	"encoding/json"
	"errors"
	"fmt"
)

//go:embed contract.json
var contractFS embed.FS

type ResourceRequirement struct {
	ID                     string `json:"id"`
	ResourceType           string `json:"resource_type"`
	Domain                 string `json:"domain"`
	Description            string `json:"description"`
	Pattern                string `json:"pattern"`
	MustExistBeforeGenesis bool   `json:"must_exist_before_genesis"`
	Notes                  string `json:"notes,omitempty"`
}

type PrincipalBinding struct {
	PrincipalID                  string `json:"principal_id"`
	KubernetesServiceAccount     string `json:"kubernetes_service_account"`
	GCPServiceAccountPlaceholder string `json:"gcp_service_account_placeholder"`
	StandingGrant                bool   `json:"standing_grant"`
}

type DeploymentManifest struct {
	WorkloadID             string `json:"workload_id"`
	KubernetesManifestPath string `json:"kubernetes_manifest_path"`
	PrincipalID            string `json:"principal_id"`
}

type ExecutionStep struct {
	ID            string   `json:"id"`
	Description   string   `json:"description"`
	Automated     bool     `json:"automated"`
	Owner         string   `json:"owner"`
	DependsOn     []string `json:"depends_on"`
	ManualStepRef string   `json:"manual_step_ref,omitempty"`
}

type ManualStep struct {
	ID              string `json:"id"`
	Description     string `json:"description"`
	WhyNotAutomated string `json:"why_not_automated"`
}

// Contract is the parsed, validated provisioning contract.
type Contract struct {
	Version              int                   `json:"version"`
	ResourceRequirements []ResourceRequirement `json:"resource_requirements"`
	PrincipalBindings    []PrincipalBinding    `json:"principal_bindings"`
	DeploymentManifests  []DeploymentManifest  `json:"deployment_manifests"`
	ExecutionOrder       []ExecutionStep       `json:"execution_order"`
	ManualSteps          []ManualStep          `json:"manual_steps"`
}

var (
	ErrDuplicateID               = errors.New("provisioning: duplicate id")
	ErrMissingRequiredField      = errors.New("provisioning: missing required field")
	ErrUnknownDependency         = errors.New("provisioning: execution_step depends_on references an unknown step id")
	ErrUnknownManualStepRef      = errors.New("provisioning: execution_step manual_step_ref references an unknown manual_steps id")
	ErrAutomatedStepHasManualRef = errors.New("provisioning: an automated=true execution_step must not carry a manual_step_ref")
	ErrManualStepMissingRef      = errors.New("provisioning: an automated=false execution_step must carry a manual_step_ref")
	ErrCyclicDependency          = errors.New("provisioning: execution_order contains a dependency cycle")
)

// Load parses and validates the embedded contract.json. It never reads
// from any path outside this package's own embedded filesystem, and never
// makes a network or cloud API call.
func Load() (Contract, error) {
	data, err := contractFS.ReadFile("contract.json")
	if err != nil {
		return Contract{}, fmt.Errorf("provisioning: read embedded contract: %w", err)
	}
	var contract Contract
	if err := json.Unmarshal(data, &contract); err != nil {
		return Contract{}, fmt.Errorf("provisioning: decode contract: %w", err)
	}
	if err := contract.Validate(); err != nil {
		return Contract{}, err
	}
	return contract, nil
}

// Validate checks structural well-formedness and the cross-field
// invariants this package's callers depend on: unique IDs within each
// section, every depends_on/manual_step_ref pointing at something that
// actually exists, automated/manual_step_ref consistency, and an
// acyclic execution order.
func (c Contract) Validate() error {
	requirementIDs := make(map[string]bool, len(c.ResourceRequirements))
	for _, r := range c.ResourceRequirements {
		if r.ID == "" || r.Description == "" || r.Pattern == "" {
			return fmt.Errorf("%w: resource_requirement %q", ErrMissingRequiredField, r.ID)
		}
		if requirementIDs[r.ID] {
			return fmt.Errorf("%w: resource_requirement %s", ErrDuplicateID, r.ID)
		}
		requirementIDs[r.ID] = true
	}

	bindingIDs := make(map[string]bool, len(c.PrincipalBindings))
	for _, b := range c.PrincipalBindings {
		if b.PrincipalID == "" || b.GCPServiceAccountPlaceholder == "" {
			return fmt.Errorf("%w: principal_binding %q", ErrMissingRequiredField, b.PrincipalID)
		}
		if bindingIDs[b.PrincipalID] {
			return fmt.Errorf("%w: principal_binding %s", ErrDuplicateID, b.PrincipalID)
		}
		bindingIDs[b.PrincipalID] = true
	}

	for _, d := range c.DeploymentManifests {
		if d.WorkloadID == "" || d.KubernetesManifestPath == "" || d.PrincipalID == "" {
			return fmt.Errorf("%w: deployment_manifest %q", ErrMissingRequiredField, d.WorkloadID)
		}
	}

	manualStepIDs := make(map[string]bool, len(c.ManualSteps))
	for _, m := range c.ManualSteps {
		if m.ID == "" || m.Description == "" || m.WhyNotAutomated == "" {
			return fmt.Errorf("%w: manual_step %q", ErrMissingRequiredField, m.ID)
		}
		if manualStepIDs[m.ID] {
			return fmt.Errorf("%w: manual_step %s", ErrDuplicateID, m.ID)
		}
		manualStepIDs[m.ID] = true
	}

	stepIDs := make(map[string]bool, len(c.ExecutionOrder))
	for _, s := range c.ExecutionOrder {
		if s.ID == "" || s.Description == "" || s.Owner == "" {
			return fmt.Errorf("%w: execution_step %q", ErrMissingRequiredField, s.ID)
		}
		if stepIDs[s.ID] {
			return fmt.Errorf("%w: execution_step %s", ErrDuplicateID, s.ID)
		}
		stepIDs[s.ID] = true
		if s.Automated && s.ManualStepRef != "" {
			return fmt.Errorf("%w: %s", ErrAutomatedStepHasManualRef, s.ID)
		}
		if !s.Automated {
			if s.ManualStepRef == "" {
				return fmt.Errorf("%w: %s", ErrManualStepMissingRef, s.ID)
			}
			if !manualStepIDs[s.ManualStepRef] {
				return fmt.Errorf("%w: %s -> %s", ErrUnknownManualStepRef, s.ID, s.ManualStepRef)
			}
		}
	}
	for _, s := range c.ExecutionOrder {
		for _, dep := range s.DependsOn {
			if !stepIDs[dep] {
				return fmt.Errorf("%w: %s -> %s", ErrUnknownDependency, s.ID, dep)
			}
		}
	}
	if err := detectCycle(c.ExecutionOrder); err != nil {
		return err
	}
	return nil
}

// detectCycle performs a straightforward DFS cycle check over
// execution_order's depends_on graph.
func detectCycle(steps []ExecutionStep) error {
	deps := make(map[string][]string, len(steps))
	for _, s := range steps {
		deps[s.ID] = s.DependsOn
	}
	const (
		unvisited = 0
		visiting  = 1
		done      = 2
	)
	state := make(map[string]int, len(steps))
	var visit func(id string) error
	visit = func(id string) error {
		switch state[id] {
		case visiting:
			return fmt.Errorf("%w: at %s", ErrCyclicDependency, id)
		case done:
			return nil
		}
		state[id] = visiting
		for _, dep := range deps[id] {
			if err := visit(dep); err != nil {
				return err
			}
		}
		state[id] = done
		return nil
	}
	for _, s := range steps {
		if err := visit(s.ID); err != nil {
			return err
		}
	}
	return nil
}

// Get returns the execution step with the given id, or false if none
// exists.
func (c Contract) Get(id string) (ExecutionStep, bool) {
	for _, s := range c.ExecutionOrder {
		if s.ID == id {
			return s, true
		}
	}
	return ExecutionStep{}, false
}

// OrderedSteps returns execution_order in a valid topological order
// (every step after everything in its depends_on), computed fresh from
// depends_on rather than trusting the JSON's own array order to already
// be correct.
func (c Contract) OrderedSteps() ([]ExecutionStep, error) {
	if err := detectCycle(c.ExecutionOrder); err != nil {
		return nil, err
	}
	byID := make(map[string]ExecutionStep, len(c.ExecutionOrder))
	for _, s := range c.ExecutionOrder {
		byID[s.ID] = s
	}
	var ordered []ExecutionStep
	visited := make(map[string]bool, len(c.ExecutionOrder))
	var visit func(id string)
	visit = func(id string) {
		if visited[id] {
			return
		}
		visited[id] = true
		for _, dep := range byID[id].DependsOn {
			visit(dep)
		}
		ordered = append(ordered, byID[id])
	}
	for _, s := range c.ExecutionOrder {
		visit(s.ID)
	}
	return ordered, nil
}
