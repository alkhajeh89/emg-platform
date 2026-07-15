# emg-auth-client

Auth client (Module 4 Identity) and Policy Enforcement Point (Module 5
Authorization) interfaces consumed by every service.

Part of the EMG™ shared libraries workspace (Module 3, ADR-012). Scaffolded
in Sprint 1 (FEAT-01-2) as an empty, versioned package.

## Contents

- `Principal`, `AuthClient` — Module 4 identity contract. Implemented by
  `services/identity` (Sprint 2/3, EPIC-02).
- `ServicePrincipalLike` — structural (duck-typed) shape of Sprint 3's
  machine identity (`emg_identity.service_principal.ServicePrincipal`),
  declared here without importing it (libraries never depend on services).
- `Decision`, `AuthorizationRequest`, `PolicyEnforcementPoint` — Module 5
  authorization contract, added Sprint 4 (FEAT-03-1). The default concrete
  evaluator is the separate `emg-policy-engine` package (FEAT-03-2); see
  `docs/engineering/sprint-4-design.md`.
