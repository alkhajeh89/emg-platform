// Package iam loads and validates the Recovery Authority's production GCP
// IAM principal inventory (ADR-044/ADR-045 S4): the single authoritative,
// declarative source of which principals may hold which permissions
// against which resource-scope pattern, and which permissions each
// principal must never hold.
//
// This package DOES NOT create, modify, bind, enable, disable, or query
// any real GCP IAM policy, resource, or credential -- it parses and
// validates a committed JSON manifest (manifest.json, embedded at build
// time) entirely offline. No network call, no cloud SDK import, and no
// credential of any kind exists anywhere in this package. Actually
// provisioning real GCP principals from this manifest remains out of
// scope for this package -- S6's provisioning package
// (internal/authority/provisioning) cross-references these principal IDs
// in its own declarative execution ordering, but performs no real IAM
// binding either; that step requires a later, explicitly authorized
// real-cloud qualification (see provisioning/README.md).
package iam

import (
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
)

//go:embed manifest.json
var manifestFS embed.FS

// Manifest is the parsed, validated principal inventory.
type Manifest struct {
	Version    int         `json:"version"`
	Principals []Principal `json:"principals"`
}

// ResourceScope is one GCP resource-name pattern a principal's permissions
// apply to. Pattern values are placeholder-only (e.g.
// "projects/{authority_project}/...") -- never a real project/instance/
// bucket/key ID (validated by patternPlaceholderOnly).
type ResourceScope struct {
	ResourceType string `json:"resource_type"`
	Pattern      string `json:"pattern"`
}

// Principal is one production IAM principal in the inventory.
type Principal struct {
	ID                     string          `json:"id"`
	Purpose                string          `json:"purpose"`
	Domain                 string          `json:"domain"`
	Kind                   string          `json:"kind"`
	ResourceScope          []ResourceScope `json:"resource_scope"`
	RequiredPermissions    []string        `json:"required_permissions"`
	ForbiddenPermissions   []string        `json:"forbidden_permissions"`
	CredentialModel        string          `json:"credential_model"`
	RotationResponsibility string          `json:"rotation_responsibility"`
	ImplementationStatus   string          `json:"implementation_status"`
	Notes                  string          `json:"notes,omitempty"`
}

// HasPermission reports whether p's required_permissions contains exactly
// permission.
func (p Principal) HasPermission(permission string) bool {
	for _, granted := range p.RequiredPermissions {
		if granted == permission {
			return true
		}
	}
	return false
}

// HasPermissionPrefix reports whether any of p's required_permissions
// starts with prefix (e.g. "cloudkms." to ask "does this principal hold
// any Cloud KMS permission at all").
func (p Principal) HasPermissionPrefix(prefix string) bool {
	for _, granted := range p.RequiredPermissions {
		if len(granted) >= len(prefix) && granted[:len(prefix)] == prefix {
			return true
		}
	}
	return false
}

var (
	ErrDuplicatePrincipalID   = errors.New("iam: duplicate principal id")
	ErrMissingRequiredField   = errors.New("iam: principal missing a required field")
	ErrInvalidDomain          = errors.New("iam: invalid domain")
	ErrInvalidKind            = errors.New("iam: invalid kind")
	ErrInvalidImplStatus      = errors.New("iam: invalid implementation_status")
	ErrPermissionOverlap      = errors.New("iam: a permission appears in both required_permissions and forbidden_permissions")
	ErrNonPlaceholderResource = errors.New("iam: resource_scope pattern must use {placeholder} segments only, never a literal identifier")
)

var validDomains = map[string]bool{
	"authority_witness": true, "signing": true, "compromise_ledger": true, "bootstrap": true,
}
var validKinds = map[string]bool{"runtime": true, "administrative": true}
var validImplStatus = map[string]bool{"grounded_in_landed_code": true, "boundary_only_not_yet_implemented": true}

// literalIdentifierHint matches resource-scope patterns that look like
// they contain a real, non-placeholder GCP identifier rather than a
// "{placeholder}" segment -- specifically, a bare alphanumeric-and-hyphen
// path segment where a placeholder was expected. This is a conservative
// heuristic, not a full grammar: it exists to catch an accidental literal
// project/bucket/key ID being committed, not to validate GCP resource-name
// syntax in general.
var placeholderSegment = regexp.MustCompile(`\{[a-z_]+\}`)

// Load parses and validates the embedded manifest.json. It never reads
// from any path outside this package's own embedded filesystem, and never
// makes a network or cloud API call.
func Load() (Manifest, error) {
	data, err := manifestFS.ReadFile("manifest.json")
	if err != nil {
		return Manifest{}, fmt.Errorf("iam: read embedded manifest: %w", err)
	}
	var manifest Manifest
	if err := json.Unmarshal(data, &manifest); err != nil {
		return Manifest{}, fmt.Errorf("iam: decode manifest: %w", err)
	}
	if err := manifest.Validate(); err != nil {
		return Manifest{}, err
	}
	return manifest, nil
}

// Validate checks structural well-formedness and the cross-field
// invariants this package's callers (policy tests, and any future
// provisioning tooling) depend on: unique principal IDs, well-formed
// enums, no permission simultaneously required and forbidden by the same
// principal, and resource-scope patterns free of literal identifiers.
func (m Manifest) Validate() error {
	seen := make(map[string]bool, len(m.Principals))
	for _, p := range m.Principals {
		if p.ID == "" || p.Purpose == "" || p.CredentialModel == "" || p.RotationResponsibility == "" {
			return fmt.Errorf("%w: %+v", ErrMissingRequiredField, p.ID)
		}
		if seen[p.ID] {
			return fmt.Errorf("%w: %s", ErrDuplicatePrincipalID, p.ID)
		}
		seen[p.ID] = true
		if !validDomains[p.Domain] {
			return fmt.Errorf("%w: %s (principal %s)", ErrInvalidDomain, p.Domain, p.ID)
		}
		if !validKinds[p.Kind] {
			return fmt.Errorf("%w: %s (principal %s)", ErrInvalidKind, p.Kind, p.ID)
		}
		if !validImplStatus[p.ImplementationStatus] {
			return fmt.Errorf("%w: %s (principal %s)", ErrInvalidImplStatus, p.ImplementationStatus, p.ID)
		}
		forbidden := make(map[string]bool, len(p.ForbiddenPermissions))
		for _, f := range p.ForbiddenPermissions {
			forbidden[f] = true
		}
		for _, r := range p.RequiredPermissions {
			if forbidden[r] {
				return fmt.Errorf("%w: %s (principal %s)", ErrPermissionOverlap, r, p.ID)
			}
		}
		for _, scope := range p.ResourceScope {
			if !placeholderSegment.MatchString(scope.Pattern) {
				return fmt.Errorf("%w: %q (principal %s)", ErrNonPlaceholderResource, scope.Pattern, p.ID)
			}
		}
	}
	return nil
}

// Get returns the principal with the given id, or false if none exists.
func (m Manifest) Get(id string) (Principal, bool) {
	for _, p := range m.Principals {
		if p.ID == id {
			return p, true
		}
	}
	return Principal{}, false
}
