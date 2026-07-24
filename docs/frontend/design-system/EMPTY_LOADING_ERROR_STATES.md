# Empty, Loading, and Error States

## Purpose
Standardizes handling of non-data states.

## Scope
All UI components requiring state management.

## Business Context
Improves UI robustness and user trust.

## Principles
- **Loading:** Immediate feedback, skeleton preference.
- **Empty:** Actionable empty states.
- **Error:** Standardized, non-disruptive, actionable error components.

## Enterprise Guidelines
- Use standardized state components.

## Accessibility
- Assistive technologies must be informed of state changes (e.g., loading).

## Internationalization
- All state-related labels externalized.

## Usage Guidelines
- Standard implementation for all components.

## Anti-Patterns
- Silently failing to show error or empty states.

## Cross References
- [FRONTEND_ERROR_HANDLING.md](../architecture/FRONTEND_ERROR_HANDLING.md)

## Future Extensions
- TBD — requires design system decision regarding "partial result" visualization patterns.

## Definition of Done
- All states verified across components.
