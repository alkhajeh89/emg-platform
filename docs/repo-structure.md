# Repository Structure

Operationalizes Module 1's approved repository structure per Engineering
Master Plan §3. See root `README.md` for the summary table; this document
adds the rationale for each boundary.

- **`/apps`** and **`/services`** are kept separate so the presentation
  layer (ADR-014, owned by the CIO function) and backend modules (Modules
  4-10, owned per ADR-016 Section 1) never blur ownership at the directory
  level — CODEOWNERS enforces this boundary automatically.
- **`/libs`** exists so every service depends on the *same* versioned
  cross-cutting code (Module 3, ADR-012) instead of each reimplementing
  error handling, telemetry, or auth-client conventions independently.
- **`/infra`** and **`/observability`** are top-level, not nested under
  `/services`, because they are cross-cutting concerns owned centrally
  (CTO function, ADR-016 Section 1 items 8-9), not per-service concerns.
- **`/docs`** holds a reference copy of frozen architecture, not the
  authoritative copy — engineering must never edit architecture in place
  here; see `docs/architecture/README.md`.
- **`/tools`** holds developer tooling, versioned like any other shared
  library (Engineering Master Plan §6), so CI/CD pipeline definitions and
  scaffolding generators go through the same review process as application
  code.

This structure is Sprint 1 output (FEAT-01-1). Any apparent conflict with
Module 1's original specification is resolved in Module 1's favor and
raised to the Architecture Board — see Engineering Master Plan §3.
