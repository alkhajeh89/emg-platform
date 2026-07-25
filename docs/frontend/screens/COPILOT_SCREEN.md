# Copilot Screen Specification

## Purpose
The Copilot screen provides an integrated surface for conversational and task-based interaction with EMG™ AI Agents.

## Primary Users
TBD — requires product and authorization model decision

## User Goals
- Query agents for analysis.
- Receive grounding context and citations.
- Iterate on task-based requests.

## Business Context
Module 9 (AI Orchestration).

## Entry Points
- Global Navigation Header.
- Contextual access from Search/Decision surfaces.

## Exit Points
- Search Screen (via citation drill-down).
- Decision Workspace (via task output promotion).

## Screen Layout & Major Regions
- **Chat History:** Threaded interaction.
- **Input Area:** Query/Task entry.
- **Grounding Context Pane:** Citations and evidence links.

## Information Hierarchy
1. Interaction thread.
2. Grounding context/provenance.

## Functional Requirements
- Support conversational/task-based interaction with agent roles.
- Grounding context and citations rendered alongside generated content.
- Mapped to [ADR-014](../../architecture/EMG_ADR-014_Enterprise_Presentation_Architecture.md) Section 5 (Agent Interaction).

## User Interactions
- Query entry.
- Task invocation.
- Citation exploration.

## Navigation Behavior
TBD — frontend routing specification required

## Data Inputs
- User query/instruction.
- Agent role selection.

## Data Outputs
- Interaction stream (text, citations, task outputs).

## BFF/API Dependencies
- [Module 9](../../../services/ai-orchestration/README.md).

## Authorization and Role Visibility
- Role: TBD — requires product and authorization model decision. Controlled by [Module 5](../../../services/authz/README.md).

## Security Classification Behavior
- Mandatory classification-aware rendering for grounding context and generated responses.

## States
- **Loading:** Stream generation animation.
- **Empty:** Start of interaction thread.
- **Error:** Standardized Error Component (stream interruption).
- **Offline:** Degraded (local chat history only).

## Accessibility Requirements
- Full screen-reader support for interaction threads.

## Internationalization and RTL Considerations
- Support for platform-defined locales.

## Responsive Behavior
- Desktop: Chat + Context pane.
- Mobile: Chat-only view.

## Performance Requirements
TBD — requires capacity and performance specification

## Telemetry and Audit Events
TBD — telemetry taxonomy required

## Component Dependencies
- Design System: Interaction Thread, Citation Chip, Confidence Badge.

## State Management
- [FRONTEND_STATE_MANAGEMENT.md](../architecture/FRONTEND_STATE_MANAGEMENT.md): Session chat history.

## Validation Rules
- Mandatory task parameters validation.

## UX Guardrails
- AI must visually distinguish generated material from human-authored context ([ADR-014](../../architecture/EMG_ADR-014_Enterprise_Presentation_Architecture.md)).

## Anti-Patterns
- Presenting agent output as definitive fact without provenance/citations.

## Acceptance Criteria
- Citations are interactable.
- Interaction stream supports real-time rendering.

## Definition of Done
- Interaction thread maintains state correctly.
- Citation drill-down works across surfaces.

## Future Extensions
- TBD — requires product or architecture decision regarding advanced agent role selection interfaces.
