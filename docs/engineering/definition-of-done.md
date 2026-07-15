# Definition of Done

Reference: Engineering Master Plan §15; Engineering Backlog v1.0 §14.

A change is Done only when:

1. Code is reviewed and approved per `docs/engineering/coding-standards.md`.
2. Automated tests pass, including any new tests the change required.
3. Code coverage meets the team's governed threshold.
4. All DevSecOps gates pass (`.github/workflows/ci.yml`: lint,
   security-scan).
5. Observability instrumentation (`libs/python/emg-telemetry`, ADR-015) is
   present for any new service boundary, event, or decision point.
6. The change's behavior is traceable to a specific module/ADR section, and
   that traceability is recorded (PR template's "Governing Architecture
   Reference" section).
7. Documentation is updated (in-code and, where relevant, `/docs`).
8. Accessibility conformance is verified for any presentation-layer change
   (ADR-014 §9).
9. A security reviewer has explicitly signed off for any change touching
   classification, provenance, or audit behavior.

A change that is "feature complete" but fails any of the above is not Done.
