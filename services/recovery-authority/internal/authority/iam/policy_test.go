// This file proves S4's Phase 5 policy properties (1-15) and Phase 6
// attack matrix (A-J; K/L are NOT modeled here -- see the package README
// for why those two specifically cannot be proven by a repository-level
// manifest alone) against the committed manifest.json.
package iam

import (
	"strings"
	"testing"
)

func mustLoad(t *testing.T) Manifest {
	t.Helper()
	manifest, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	return manifest
}

func principal(t *testing.T, manifest Manifest, id string) Principal {
	t.Helper()
	p, found := manifest.Get(id)
	if !found {
		t.Fatalf("principal %q not found", id)
	}
	return p
}

// -- Phase 5, property 1 --------------------------------------------------

func TestPolicy01_SigningPrincipalCanSignButNotAdministerKeys(t *testing.T) {
	p := principal(t, mustLoad(t), "recovery-signing")
	if !p.HasPermission("cloudkms.cryptoKeyVersions.useToSign") {
		t.Fatal("recovery-signing must be able to sign")
	}
	forbidden := []string{
		"cloudkms.cryptoKeys.create", "cloudkms.cryptoKeys.update", "cloudkms.cryptoKeys.setIamPolicy",
		"cloudkms.cryptoKeyVersions.create", "cloudkms.cryptoKeyVersions.update",
		"cloudkms.cryptoKeyVersions.destroy", "cloudkms.cryptoKeyVersions.restore",
		"cloudkms.keyRings.create", "cloudkms.keyRings.setIamPolicy",
	}
	for _, perm := range forbidden {
		if p.HasPermission(perm) {
			t.Errorf("recovery-signing must not hold key-administration permission %q", perm)
		}
	}
}

// -- Phase 5, property 2 & Attack A ---------------------------------------

func TestPolicy02_AttackA_SigningPrincipalCannotMutateSpanner(t *testing.T) {
	p := principal(t, mustLoad(t), "recovery-signing")
	if p.HasPermissionPrefix("spanner.") {
		t.Fatalf("recovery-signing must hold zero Spanner permissions, has: %v", p.RequiredPermissions)
	}
}

// -- Phase 5, property 3 --------------------------------------------------

func TestPolicy03_SigningPrincipalCannotAdministerWitnessStorage(t *testing.T) {
	p := principal(t, mustLoad(t), "recovery-signing")
	if p.HasPermissionPrefix("storage.") {
		t.Fatalf("recovery-signing must hold zero GCS permissions, has: %v", p.RequiredPermissions)
	}
}

// -- Phase 5, property 4 & Attack B ---------------------------------------

func TestPolicy04_AttackB_MutationPrincipalCannotSign(t *testing.T) {
	p := principal(t, mustLoad(t), "recovery-authority-runtime")
	if p.HasPermissionPrefix("cloudkms.") {
		t.Fatalf("recovery-authority-runtime must hold zero Cloud KMS permissions, has: %v", p.RequiredPermissions)
	}
}

// -- Phase 5, property 5 --------------------------------------------------

func TestPolicy05_MutationPrincipalCannotAdministerKMS(t *testing.T) {
	// Subsumed by policy 4 (zero KMS permissions at all implies no KMS
	// admin permission specifically), restated as its own named case.
	p := principal(t, mustLoad(t), "recovery-authority-runtime")
	adminPerms := []string{
		"cloudkms.cryptoKeys.create", "cloudkms.cryptoKeyVersions.create",
		"cloudkms.cryptoKeyVersions.destroy", "cloudkms.keyRings.create",
	}
	for _, perm := range adminPerms {
		if p.HasPermission(perm) {
			t.Errorf("recovery-authority-runtime must not hold %q", perm)
		}
	}
}

// -- Phase 5, property 6 & Attack E ---------------------------------------

func TestPolicy06_AttackE_PinCaptureCanReadPublicKeyButNotSign(t *testing.T) {
	p := principal(t, mustLoad(t), "recovery-pin-capture")
	if !p.HasPermission("cloudkms.cryptoKeyVersions.viewPublicKey") {
		t.Fatal("recovery-pin-capture must hold viewPublicKey")
	}
	if !p.HasPermission("cloudkms.cryptoKeyVersions.get") {
		t.Fatal("recovery-pin-capture must hold cryptoKeyVersions.get (to check ENABLED state)")
	}
	if p.HasPermission("cloudkms.cryptoKeyVersions.useToSign") {
		t.Fatal("recovery-pin-capture must NOT hold useToSign")
	}
}

