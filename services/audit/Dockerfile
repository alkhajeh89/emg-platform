# EMG Audit Service — production image (Module 6, FEAT-04-1, Sprint 6).
# Thin deployment shell over the shared audit libraries.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Shared libraries (Module 3, ADR-012) this service depends on — copied in
# explicitly rather than installed from an index, since they are not yet
# published to a package registry (Sprint 1 scope note).
COPY libs/python/emg-common-types /build/libs/python/emg-common-types
COPY libs/python/emg-errors /build/libs/python/emg-errors
COPY libs/python/emg-telemetry /build/libs/python/emg-telemetry
COPY libs/python/emg-api-contracts /build/libs/python/emg-api-contracts
COPY libs/python/emg-audit-client /build/libs/python/emg-audit-client
COPY libs/python/emg-audit-pipeline /build/libs/python/emg-audit-pipeline

COPY services/audit /build/services/audit

RUN pip install \
    /build/libs/python/emg-common-types \
    /build/libs/python/emg-errors \
    /build/libs/python/emg-telemetry \
    /build/libs/python/emg-api-contracts \
    /build/libs/python/emg-audit-client \
    /build/libs/python/emg-audit-pipeline \
    /build/services/audit

FROM python:3.11-slim AS runtime

RUN useradd --create-home --uid 10001 emg
COPY --from=base /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=base /usr/local/bin /usr/local/bin

USER emg
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["uvicorn", "emg_audit_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
