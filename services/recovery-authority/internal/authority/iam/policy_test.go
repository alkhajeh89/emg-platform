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
// proves the manifest itself models the signing domain, the
// authority/witness domain, and (P1 remediation, this task) the
// compromise-ledger domain as living under three DIFFERENT
// project-placeholder namespaces -- so an administrator whose IAM reach is
// scoped to one domain's home resource pattern has no resource in another
// domain's home pattern to bind against, as modeled here. This is a
// structural property of the DESIGN, not a live-cloud proof (see README).
//
// Each domain's "home" placeholder is now anchored to the resource_type it
// structurally owns (spanner_database for authority_witness, kms_crypto_key
// for signing, gcs_bucket for compromise_ledger) rather than to "whichever
// placeholder was seen for this domain," because authority_witness-domain
// principals now legitimately hold EXPLICIT, DISCLOSED, read-only
// gcs_bucket resource_scope entries reaching into both other domains
// (recovery-authority-runtime and recovery-verification-read's own pin/
// ledger read access, ADR-045 §5 "verification capability is deliberately
// unprivileged") -- a real, intentional exception to same-domain-only
// resource_scope, not an accidental placeholder collision. That exception
// is itself independently proven read-only by
// TestPinStoreAndLedgerCrossDomainReadIsReadOnly below, so this test's
// narrower, resource-type-anchored form loses no coverage.
func TestAttackCD_CrossDomainResourceScopesUseDistinctProjectPlaceholders(t *testing.T) {
	manifest := mustLoad(t)
	homePlaceholder := func(domain, wantResourceType string) string {
		t.Helper()
		for _, p := range manifest.Principals {
			if p.Domain != domain {
				continue
			}
			for _, scope := range p.ResourceScope {
				if scope.ResourceType != wantResourceType {
					continue
				}
				placeholder := placeholderSegment.FindString(scope.Pattern)
				if placeholder != "" {
					return placeholder
				}
			}
		}
		t.Fatalf("no principal in domain %q declares a %q resource_scope entry", domain, wantResourceType)
		return ""
	}
	authority := homePlaceholder("authority_witness", "spanner_database")
	signing := homePlaceholder("signing", "kms_crypto_key")
	ledger := homePlaceholder("compromise_ledger", "gcs_bucket")

	if authority == signing || authority == ledger || signing == ledger {
		t.Fatalf("authority_witness (%q), signing (%q), and compromise_ledger (%q) domains must all use mutually distinct project placeholders", authority, signing, ledger)
	}
}

// TestPinStoreAndLedgerCrossDomainReadIsReadOnly is the direct Phase 5
// regression test ("verifier is read-only"): every principal whose
// resource_scope reaches into the signing domain's pin bucket or the
// compromise-ledger domain's bucket, from OUTSIDE that domain, must hold
// storage.objects.get and must never hold storage.objects.update/delete
// anywhere (update/delete are never legitimate for ANY principal against
// ANY of these create-if-absent-only buckets, cross-domain or not -- see
// TestNoStorageUpdateOrDeletePermissionAnywhere below for the unconditional
// form of that check). storage.objects.create is deliberately NOT checked
// here: this manifest's flat, unpaired required_permissions schema cannot
// distinguish "create on the home bucket" from "create on the cross-domain
// bucket" for a principal that legitimately needs create on ITS OWN
// domain's bucket (recovery-authority-runtime, recovery-bootstrap-deployment)
// -- that disclosed limitation is recorded in both principals' own notes
// fields, not silently assumed here. recovery-verification-read, which has
// no home bucket needing create at all, provides the clean, unambiguous
// positive case this test can fully verify.
func TestPinStoreAndLedgerCrossDomainReadIsReadOnly(t *testing.T) {
	manifest := mustLoad(t)
	crossDomainBucket := func(p Principal) bool {
		for _, scope := range p.ResourceScope {
			if scope.ResourceType != "gcs_bucket" {
				continue
			}
			placeholder := placeholderSegment.FindString(scope.Pattern)
			if (placeholder == "{signing_project}" || placeholder == "{compromise_ledger_project}") && p.Domain != "signing" && p.Domain != "compromise_ledger" {
				return true
			}
		}
		return false
	}
	for _, p := range manifest.Principals {
		if !crossDomainBucket(p) {
			continue
		}
		if !p.HasPermission("storage.objects.get") {
			t.Errorf("principal %s reaches a cross-domain pin/ledger bucket but does not hold storage.objects.get", p.ID)
		}
		for _, forbidden := range []string{"storage.objects.update", "storage.objects.delete"} {
			if p.HasPermission(forbidden) {
				t.Errorf("principal %s reaches a cross-domain pin/ledger bucket but holds %s", p.ID, forbidden)
			}
		}
	}
	// The one principal with no legitimate reason to hold create at all --
	// the clean, fully-verifiable case the comment above describes.
	reader := principal(t, manifest, "recovery-verification-read")
	if reader.HasPermission("storage.objects.create") {
		t.Error("recovery-verification-read must never hold storage.objects.create -- it is read-only by design")
	}
}