// -- Phase 5, property 7 & Attack F ---------------------------------------

func TestPolicy07_AttackF_PinCaptureAndSignerCannotAdministerKMS(t *testing.T) {
	manifest := mustLoad(t)
	adminPerms := []string{
		"cloudkms.cryptoKeyVersions.create", "cloudkms.cryptoKeyVersions.update",
		"cloudkms.cryptoKeyVersions.destroy", "cloudkms.cryptoKeyVersions.restore",
		"cloudkms.cryptoKeys.create", "cloudkms.cryptoKeys.update",
		"cloudkms.cryptoKeys.setIamPolicy", "cloudkms.keyRings.create", "cloudkms.keyRings.setIamPolicy",
	}
	for _, id := range []string{"recovery-pin-capture", "recovery-signing"} {
		p := principal(t, manifest, id)
		for _, perm := range adminPerms {
			if p.HasPermission(perm) {
				t.Errorf("%s must not hold KMS admin/disable/destroy/rotate permission %q", id, perm)
			}
		}
	}
	// The signer specifically must not even be able to view/enumerate --
	// that capability belongs only to pin-capture (IAM permission
	// separation Cloud KMS itself supports).
	signer := principal(t, manifest, "recovery-signing")
	if signer.HasPermission("cloudkms.cryptoKeyVersions.viewPublicKey") || signer.HasPermission("cloudkms.cryptoKeyVersions.get") {
		t.Fatal("recovery-signing must not hold public-key-retrieval permissions -- that is pin-capture's separate capability")
	}
}

// -- Phase 5, property 8 & Attack J (partial) ------------------------------

func TestPolicy08_AttackJ_ComplianceLedgerWriterCannotSign(t *testing.T) {
	p := principal(t, mustLoad(t), "compromise-ledger-writer")
	if p.HasPermissionPrefix("cloudkms.") {
		t.Fatalf("compromise-ledger-writer must hold zero Cloud KMS permissions, has: %v", p.RequiredPermissions)
	}
}

// -- Phase 5, property 9 ---------------------------------------------------

func TestPolicy09_ComplianceLedgerWriterCannotMutateSpannerState(t *testing.T) {
	p := principal(t, mustLoad(t), "compromise-ledger-writer")
	if p.HasPermissionPrefix("spanner.") {
		t.Fatalf("compromise-ledger-writer must hold zero Spanner permissions unless specifically justified, has: %v", p.RequiredPermissions)
	}
}

// -- Phase 5, property 10 & Attack I ---------------------------------------

func TestPolicy10_AttackI_NoPrincipalHasSetIamPolicy(t *testing.T) {
	for _, p := range mustLoad(t).Principals {
		for _, perm := range p.RequiredPermissions {
			if strings.HasSuffix(perm, "setIamPolicy") || strings.HasSuffix(perm, "getIamPolicy") {
				t.Errorf("principal %s must not hold IAM-policy permission %q", p.ID, perm)
			}
		}
	}
}

// -- Phase 5, property 11 & Attack H ---------------------------------------

func TestPolicy11_AttackH_NoPrincipalCanCreateServiceAccountKeys(t *testing.T) {
	for _, p := range mustLoad(t).Principals {
		if p.HasPermission("iam.serviceAccountKeys.create") {
			t.Errorf("principal %s must not hold iam.serviceAccountKeys.create", p.ID)
		}
	}
}

// -- Phase 5, property 12 & Attack G ---------------------------------------

func TestPolicy12_AttackG_NoPrincipalCanImpersonateOrMintCredentials(t *testing.T) {
	forbidden := []string{
		"iam.serviceAccounts.getAccessToken",
		"iam.serviceAccounts.actAs",
		"iam.serviceAccounts.signBlob",
		"iam.serviceAccounts.signJwt",
	}
	for _, p := range mustLoad(t).Principals {
		for _, perm := range forbidden {
			if p.HasPermission(perm) {
				t.Errorf("principal %s must not hold impersonation-shaped permission %q", p.ID, perm)
			}
		}
	}
}

// -- Phase 5, property 13 ---------------------------------------------------

