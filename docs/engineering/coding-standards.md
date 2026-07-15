# Coding Standards

Reference: Engineering Master Plan §14.

## Python (backend services, FastAPI)

- PEP 8, enforced via `ruff` (lint) and `black` (format) in CI
  (`.github/workflows/ci.yml`) and pre-commit (`.pre-commit-config.yaml`).
- Type annotations required; `mypy --strict` runs against `/libs` and
  `/services` (`pyproject.toml`, `[tool.mypy]`).
- Every public function/class has a docstring sufficient for another
  engineer to understand intent without reading the implementation.

## TypeScript/React (presentation layer, ADR-014)

- Standardized lint/format configuration shared across all
  presentation-layer packages (scaffolded when `/apps` implementation
  begins, EPIC-10).

## API Design

- Follows the Enterprise API Architecture's REST and GraphQL conventions.
  Shared envelope/pagination conventions live in
  `libs/python/emg-api-contracts`. No service defines an ad hoc API style.

## Commit Messages

Conventional Commits (`CONTRIBUTING.md`), enabling automated changelog
generation.

## Secure Coding Baseline

OWASP guidance; enforced by DevSecOps gates
(`.github/workflows/ci.yml` `security-scan` job), not left to individual
reviewer judgment alone.

## Cross-Team Review

Any change touching `/libs` (a shared library) or a cross-module contract
requires at least one review from an engineer outside the author's
immediate team (`CODEOWNERS`).
