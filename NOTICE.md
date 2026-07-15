# Classification & Handling Notice

**Document/Repository Classification:** Internal — Engineering Delivery

This repository contains architecture references, engineering scaffolding,
and (from Sprint 2 onward) source code for a government/defense-adjacent
platform. Contributors must:

1. Not commit secrets, credentials, or classified government data to this
   repository, including in commit history, issues, or CI logs. Secrets
   scanning is enforced pre-commit and in CI (`.pre-commit-config.yaml`,
   `.github/workflows/ci.yml`).
2. Treat any mock government data used for local development or the Lab
   Prototype (Engineering Master Plan §18) as classification-labeled per
   Module 6 (Audit, Provenance & Digital Evidence) conventions, even though
   it is synthetic.
3. Route any question about data classification, export control, or
   government handling requirements to the Chief Information Security
   Officer function per ADR-016 (Enterprise Ownership Registry, Section 10 —
   Security Controls).

This notice is scaffolded under Sprint 1 (FEAT-01-1) and will be extended as
Module 6 (Audit, Provenance & Digital Evidence) is implemented (Sprint 5–6).
