# Risk Overview

**Classification:** Supporting executive risk summary; non-governing
**Authority boundary:** This document does not set risk appetite, product
scope, or architecture.

### Evidenced Controls and Foundations

- **Audit-First Foundation:** The audit platform implements event-based audit
  and provenance capabilities. This evidence does not establish that every
  platform path has adopted them.
- **Trust-Scoring Library:** The deterministic, storage-independent
  `emg-trust-scoring` library is implemented. It is not yet wired into a live
  ingestion service or adopted platform-wide.
- **Persistence Library:** The reusable PostgreSQL-authoritative persistence
  and Neo4j projection library is implemented and integration-tested. The live
  Knowledge Graph service's Neo4j serving-projection binding remains open.

### Unresolved Risks

- **Runtime Explainability Adoption:** Trust scoring and citation capabilities
  are not yet operational across the platform despite the implemented
  trust-scoring library.
- **Persistence Adoption:** The implemented persistence substrate is not yet
  bound across every required live service path.
- **Constructed Human Oversight:** HITL is an accepted design direction, but
  approval-gateway enforcement remains planned and must not be reported as an
  evidenced platform-wide control.

TBD — requires executive decision on enterprise-wide risk acceptance and threat appetite.
