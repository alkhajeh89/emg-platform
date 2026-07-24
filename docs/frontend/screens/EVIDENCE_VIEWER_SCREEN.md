# Evidence Viewer Screen Specification

## Purpose
The Evidence Viewer provides a detailed, granular view of specific evidence items, including their full provenance and audit trail, to support explainable analysis.

## Primary Users
TBD — requires product and authorization model decision

## User Goals
- Review citation details.
- Link to authoritative source provenance.
- Assess evidence confidence score.

## Business Context
Module 6 (Enterprise Audit, Provenance & Digital Evidence Platform).

## Entry Points
- Search Screen (via citation click).
- Copilot Screen (via grounding reference).

## Exit Points
- Search/Agent surfaces.

## Screen Layout & Major Regions
- **Evidence Header:** Citation title and confidence.
- **Content Body:** Raw content.
- **Provenance Ledger:** Audit trail/Provenance metadata.

## Information Hierarchy
1. Citation metadata.
2. Evidence content.
3. Provenance/Audit trail.

## Functional Requirements
- Present citation and evidence provenance.
- Mapped to [ADR-014](../../architecture/EMG_ADR-014_Enterprise_Presentation_Architecture.md) Section 5 (Search & Discovery).

## User Interactions
- Citation exploration.
- Audit trail drill-down.

## Navigation Behavior
TBD — frontend routing specification required

## Data Inputs
- Evidence/Citation ID.

## Data Outputs
- Provenance details.

## BFF/API Dependencies
- [Module 6](../../../services/audit/README.md).

## Authorization and Role Visibility
- Role: TBD — requires product and authorization model decision. Controlled by [Module 5](../../../services/authz/README.md).

## Security Classification Behavior
- Enforce mandatory property-level redaction for all visualized evidence content.

## States
- **Loading:** Fetching citation content and audit ledger.
- **Empty:** No evidence data found.
- **Error:** Standardized Error Component.
- **Offline:** Read-only access to cached evidence.

## Accessibility Requirements
- Support for assistive technologies to read provenance data.

## Internationalization and RTL Considerations
- Support for platform-defined locales.

## Responsive Behavior
- Desktop: Modal or side-panel view.
- Mobile: Full-screen view.

## Performance Requirements
TBD — requires capacity and performance specification

## Telemetry and Audit Events
TBD — telemetry taxonomy required

## Component Dependencies
- Design System: Evidence Card, Provenance Ledger.

## State Management
- [FRONTEND_STATE_MANAGEMENT.md](../architecture/FRONTEND_STATE_MANAGEMENT.md): Evidence detail context.

## Validation Rules
- Mandatory ID validation.

## UX Guardrails
- Citations must be clearly linked to their authoritative provenance source (Module 6).

## Anti-Patterns
- Presenting evidence without its provenance link.

## Acceptance Criteria
- Evidence provenance is fully accessible.
- Audit trail is readable.

## Definition of Done
- Evidence details correctly map to audit/provenance metadata.

## Future Extensions
- TBD — requires product or architecture decision regarding integrated evidence annotation.
