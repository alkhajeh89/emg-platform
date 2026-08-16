package iam

import "testing"

func TestLoadSucceeds(t *testing.T) {
	manifest, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if manifest.Version != 1 {
		t.Fatalf("version = %d, want 1", manifest.Version)
	}
	if len(manifest.Principals) == 0 {
		t.Fatal("expected at least one principal")
	}
}

func TestAllSixPhase1PrincipalsPresent(t *testing.T) {
	manifest, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	want := []string{
		"recovery-authority-runtime",    // A
		"recovery-signing",              // B
		"recovery-pin-capture",          // C
		"compromise-ledger-writer",      // D
		"recovery-verification-read",    // E
		"recovery-bootstrap-deployment", // F (boundary only)
	}
	for _, id := range want {
		if _, found := manifest.Get(id); !found {
			t.Errorf("expected principal %q to be present", id)
		}
	}
}

func TestNoDuplicatePrincipalIDs(t *testing.T) {
	manifest, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]bool{}
	for _, p := range manifest.Principals {
		if seen[p.ID] {
			t.Errorf("duplicate principal id %q", p.ID)
		}
		seen[p.ID] = true
	}
}

func TestNoResourceScopeContainsLiteralIdentifier(t *testing.T) {
	manifest, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range manifest.Principals {
		for _, scope := range p.ResourceScope {
			if !placeholderSegment.MatchString(scope.Pattern) {
				t.Errorf("principal %s resource_scope pattern %q contains no {placeholder} segment", p.ID, scope.Pattern)
			}
		}
	}
}

func TestNoPermissionIsBothRequiredAndForbiddenForSamePrincipal(t *testing.T) {
	manifest, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range manifest.Principals {
		forbidden := map[string]bool{}
		for _, f := range p.ForbiddenPermissions {
			forbidden[f] = true
		}
		for _, r := range p.RequiredPermissions {
			if forbidden[r] {
				t.Errorf("principal %s: permission %q is both required and forbidden", p.ID, r)
			}
		}
	}
}

// TestValidateRejectsPermissionOverlap proves Validate() itself (not just
// this test file's own re-derivation above) catches the invariant --
// exercised against a deliberately corrupted in-memory manifest, not the
// committed file.
func TestValidateRejectsPermissionOverlap(t *testing.T) {
	bad := Manifest{Version: 1, Principals: []Principal{{
		ID: "x", Purpose: "p", Domain: "signing", Kind: "runtime",
		CredentialModel: "c", RotationResponsibility: "r", ImplementationStatus: "grounded_in_landed_code",
		RequiredPermissions:  []string{"cloudkms.cryptoKeyVersions.useToSign"},
		ForbiddenPermissions: []string{"cloudkms.cryptoKeyVersions.useToSign"},
	}}}
	if err := bad.Validate(); err == nil {
		t.Fatal("expected Validate to reject a permission that is both required and forbidden")
	}
}

func TestValidateRejectsDuplicateID(t *testing.T) {
	bad := Manifest{Version: 1, Principals: []Principal{
		{ID: "x", Purpose: "p", Domain: "signing", Kind: "runtime", CredentialModel: "c", RotationResponsibility: "r", ImplementationStatus: "grounded_in_landed_code"},
		{ID: "x", Purpose: "p2", Domain: "signing", Kind: "runtime", CredentialModel: "c", RotationResponsibility: "r", ImplementationStatus: "grounded_in_landed_code"},
	}}
	if err := bad.Validate(); err == nil {
		t.Fatal("expected Validate to reject a duplicate principal id")
	}
}

func TestValidateRejectsLiteralResourceIdentifier(t *testing.T) {
	bad := Manifest{Version: 1, Principals: []Principal{{
		ID: "x", Purpose: "p", Domain: "signing", Kind: "runtime",
		CredentialModel: "c", RotationResponsibility: "r", ImplementationStatus: "grounded_in_landed_code",
		ResourceScope: []ResourceScope{{ResourceType: "kms_crypto_key", Pattern: "projects/my-real-prod-project/locations/us/keyRings/prod/cryptoKeys/k"}},
	}}}
	if err := bad.Validate(); err == nil {
		t.Fatal("expected Validate to reject a resource_scope pattern with no {placeholder} segment")
	}
}

func TestValidateRejectsInvalidDomainKindStatus(t *testing.T) {
	base := Principal{ID: "x", Purpose: "p", CredentialModel: "c", RotationResponsibility: "r"}
	cases := []Principal{
		func() Principal {
			p := base
			p.Domain = "not-a-real-domain"
			p.Kind = "runtime"
			p.ImplementationStatus = "grounded_in_landed_code"
			return p
		}(),
		func() Principal {
			p := base
			p.Domain = "signing"
			p.Kind = "not-a-real-kind"
			p.ImplementationStatus = "grounded_in_landed_code"
			return p
		}(),
		func() Principal {
			p := base
			p.Domain = "signing"
			p.Kind = "runtime"
			p.ImplementationStatus = "not-a-real-status"
			return p
		}(),
	}
	for i, p := range cases {
		bad := Manifest{Version: 1, Principals: []Principal{p}}
		if err := bad.Validate(); err == nil {
			t.Errorf("case %d: expected Validate to reject invalid enum value", i)
		}
	}
}
