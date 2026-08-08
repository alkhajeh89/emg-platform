# EMG Studio BFF — production image (Phase 2B).
# Thin deployment shell, following the same multi-stage layout and
# hash-pinned dependency install as services/audit/Dockerfile and
# services/knowledge-graph/Dockerfile.

FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements-production.lock /build/requirements-production.lock
RUN pip install --require-hashes -r /build/requirements-production.lock

# Shared libraries this app depends on — must match
# apps/studio-bff/pyproject.toml's `emg-*` dependencies and
# docker/dependencies.yaml's `studio-bff` entry exactly
# (tools/ci/check_dependency_manifest.py).
COPY libs/python/emg-common-types /build/libs/python/emg-common-types
COPY libs/python/emg-errors /build/libs/python/emg-errors
COPY libs/python/emg-telemetry /build/libs/python/emg-telemetry
COPY libs/python/emg-api-contracts /build/libs/python/emg-api-contracts

COPY apps/studio-bff /build/apps/studio-bff

RUN pip install --no-deps --no-build-isolation \
    /build/libs/python/emg-common-types \
    /build/libs/python/emg-errors \
    /build/libs/python/emg-telemetry \
    /build/libs/python/emg-api-contracts \
    /build/apps/studio-bff

FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS runtime

RUN useradd --create-home --uid 10001 emg
COPY --from=base /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=base /usr/local/bin /usr/local/bin

ENV EMG_STUDIO_BFF_DEPLOYMENT_ENVIRONMENT=production

USER emg
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["uvicorn", "emg_studio_bff.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "5", "--limit-concurrency", "100", "--limit-max-requests", "10000"]
