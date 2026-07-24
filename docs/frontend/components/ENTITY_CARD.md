# Entity Card Component Specification

## Purpose
Displays a summary of an entity.

## Usage
Used within the Knowledge Graph Screen and Entity Details screen.

## Business Context
Module 7 (Knowledge Graph).

## Parent Screens
Knowledge Graph Screen, Entity Details Screen.

## Child Components
Confidence Badge.

## Inputs (Properties)
- `label`: TBD — requires component API specification
- `entityType`: TBD — requires component API specification
- `confidence`: TBD — requires component API specification

## Outputs (Events)
- `onClick`: TBD — requires component API specification

## Visual States
- Default, Selected.

## Loading State
Skeleton state.

## Empty State
N/A

## Error State
N/A

## Accessibility
Semantic label.

## Keyboard Behavior
- Tab-accessible.

## Responsive Behavior
- Responsive width.

## Security Considerations
- Mandatory property-level redaction.

## Internationalization
- Support for platform-defined locales.

## Validation Rules
TBD — validation rules require product specification

## UX Guidelines
- Clearly distinguish between entity types.

## Anti-Patterns
- Overloading with too many properties.

## Acceptance Criteria
- Entity properties accurately map to Knowledge Graph.

## Definition of Done
- Redaction policy enforced.

## Future Extensions
- TBD — requires product or architecture decision regarding interactive property modification.
