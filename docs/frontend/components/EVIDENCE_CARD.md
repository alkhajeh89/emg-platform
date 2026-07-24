# Evidence Card Component Specification

## Purpose
Displays detailed evidence, including provenance.

## Usage
Used within the Decision Workspace.

## Business Context
Module 6 (Audit & Provenance).

## Parent Screens
Decision Workspace Screen.

## Child Components
Provenance Ledger link.

## Inputs (Properties)
- `content`: TBD — requires component API specification
- `provenanceId`: TBD — requires component API specification
- `confidence`: TBD — requires component API specification

## Outputs (Events)
- `onProvenanceClick`: TBD — requires component API specification

## Visual States
- Default, Highlighted.

## Loading State
Skeleton state.

## Empty State
N/A

## Error State
Error badge.

## Accessibility
ARIA-label for provenance links.

## Keyboard Behavior
- Tab-accessible.

## Responsive Behavior
- Responsive width based on workspace layout.

## Security Considerations
- Mandatory property-level redaction.

## Internationalization
- Support for platform-defined locales.

## Validation Rules
TBD — validation rules require product specification

## UX Guidelines
- Clearly distinguish AI vs. Human provenance.

## Anti-Patterns
- Presenting evidence without provenance.

## Acceptance Criteria
- Provenance is directly navigable.
- Confidence badge reflects data validity.

## Definition of Done
- Card reflects provenance accurately.
- Redaction policy enforced.

## Future Extensions
- TBD — requires product or architecture decision regarding integrated annotation.