// TestNoStorageUpdateOrDeletePermissionAnywhere proves, across every
// principal in the manifest regardless of domain, that storage.objects.update
// and storage.objects.delete are never required -- every GCS-backed store
// in this architecture (witness, pin, ledger) is create-if-absent-only, so
// no legitimate principal ever needs to modify or remove an existing
// object.
func TestNoStorageUpdateOrDeletePermissionAnywhere(t *testing.T) {
	for _, p := range mustLoad(t).Principals {
		for _, forbidden := range []string{"storage.objects.update", "storage.objects.delete"} {
			if p.HasPermission(forbidden) {
				t.Errorf("principal %s must not hold %s -- every GCS-backed store in this architecture is create-if-absent-only", p.ID, forbidden)
			}
		}
	}
}

// TestPinCaptureAndLedgerWriterCannotSign is the direct Phase 5 regression
// test ("pin-capture principal cannot overwrite/delete existing pins" +
// "compromise writer cannot sign"): neither the pin-store nor the
// compromise-ledger write principal holds any cloudkms.cryptoKeyVersions.useToSign
// or storage.objects.update/delete permission.
func TestPinCaptureAndLedgerWriterCannotSign(t *testing.T) {
	for _, id := range []string{"recovery-pin-capture", "compromise-ledger-writer"} {
		p := principal(t, mustLoad(t), id)
		if p.HasPermission("cloudkms.cryptoKeyVersions.useToSign") {
			t.Errorf("%s must not hold cloudkms.cryptoKeyVersions.useToSign", id)
		}
		for _, forbidden := range []string{"storage.objects.update", "storage.objects.delete"} {
			if p.HasPermission(forbidden) {
				t.Errorf("%s must not hold %s -- pin/ledger write principals are create-if-absent only", id, forbidden)
			}
		}
	}
}

// TestPinCaptureCannotWriteLedgerAndLedgerWriterCannotCapturePins proves
// the two write principals this task adds cannot reach each other's
// resource: pin-capture (signing domain) has no compromise_ledger-domain
// resource_scope entry, and compromise-ledger-writer (compromise_ledger
// domain) has no signing-domain resource_scope entry.
func TestPinCaptureCannotWriteLedgerAndLedgerWriterCannotCapturePins(t *testing.T) {
	manifest := mustLoad(t)
	pinCapture := principal(t, manifest, "recovery-pin-capture")
	for _, scope := range pinCapture.ResourceScope {
		if placeholderSegment.FindString(scope.Pattern) == "{compromise_ledger_project}" {
			t.Fatal("recovery-pin-capture must not reach the compromise-ledger domain's resources")
		}
	}
	ledgerWriter := principal(t, manifest, "compromise-ledger-writer")
	for _, scope := range ledgerWriter.ResourceScope {
		placeholder := placeholderSegment.FindString(scope.Pattern)
		if placeholder == "{signing_project}" {
			t.Fatal("compromise-ledger-writer must not reach the signing domain's resources")
		}
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
