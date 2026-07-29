# EMG Knowledge Graph Service — production image (Module 7, FEAT-05-6,
# Sprint 7.1-7.4; Knowledge Graph Integration Closure Group B1).
# Thin deployment shell over the shared knowledge-graph libraries, following
# the same multi-stage layout as services/audit/Dockerfile and
# services/identity/Dockerfile.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Shared libraries (Module 3, ADR-012) this service depends on — copied in
# explicitly rather than installed from an index, since they are not yet
# published to a package registry (Sprint 1 scope note). This list must match
# services/knowledge-graph/pyproject.toml's `emg-*` dependencies and
# docker/dependencies.yaml's `knowledge-graph` entry exactly
# (tools/ci/check_dependency_manifest.py, check_dependency_drift.py).
COPY libs/python/emg-common-types /build/libs/python/emg-common-types
COPY libs/python/emg-errors /build/libs/python/emg-errors
COPY libs/python/emg-ontology /build/libs/python/emg-ontology
COPY libs/python/emg-platform-core /build/libs/python/emg-platform-core
COPY libs/python/emg-memory-graph /build/libs/python/emg-memory-graph
COPY libs/python/emg-telemetry /build/libs/python/emg-telemetry
COPY libs/python/emg-api-contracts /build/libs/python/emg-api-contracts
COPY libs/python/emg-persistence /build/libs/python/emg-persistence

# ADR-025 Group C2: authorization enforcement (PEP contract + ABAC evaluator).
COPY libs/python/emg-auth-client /build/libs/python/emg-auth-client
COPY libs/python/emg-policy-engine /build/libs/python/emg-policy-engine

# emg-memory-graph's own declared dependencies (transitively required at
# install time even though this service does not import them directly).
COPY libs/python/emg-knowledge-lifecycle /build/libs/python/emg-knowledge-lifecycle
COPY libs/python/emg-knowledge-pipeline /build/libs/python/emg-knowledge-pipeline
COPY libs/python/emg-semantic-layer /build/libs/python/emg-semantic-layer
COPY libs/python/emg-trust-scoring /build/libs/python/emg-trust-scoring
COPY libs/python/emg-audit-client /build/libs/python/emg-audit-client

COPY services/knowledge-graph /build/services/knowledge-graph

RUN pip install \
    /build/libs/python/emg-common-types \
    /build/libs/python/emg-errors \
    /build/libs/python/emg-ontology \
    /build/libs/python/emg-knowledge-lifecycle \
    /build/libs/python/emg-knowledge-pipeline \
    /build/libs/python/emg-semantic-layer \
    /build/libs/python/emg-trust-scoring \
    /build/libs/python/emg-audit-client \
    /build/libs/python/emg-memory-graph \
    /build/libs/python/emg-platform-core \
    /build/libs/python/emg-telemetry \
    /build/libs/python/emg-api-contracts \
    /build/libs/python/emg-persistence \
    /build/libs/python/emg-auth-client \
    /build/libs/python/emg-policy-engine \
    /build/services/knowledge-graph

FROM python:3.11-slim AS runtime

RUN useradd --create-home --uid 10001 emg
COPY --from=base /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=base /usr/local/bin /usr/local/bin

# ADR-025 Group C10: `Settings.policy_config_path`'s default
# ("services/knowledge-graph/config/policy.example.yaml") is a relative
# path resolved against the process cwd — mirroring
# services/identity/config.py's identical `policy_config_path` convention.
# WORKDIR + this COPY make that default resolve inside the running
# container without requiring every deployment to override
# EMG_KNOWLEDGE_GRAPH_API_POLICY_CONFIG_PATH just to get the packaged
# example (still local-development-only; a real deployment authors and
# mounts/bakes in its own policy file at this same path or points the env
# var elsewhere). Without this, the container's default policy lookup
# would silently fail closed (empty, default-deny ruleset) even though a
# real deployment intends to use its own file — the fail-closed *behavior*
# is correct either way, but the *file* should not go missing by omission.
WORKDIR /app
COPY --from=base /build/services/knowledge-graph/config /app/services/knowledge-graph/config

# ADR-033 Phase 3: the reviewed, immutable production catalog is packaged
# with the deployment and loaded before the process can serve traffic.
ENV EMG_KNOWLEDGE_GRAPH_API_SCHEMA_CATALOG_PATH=services/knowledge-graph/config/schema-catalog.json \
    EMG_KNOWLEDGE_GRAPH_API_DEPLOYMENT_ENVIRONMENT=production

USER emg
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

# Apply any pending PostgreSQL migrations (Group B4; no-op unless
# EMG_KNOWLEDGE_GRAPH_API_STORE_BACKEND=postgres) before serving traffic.
CMD ["sh", "-c", "python -m emg_knowledge_graph_api.migrate && uvicorn emg_knowledge_graph_api.main:app --host 0.0.0.0 --port 8000"]
