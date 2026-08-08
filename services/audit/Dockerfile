# EMG Audit Service — production image (Module 6, FEAT-04-1, Sprint 6).
# Thin deployment shell over the shared audit libraries.

FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements-production.lock /build/requirements-production.lock
RUN pip install --require-hashes -r /build/requirements-production.lock

# Shared libraries (Module 3, ADR-012) this service depends on — copied in
# explicitly rather than installed from an index, since they are not yet
# published to a package registry (Sprint 1 scope note).
COPY libs/python/emg-common-types /build/libs/python/emg-common-types
COPY libs/python/emg-errors /build/libs/python/emg-errors
COPY libs/python/emg-telemetry /build/libs/python/emg-telemetry
COPY libs/python/emg-api-contracts /build/libs/python/emg-api-contracts
COPY libs/python/emg-audit-client /build/libs/python/emg-audit-client
COPY libs/python/emg-audit-pipeline /build/libs/python/emg-audit-pipeline
COPY libs/python/emg-auth-client /build/libs/python/emg-auth-client
COPY libs/python/emg-policy-engine /build/libs/python/emg-policy-engine

COPY services/audit /build/services/audit

RUN pip install --no-deps --no-build-isolation \
    /build/libs/python/emg-common-types \
    /build/libs/python/emg-errors \
    /build/libs/python/emg-telemetry \
    /build/libs/python/emg-api-contracts \
    /build/libs/python/emg-audit-client \
    /build/libs/python/emg-audit-pipeline \
    /build/libs/python/emg-auth-client \
    /build/libs/python/emg-policy-engine \
    /build/services/audit

FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS runtime

RUN useradd --create-home --uid 10001 emg
WORKDIR /app
COPY --from=base /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=base /usr/local/bin /usr/local/bin
COPY --from=base /build/services/audit/config /app/services/audit/config

ENV EMG_AUDIT_DEPLOYMENT_ENVIRONMENT=production

USER emg
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["uvicorn", "emg_audit_service.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "5", "--limit-concurrency", "100", "--limit-max-requests", "10000"]
