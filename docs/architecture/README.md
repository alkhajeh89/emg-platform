# Architecture Reference Set

Reference copy of the frozen Architecture Baseline v1.0 document set, per
Engineering Master Plan §3: "a reference copy of the frozen Architecture
Baseline v1.0 document set, for engineering traceability; the authoritative
copy remains under Architecture Board control." Do not edit these files —
any architectural change is proposed as a new ADR through the Enterprise
Architecture Board, never as a pull request to this directory.

| Document | Covers |
| --- | --- |
| `EMG_Architecture_Baseline_v1.0_Final.md` | Frozen architecture of record: approved documents/modules/ADR registers, principles, engineering readiness statement |
| `EMG_Engineering_Master_Plan.md` | Build-execution plan: bootstrap, monorepo structure, tech stack, CI/CD, DevSecOps, sprint phases, coding standards, Definition of Done |
| `EMG_Engineering_Backlog_v1.0.md` | Sprint-by-sprint (1–24) Epic/Feature/Story/Task backlog, dependencies, milestones |
| `EMG_ADR-014_Enterprise_Presentation_Architecture.md` | Presentation layer: BFF strategy, component composition, screen families (ADR-014) |
| `EMG_ADR-015_Unified_Enterprise_Observability.md` | Shared logs/metrics/traces model, alerting, SLI/SLO/error budget (ADR-015) |
| `EMG_ADR-016_Enterprise_Ownership_Registry.md` | Accountable Owner / Operational Steward registry — source for `/CODEOWNERS` (ADR-016) |
| `EMG_ADR-017_Enterprise_Capacity_Scalability_Model.md` | Cross-layer capacity, HA, and disaster-recovery model (ADR-017) |

Modules 1–10 and ADR-012/013 are referenced throughout the above but are not
separately reproduced here, as their source documents were not provided to
engineering as standalone files at Sprint 1 bootstrap time; consult the
Architecture Board's authoritative repository for their full text.
