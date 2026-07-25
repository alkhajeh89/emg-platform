# Frontend Components

## Purpose
This directory contains all shared UI components for the EMG™ frontend.

## Scope
Shared components used across `apps/` and `libs/`.

## Naming Conventions
- Component folders: `kebab-case`
- Component files: `PascalCase.tsx` (e.g., `EvidenceCard.tsx`)
- Styles: Colocated in the same directory (e.g., `EvidenceCard.module.css`).

## Folder Organization
```text
components/
└── ComponentName/
    ├── ComponentName.tsx
    ├── ComponentName.test.tsx
    ├── ComponentName.module.css
    └── index.ts (barrel file)
```

## Ownership
Frontend Engineering Team.

## Examples
Components must be composed according to the [Enterprise UX Architecture & Design System](../../enterprise-design/DESIGN_SYSTEM.md) and [ADR-014](../../architecture/EMG_ADR-014_Enterprise_Presentation_Architecture.md).
