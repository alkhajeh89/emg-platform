package bootstrap

import (
	"errors"
	"fmt"
	"strings"
	"time"
)

// ApprovalRole identifies which of the two mandatory, independent parties
// (ADR-044 §15A's signing administrative independence requirement, extended
// here to genesis) an Approval was made by. Genesis requires exactly one of
// each -- never two of the same role substituting for the missing one, and
// never a single approver satisfying both.
type ApprovalRole int

const (
	ApprovalRoleUnspecified ApprovalRole = iota
	// ApprovalRoleAuthority is the authority-side approval: the party
	// responsible for the Spanner/GCS authority and witness domain.
	ApprovalRoleAuthority
	// ApprovalRoleSigning is the signing-side approval: the party
	// responsible for the Cloud KMS signing domain, administratively
	// independent of ApprovalRoleAuthority (ADR-045 §7, §15A).
	ApprovalRoleSigning
)

func (r ApprovalRole) String() string {
	switch r {
	case ApprovalRoleAuthority:
		return "AUTHORITY"
	case ApprovalRoleSigning:
		return "SIGNING"
	default:
		return "UNSPECIFIED"
	}
}

// Approval is one dual-control attestation. It is a structured record, not
// a cryptographic signature -- this package has no opinion on how an
// approval was originally captured (ticketing system, signed change
// request, or similar governed external process); it only enforces the
// structural properties a genuinely independent dual-control approval must
// have before ExecuteGenesis may proceed.
//
// RequestDigest binds this approval to the exact GenesisRequest content it
// was given for -- an approval computed for one request can never be
// replayed against a different one (ATTACK_Q), and an approval captured
// long ago for the same identifiers but a different signing key, Spanner
// database, or lineage will also fail to match (see computeRequestDigest).
type Approval struct {
	Role          ApprovalRole
	ApproverID    string
	ApprovedAt    time.Time
	Reason        string
	RequestDigest [32]byte
}

var (
	ErrApprovalRoleRequired         = errors.New("bootstrap: approval role must be AUTHORITY or SIGNING")
	ErrApprovalApproverRequired     = errors.New("bootstrap: approval requires a non-empty approver identifier")
	ErrApprovalReasonRequired       = errors.New("bootstrap: approval requires a non-empty reason")
	ErrApprovalTimestampRequired    = errors.New("bootstrap: approval requires a non-zero ApprovedAt timestamp")
	ErrApprovalFromTheFuture        = errors.New("bootstrap: approval ApprovedAt is after the current time")
	ErrApprovalStale                = errors.New("bootstrap: approval is older than the maximum permitted age")
	ErrApprovalRequestMismatch      = errors.New("bootstrap: approval RequestDigest does not match this exact genesis request")
	ErrDualControlRolesMissing      = errors.New("bootstrap: dual control requires exactly one AUTHORITY approval and one SIGNING approval")
	ErrDualControlSameApprover      = errors.New("bootstrap: AUTHORITY and SIGNING approvals must come from distinct approvers")
	ErrDualControlDuplicateRole     = errors.New("bootstrap: more than one approval was supplied for the same role")
	ErrMaxApprovalAgeMustBePositive = errors.New("bootstrap: maxApprovalAge must be a positive duration")
)

func (a Approval) validate(now time.Time, requestDigest [32]byte, maxApprovalAge time.Duration) error {
	if a.Role != ApprovalRoleAuthority && a.Role != ApprovalRoleSigning {
		return ErrApprovalRoleRequired
	}
	if strings.TrimSpace(a.ApproverID) == "" {
		return ErrApprovalApproverRequired
	}
	if strings.TrimSpace(a.Reason) == "" {
		return ErrApprovalReasonRequired
	}
	if a.ApprovedAt.IsZero() {
		return ErrApprovalTimestampRequired
	}
	if a.ApprovedAt.After(now) {
		return ErrApprovalFromTheFuture
	}
	if now.Sub(a.ApprovedAt) > maxApprovalAge {
		return fmt.Errorf("%w: approved at %s, now %s, max age %s", ErrApprovalStale, a.ApprovedAt, now, maxApprovalAge)
	}
	if a.RequestDigest != requestDigest {
		return ErrApprovalRequestMismatch
	}
	return nil
}

// validateDualControl enforces ADR-044/045's dual-control requirement for
// genesis (S6 Phase 2): exactly one AUTHORITY and one SIGNING approval, from
// two distinct approvers, each individually valid, fresh, and bound to
// requestDigest. Any duplicate, missing role, shared approver, stale
// timestamp, or mismatched binding fails closed -- there is no path by
// which fewer than two genuinely independent, current approvals permit
// genesis to proceed.
func validateDualControl(approvals []Approval, requestDigest [32]byte, now time.Time, maxApprovalAge time.Duration) error {
	if maxApprovalAge <= 0 {
		return ErrMaxApprovalAgeMustBePositive
	}
	var authority, signing *Approval
	for i := range approvals {
		approval := approvals[i]
		if err := approval.validate(now, requestDigest, maxApprovalAge); err != nil {
			return fmt.Errorf("bootstrap: approval[%d]: %w", i, err)
		}
		switch approval.Role {
		case ApprovalRoleAuthority:
			if authority != nil {
				return ErrDualControlDuplicateRole
			}
			authority = &approvals[i]
		case ApprovalRoleSigning:
			if signing != nil {
				return ErrDualControlDuplicateRole
			}
			signing = &approvals[i]
		}
	}
	if authority == nil || signing == nil {
		return ErrDualControlRolesMissing
	}
	if strings.EqualFold(strings.TrimSpace(authority.ApproverID), strings.TrimSpace(signing.ApproverID)) {
		return ErrDualControlSameApprover
	}
	return nil
}

// approvalEvidence is the non-secret subset of an Approval durable evidence
// (Phase 10) may record: identity, role, and timing, never the free-text
// Reason verbatim beyond a bounded, already-audited-elsewhere summary, and
// never RequestDigest's raw bytes beyond a hex summary (it is not a secret,
// but there is no reason to widen the evidence format further than needed).
type approvalEvidence struct {
	Role       string    `json:"role"`
	ApproverID string    `json:"approver_id"`
	ApprovedAt time.Time `json:"approved_at"`
}

func approvalEvidenceFor(approvals []Approval) []approvalEvidence {
	out := make([]approvalEvidence, 0, len(approvals))
	for _, a := range approvals {
		out = append(out, approvalEvidence{
			Role:       a.Role.String(),
			ApproverID: a.ApproverID,
			ApprovedAt: a.ApprovedAt.UTC(),
		})
	}
	return out
}
