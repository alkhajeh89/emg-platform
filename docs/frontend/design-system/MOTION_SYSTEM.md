# Motion System

## Purpose
Defines the motion system to provide meaningful feedback and reduce cognitive load.

## Scope
All UI transitions and animations.

## Design Philosophy
Motion should be functional, not decorative.

## Business Context
Supports [ADR-014](../../architecture/EMG_ADR-014_Enterprise_Presentation_Architecture.md) interaction patterns.

## Principles
- **Feedback Animations:** Contextual responses to user actions.
- **Loading Philosophy:** Micro-animations for perceived performance.
- **Reduced Motion Guidance:** Must respect user's system preferences (prefers-reduced-motion).

## Accessibility Considerations
- Must respect `prefers-reduced-motion` media queries.

## Internationalization
- Motion should be consistent across locales.

## Enterprise Guidelines
- Standardized motion token usage.

## Usage Guidelines
- Transition types (enter/exit/hover).

## Anti-Patterns
- Long, distracting animations.

## Cross References
- [Enterprise UX Architecture & Design System](../../enterprise-design/DESIGN_SYSTEM.md)

## Future Extensions
- TBD — requires design system decision regarding motion timing and easing curves.

## Definition of Done
- Repository consistency verified.
