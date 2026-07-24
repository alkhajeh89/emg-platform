# Frontend Screens

## Purpose
This directory contains screen-level component compositions.

## Scope
Screen families defined in [ADR-014](../../architecture/EMG_ADR-014_Enterprise_Presentation_Architecture.md).

## Naming Conventions
- Screen folders: `kebab-case`
- Screen files: `PascalCase.tsx` (e.g., `DecisionBriefingScreen.tsx`)

## Folder Organization
```text
screens/
└── ScreenName/
    ├── ScreenName.tsx
    ├── ScreenName.test.tsx
    └── index.ts
```

## Ownership
Frontend Engineering Team.

## Examples
Screen compositions must map directly to the backend capability (Search, Authoring, Agent Interaction, Decision Workspace) as mandated by ADR-014.
