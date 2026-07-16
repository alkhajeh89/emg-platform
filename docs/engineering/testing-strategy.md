# Testing Strategy

Reference: Engineering Master Plan §16.

Standard pyramid: unit tests for business logic, integration tests across
service boundaries, end-to-end tests for full user-journey scenarios —
layered with each module's own testing obligations as they are implemented
(Module 7 §26, Module 8's grounding validation tests, Module 9 §17's
AI/agentic threat cases, Module 10's Decision Replay reconstruction tests).

Sprint 1 status: `libs/python/*` packages carry unit tests
(`tests/test_import.py` per package) exercising the scaffolded shared-library
surface. `/services` test directories are scaffolded (`tests/.gitkeep`) with
no test suites yet, since no service has business logic this sprint.
Performance/load testing against ADR-017's compounded-load model begins once
a full request chain exists (EPIC-07 onward).

## Authorization testing harness (Sprint 5, FEAT-03-4)

`emg_policy_engine.testing` is the platform's shared, reusable toolkit for
authorization testing: `AuthorizationScenario` (a declarative
principal/resource/action/expected-outcome expectation), `assert_scenario`
(raises `AssertionError` on mismatch), and `run_scenarios` (batch runner
returning failure messages). Any service embedding the PEP
(`emg_policy_engine`) uses this to express positive/negative authorization
cases declaratively instead of hand-writing engine or HTTP assertions. It has
no pytest runtime dependency (plain `assert` / returned strings) and no
YAML/DSL layer. Reference adoption:
`services/identity/tests/test_authz_scenarios.py`, which runs the harness
against that service's real `config/policy.example.yaml`.
