# Contributing to EMG™

This repository is governed by the frozen Architecture Baseline v1.0 and the
Engineering Master Plan. Engineering decisions within that baseline (Section
4: Technology Stack Selection) are made here; architectural change requires a
new ADR reviewed by the Enterprise Architecture Board — it is never made
through a pull request to this repository.

## Workflow

1. Branch from `main`. Direct pushes to `main` are blocked (`.github/settings.yml`).
2. Open a pull request. `CODEOWNERS` assigns required reviewers based on the
   Enterprise Ownership Registry (ADR-016).
3. All CI gates (`.github/workflows/ci.yml`) must pass: lint/static analysis,
   unit tests, build, security scanning, integration tests.
4. Cross-team review is required when a change touches a shared library
   (`/libs`) or a cross-module contract, per Engineering Master Plan §14.
5. Merge requires CODEOWNERS approval and a green CI run.

## Coding Standards

See `docs/engineering/coding-standards.md` (Engineering Master Plan §14).

## Definition of Done

See `docs/engineering/definition-of-done.md` (Engineering Master Plan §15;
Engineering Backlog v1.0 §14).

## Commit Messages

Conventional Commits format (`type(scope): summary`), e.g.:

```
feat(libs-telemetry): add correlation-id propagation helper
fix(ci): correct security-scan job path filter
chore(infra): add staging environment folder scaffold
```

This enables automated changelog generation per Engineering Master Plan §14.
