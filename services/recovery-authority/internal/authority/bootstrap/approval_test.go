package bootstrap

import (
	"errors"
	"testing"
	"time"
)

func TestValidateDualControlAcceptsExactlyOneOfEachRole(t *testing.T) {
	t.Parallel()
	now := time.Date(2026, 8, 18, 0, 0, 0, 0, time.UTC)
	digest := computeRequestDigest("a", "b")
	approvals := []Approval{
		{Role: ApprovalRoleAuthority, ApproverID: "alice", ApprovedAt: now.Add(-time.Hour), Reason: "ok", RequestDigest: digest},
		{Role: ApprovalRoleSigning, ApproverID: "bob", ApprovedAt: now.Add(-time.Hour), Reason: "ok", RequestDigest: digest},
	}
	if err := validateDualControl(approvals, digest, now, maxApprovalAge); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestValidateDualControlRejectsSameApprover is ATTACK_P: one person
// satisfying both approvals must never be accepted, even with otherwise
// perfectly valid, fresh, correctly-bound approvals.
func TestValidateDualControlRejectsSameApprover(t *testing.T) {
	t.Parallel()
	now := time.Date(2026, 8, 18, 0, 0, 0, 0, time.UTC)
	digest := computeRequestDigest("a", "b")
	approvals := []Approval{
		{Role: ApprovalRoleAuthority, ApproverID: "alice", ApprovedAt: now.Add(-time.Hour), Reason: "ok", RequestDigest: digest},
		{Role: ApprovalRoleSigning, ApproverID: "Alice", ApprovedAt: now.Add(-time.Hour), Reason: "ok", RequestDigest: digest},
	}
	err := validateDualControl(approvals, digest, now, maxApprovalAge)
	if !errors.Is(err, ErrDualControlSameApprover) {
		t.Fatalf("err = %v, want ErrDualControlSameApprover", err)
	}
}

func TestValidateDualControlRejectsMissingRole(t *testing.T) {
	t.Parallel()
	now := time.Date(2026, 8, 18, 0, 0, 0, 0, time.UTC)
	digest := computeRequestDigest("a", "b")
	approvals := []Approval{
		{Role: ApprovalRoleAuthority, ApproverID: "alice", ApprovedAt: now.Add(-time.Hour), Reason: "ok", RequestDigest: digest},
	}
	err := validateDualControl(approvals, digest, now, maxApprovalAge)
	if !errors.Is(err, ErrDualControlRolesMissing) {
		t.Fatalf("err = %v, want ErrDualControlRolesMissing", err)
	}
}

// TestValidateDualControlRejectsDuplicateRole is S6 Phase 9 scenario I
// (duplicate approvals): two AUTHORITY approvals never substitute for the
// missing SIGNING approval.
func TestValidateDualControlRejectsDuplicateRole(t *testing.T) {
	t.Parallel()
	now := time.Date(2026, 8, 18, 0, 0, 0, 0, time.UTC)
	digest := computeRequestDigest("a", "b")
	approvals := []Approval{
		{Role: ApprovalRoleAuthority, ApproverID: "alice", ApprovedAt: now.Add(-time.Hour), Reason: "ok", RequestDigest: digest},
		{Role: ApprovalRoleAuthority, ApproverID: "carol", ApprovedAt: now.Add(-time.Hour), Reason: "ok", RequestDigest: digest},
	}
	err := validateDualControl(approvals, digest, now, maxApprovalAge)
	if !errors.Is(err, ErrDualControlDuplicateRole) {
		t.Fatalf("err = %v, want ErrDualControlDuplicateRole", err)
	}
}

// TestValidateDualControlRejectsStaleApproval and
// TestValidateDualControlRejectsMismatchedRequestDigest are ATTACK_Q: a
// stale or replayed approval (captured for a different request) must never
// be accepted.
func TestValidateDualControlRejectsStaleApproval(t *testing.T) {
	t.Parallel()
	now := time.Date(2026, 8, 18, 0, 0, 0, 0, time.UTC)
	digest := computeRequestDigest("a", "b")
	approvals := []Approval{
		{Role: ApprovalRoleAuthority, ApproverID: "alice", ApprovedAt: now.Add(-maxApprovalAge - time.Hour), Reason: "ok", RequestDigest: digest},
		{Role: ApprovalRoleSigning, ApproverID: "bob", ApprovedAt: now.Add(-time.Hour), Reason: "ok", RequestDigest: digest},
	}
	err := validateDualControl(approvals, digest, now, maxApprovalAge)
	if !errors.Is(err, ErrApprovalStale) {
		t.Fatalf("err = %v, want ErrApprovalStale", err)
	}
}

func TestValidateDualControlRejectsMismatchedRequestDigest(t *testing.T) {
	t.Parallel()
	now := time.Date(2026, 8, 18, 0, 0, 0, 0, time.UTC)
	digest := computeRequestDigest("a", "b")
	otherDigest := computeRequestDigest("a", "different")
	approvals := []Approval{
		{Role: ApprovalRoleAuthority, ApproverID: "alice", ApprovedAt: now.Add(-time.Hour), Reason: "ok", RequestDigest: otherDigest},
		{Role: ApprovalRoleSigning, ApproverID: "bob", ApprovedAt: now.Add(-time.Hour), Reason: "ok", RequestDigest: digest},
	}
	err := validateDualControl(approvals, digest, now, maxApprovalAge)
	if !errors.Is(err, ErrApprovalRequestMismatch) {
		t.Fatalf("err = %v, want ErrApprovalRequestMismatch", err)
	}
}

func TestValidateDualControlRejectsFutureApproval(t *testing.T) {
	t.Parallel()
	now := time.Date(2026, 8, 18, 0, 0, 0, 0, time.UTC)
	digest := computeRequestDigest("a", "b")
	approvals := []Approval{
		{Role: ApprovalRoleAuthority, ApproverID: "alice", ApprovedAt: now.Add(time.Hour), Reason: "ok", RequestDigest: digest},
		{Role: ApprovalRoleSigning, ApproverID: "bob", ApprovedAt: now.Add(-time.Hour), Reason: "ok", RequestDigest: digest},
	}
	err := validateDualControl(approvals, digest, now, maxApprovalAge)
	if !errors.Is(err, ErrApprovalFromTheFuture) {
		t.Fatalf("err = %v, want ErrApprovalFromTheFuture", err)
	}
}

func TestValidateDualControlRejectsEmptyReasonAndApprover(t *testing.T) {
	t.Parallel()
	now := time.Date(2026, 8, 18, 0, 0, 0, 0, time.UTC)
	digest := computeRequestDigest("a", "b")
	cases := []struct {
		name      string
		approvals []Approval
		wantErr   error
	}{
		{
			name: "empty approver",
			approvals: []Approval{
				{Role: ApprovalRoleAuthority, ApproverID: "", ApprovedAt: now, Reason: "ok", RequestDigest: digest},
				{Role: ApprovalRoleSigning, ApproverID: "bob", ApprovedAt: now, Reason: "ok", RequestDigest: digest},
			},
			wantErr: ErrApprovalApproverRequired,
		},
		{
			name: "empty reason",
			approvals: []Approval{
				{Role: ApprovalRoleAuthority, ApproverID: "alice", ApprovedAt: now, Reason: "", RequestDigest: digest},
				{Role: ApprovalRoleSigning, ApproverID: "bob", ApprovedAt: now, Reason: "ok", RequestDigest: digest},
			},
			wantErr: ErrApprovalReasonRequired,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := validateDualControl(tc.approvals, digest, now, maxApprovalAge)
			if !errors.Is(err, tc.wantErr) {
				t.Fatalf("err = %v, want %v", err, tc.wantErr)
			}
		})
	}
}
