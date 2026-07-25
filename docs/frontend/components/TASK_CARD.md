# Task Card Component Specification

## Purpose
Displays actionable task or decision information.

## Usage
Used within the Dashboard screen task queue.

## Business Context
Module 10 (Decision Intelligence).

## Parent Screens
Dashboard Screen.

## Child Components
None.

## Inputs (Properties)
- `title`: TBD — requires component API specification
- `deadline`: TBD — requires component API specification
- `status`: TBD — requires component API specification

## Outputs (Events)
- `onClick`: TBD — requires component API specification

## Visual States
- Default, High-priority (color-coded).

## Loading State
Skeleton state.

## Empty State
N/A

## Error State
N/A

## Accessibility
ARIA-label for status.

## Keyboard Behavior
- Tab-accessible.

## Responsive Behavior
- Responsive width.

## Security Considerations
- Redaction of sensitive task context.

## Internationalization
- Support for platform-defined locales (deadline format).

## Validation Rules
TBD — validation rules require product specification

## UX Guidelines
- Clearly highlight priority.

## Anti-Patterns
- Missing deadline information.

## Acceptance Criteria
- Navigation to Decision Workspace works.

## Definition of Done
- Task status is updated in real-time.

## Future Extensions
- TBD — requires product or architecture decision regarding bulk action support.
