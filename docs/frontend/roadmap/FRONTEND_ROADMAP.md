# Frontend Roadmap

## Purpose
Outline the frontend development roadmap for EMG executive and operational surfaces.

## Scope
Short- and medium-term implementation milestones for EPIC-10 (ADR-014), including
**mandatory bilingual UX** per ADR-018.

## Responsibilities
Frontend Engineering, Product Team, Design System owners.

## Dependencies
- [Engineering Backlog](../../architecture/EMG_Engineering_Backlog_v1.0.md)
- [ADR-014 Presentation Architecture](../../architecture/EMG_ADR-014_Enterprise_Presentation_Architecture.md)
- [ADR-018 Bilingual Enterprise Architecture](../../architecture/EMG_ADR-018_Bilingual_Enterprise_Architecture.md)

## Architecture Alignment
Supports the prioritized backlog. Presentation is never a monolingual English-only
surface: Arabic RTL and English LTR are peer requirements from the first UI sprint.

## Bilingual UX milestones (ADR-018)

1. Design tokens and layout primitives support RTL and LTR without forked apps.
2. Dynamic language switching (user/session preference) with persistent choice.
3. Enterprise terminology management (approved Arabic/English term pairs).
4. Screen families (Search, Agent, Decision Workspace, Knowledge Authoring) ship
   with AR/EN copy and mirrored layouts.
5. Accessibility and QA matrices include Arabic RTL cases.

## Implementation Guidelines
Track progress against defined milestones; bilingual acceptance is required for
UI Definition of Done.

## Best Practices
Maintain transparency and agility; never hard-code LTR-only assumptions in
layout, icons, or charts.

## Future Extensions
Dynamic roadmap tracking; additional locales only via explicit ADR.