func TestPolicy13_NoPrincipalHasProjectFolderOrgAdministration(t *testing.T) {
	for _, p := range mustLoad(t).Principals {
		if p.HasPermissionPrefix("resourcemanager.") {
			t.Errorf("principal %s must hold zero resourcemanager.* permissions, has: %v", p.ID, p.RequiredPermissions)
		}
	}
}

// -- Phase 5, property 14 ---------------------------------------------------

func TestPolicy14_NoManifestFieldContainsStaticCredentialMaterial(t *testing.T) {
	suspicious := []string{"PRIVATE KEY", "BEGIN CERTIFICATE", "-----BEGIN", "AKIA", "ya29."}
	for _, p := range mustLoad(t).Principals {
		fields := []string{p.Purpose, p.CredentialModel, p.RotationResponsibility, p.Notes}
		for _, field := range fields {
			for _, marker := range suspicious {
				if strings.Contains(field, marker) {
					t.Errorf("principal %s has a field containing suspicious credential-shaped marker %q", p.ID, marker)
				}
			}
		}
		if strings.Contains(strings.ToLower(p.CredentialModel), "static") && !strings.Contains(strings.ToLower(p.CredentialModel), "no static") {
			t.Errorf("principal %s credential_model mentions 'static' without explicitly ruling it out: %q", p.ID, p.CredentialModel)
		}
	}
}

// -- Phase 5, property 15 ----------------------------------------------------

func TestPolicy15_NoWildcardOrBroadRoleDefeatsSeparation(t *testing.T) {
	broadMarkers := []string{"*", "roles/owner", "roles/editor", "roles/admin", ".admin", "roles/spanner.databaseAdmin", "roles/cloudkms.admin"}
	for _, p := range mustLoad(t).Principals {
		for _, perm := range p.RequiredPermissions {
			for _, marker := range broadMarkers {
				if perm == marker || strings.Contains(perm, marker) {
					t.Errorf("principal %s required_permissions contains broad/wildcard entry %q", p.ID, perm)
				}
			}
		}
	}
}

// -- Attack C / D: cross-domain resource-scope separation -----------------

// TestAttackCD_CrossDomainResourceScopesUseDistinctProjectPlaceholders
// proves the manifest itself models the signing domain and the
// authority/witness domain as living under DIFFERENT project-placeholder
// namespaces ({signing_project} vs {authority_project}) -- so an
// administrator whose IAM reach is scoped to one domain's resource
// pattern has no resource in the OTHER domain's pattern to bind against,
// as modeled here. This is a structural property of the DESIGN, not a
// live-cloud proof: whether the two placeholders resolve to genuinely
// IAM-unreachable projects in a real deployment is an S9/organizational
// governance fact this manifest cannot establish on its own (see README).
func TestAttackCD_CrossDomainResourceScopesUseDistinctProjectPlaceholders(t *testing.T) {
	manifest := mustLoad(t)
	domainProjectPlaceholder := map[string]string{}
	for _, p := range manifest.Principals {
		for _, scope := range p.ResourceScope {
			placeholder := placeholderSegment.FindString(scope.Pattern)
			if placeholder == "" {
				continue
			}
			if existing, ok := domainProjectPlaceholder[p.Domain]; ok && existing != placeholder {
				t.Errorf("domain %s uses inconsistent project placeholders: %q and %q", p.Domain, existing, placeholder)
			}
			domainProjectPlaceholder[p.Domain] = placeholder
		}
	}
	signing, hasSigning := domainProjectPlaceholder["signing"]
	authority, hasAuthority := domainProjectPlaceholder["authority_witness"]
	if !hasSigning || !hasAuthority {
		t.Fatal("expected both signing and authority_witness domains to declare a resource scope")
	}
	if signing == authority {
		t.Fatalf("signing domain and authority_witness domain must use distinct project placeholders, both use %q", signing)
	}
}

// -- Cross-cutting: every principal's required/forbidden lists are disjoint,
// re-asserted here (in addition to manifest_test.go) as an explicit named
// policy property since Validate() enforces it at load time already.

func TestPolicyCrossCutting_LoadItselfEnforcesNoOverlap(t *testing.T) {
	if _, err := Load(); err != nil {
		t.Fatalf("Load (which calls Validate) must succeed against the committed manifest: %v", err)
	}
}
