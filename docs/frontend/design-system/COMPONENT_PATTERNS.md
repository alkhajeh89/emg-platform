# Component Patterns

## Purpose
Establishes guidelines for component composition to ensure structural consistency across the platform.

## Scope
All shared design system components.

## Business Context
Ensures efficient development and UI uniformity as mandated by [ADR-014](../../architecture/EMG_ADR-014_Enterprise_Presentation_Architecture.md).

## Principles
- **Composition Philosophy:** Favor small, single-purpose components composed into larger features.
- **Reuse Strategy:** Maximize reuse of atomic components to minimize maintenance overhead.
- **Component Hierarchy:** Clear separation between layout, feature, and primitive components.
- **Pattern Consistency:** Consistent API surface and behavior for similar functional components.

## Enterprise Guidelines
- Components should rely on semantic design tokens.

## Accessibility
- TBD — requires design system decision.

## Internationalization
- Support RTL layout flipping and locale-specific text sizing.

## Usage Guidelines
- Use component library for all common UI patterns.

## Anti-Patterns
- Creating unique components for patterns already solved in the Design System.

## Cross References
- [Enterprise UX Architecture & Design System](../../enterprise-design/DESIGN_SYSTEM.md)
- [DESIGN_PRINCIPLES.md](DESIGN_PRINCIPLES.md)

## Future Extensions
- TBD — requires design system decision regarding component-specific extensibility APIs.

## Definition of Done
- Repository consistency verified.
