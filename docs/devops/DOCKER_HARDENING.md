# Docker Hardening

EMG service Dockerfiles use digest-pinned Python bases, hash-locked Python
dependencies, multi-stage builds, a fixed non-root UID, and health checks.
`.dockerignore` excludes repository metadata, tests, caches, documentation,
front-end sources, and build artifacts from service build contexts.

Production orchestrators must enforce read-only roots, capability drop,
`no-new-privileges`, bounded writable temporary storage, CPU/memory/PID limits,
and network policy. Stateful vendor images require only their documented data
volumes; do not make a data directory read-only. Refresh a digest only through
a reviewed dependency update that reruns SBOM and vulnerability gates.
