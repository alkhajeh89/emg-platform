# EMG™ Frontend Architecture Guide

*This guide details the current recommended implementation stack for the primary web-based presentation surface. It is a consumer of the [Enterprise Presentation Architecture (ADR-014)](../architecture/EMG_ADR-014_Enterprise_Presentation_Architecture.md) and does not override it.*

## Recommended Stack
*   **Framework**: Next.js (React/TypeScript)
*   **Styling**: Tailwind CSS
*   **Components**: shadcn/ui (governed by the [Design System](../enterprise-design/DESIGN_SYSTEM.md))
*   **Advanced Patterns**: React Flow, D3.js

## Key Principles
1.  **Framework Agnosticism**: While Next.js is currently used, the architecture prioritizes component-based composition (ADR-014) over framework-specific features.
2.  **BFF Pattern**: All client-side requests must go through the BFF layer. Direct module API access is prohibited.
3.  **State Management**: Transient UI state only. Session-scoped state must follow the [Session Memory lifecycle](../engineering/memory-graph-developer-guide.md).
