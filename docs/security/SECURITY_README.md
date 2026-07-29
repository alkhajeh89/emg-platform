# Security Architecture Documentation

## Production hardening baseline

SRS-3 requires encrypted external transport, secret-store supplied credentials,
durable production backends, digest-pinned containers, hash-locked Python
dependencies, SBOM/provenance artifacts, and blocking dependency, container,
and secret scans. See `docs/devops/PRODUCTION_DEPLOYMENT_GUIDE.md`,
`docs/devops/DOCKER_HARDENING.md`, and
`docs/infrastructure/OPERATIONS_GUIDE.md`.

All EMG HTTP services reject request bodies above 1 MiB, JSON nesting deeper
than 32 levels, JSON collections above 1,000 members, and per-worker
concurrency above 100. Endpoint-specific pagination and export limits remain
additional controls. These application limits do not replace ingress rate
limits, connection limits, or workload resource quotas.

This directory contains the security architecture documentation for the EMG Platform.

## Required Documents

1. [Security README](SECURITY_README.md)
2. [Security Architecture Overview](SECURITY_ARCHITECTURE_OVERVIEW.md)
3. [Identity and Access Management](IDENTITY_AND_ACCESS_MANAGEMENT.md)
4. [Authentication Architecture](AUTHENTICATION_ARCHITECTURE.md)
5. [Authorization Model](AUTHORIZATION_MODEL.md)
6. [Agent Security](AGENT_SECURITY.md)
7. [Data Protection](DATA_PROTECTION.md)
8. [Audit and Logging](AUDIT_AND_LOGGING.md)
9. [Threat Model](THREAT_MODEL.md)
10. [Security Compliance](SECURITY_COMPLIANCE.md)
11. [Security Decision Register](SECURITY_DECISION_REGISTER.md)
12. [Security Glossary](SECURITY_GLOSSARY.md)
