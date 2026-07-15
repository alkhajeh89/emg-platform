# /apps — Deployable Applications (ADR-014)

Web client and Backend-for-Frontend (BFF) layers, organized per screen
family (Search, Knowledge Authoring, Agent Interaction, Decision Workspace),
per Engineering Master Plan §3.

**Out of Sprint 1 scope.** This directory is scaffolded now so the monorepo
structure (Module 1) is complete from day one, but contains no application
code — Sprint 1's explicit constraints exclude both API and frontend
implementation. Implementation begins at EPIC-10 (Sprint 21+), per
Engineering Backlog v1.0 §6:

- FEAT-10-1 Design System Component Integration
- FEAT-10-2 BFF Layer Implementation
- FEAT-10-3 Search & Discovery UI
- FEAT-10-4 Agent Interaction UI
- FEAT-10-5 Human Decision Workspace UI
- FEAT-10-6 Knowledge Authoring UI

Stack selected (Engineering Master Plan §4): Next.js, React, TypeScript.
