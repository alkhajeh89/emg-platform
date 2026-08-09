FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY requirements-production.lock /build/requirements-production.lock
RUN pip install --require-hashes -r /build/requirements-production.lock

COPY libs/python/emg-common-types /build/libs/python/emg-common-types
COPY libs/python/emg-errors /build/libs/python/emg-errors
COPY libs/python/emg-telemetry /build/libs/python/emg-telemetry
COPY libs/python/emg-audit-client /build/libs/python/emg-audit-client
COPY libs/python/emg-ontology /build/libs/python/emg-ontology
COPY libs/python/emg-knowledge-lifecycle /build/libs/python/emg-knowledge-lifecycle
COPY libs/python/emg-knowledge-pipeline /build/libs/python/emg-knowledge-pipeline
COPY libs/python/emg-semantic-layer /build/libs/python/emg-semantic-layer
COPY libs/python/emg-trust-scoring /build/libs/python/emg-trust-scoring
COPY libs/python/emg-memory-graph /build/libs/python/emg-memory-graph
COPY libs/python/emg-platform-core /build/libs/python/emg-platform-core
COPY libs/python/emg-persistence /build/libs/python/emg-persistence
COPY services/audit-projector /build/services/audit-projector

RUN pip install --no-deps --no-build-isolation \
    /build/libs/python/emg-common-types \
    /build/libs/python/emg-errors \
    /build/libs/python/emg-telemetry \
    /build/libs/python/emg-audit-client \
    /build/libs/python/emg-ontology \
    /build/libs/python/emg-knowledge-lifecycle \
    /build/libs/python/emg-knowledge-pipeline \
    /build/libs/python/emg-semantic-layer \
    /build/libs/python/emg-trust-scoring \
    /build/libs/python/emg-memory-graph \
    /build/libs/python/emg-platform-core \
    /build/libs/python/emg-persistence \
    /build/services/audit-projector

FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS runtime
RUN useradd --create-home --uid 10001 emg
WORKDIR /app
COPY --from=base /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=base /usr/local/bin /usr/local/bin
ENV EMG_AUDIT_PROJECTOR_DEPLOYMENT_ENVIRONMENT=production
USER emg
CMD ["emg-audit-projector"]
