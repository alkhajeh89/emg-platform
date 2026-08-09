FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 emg
COPY libs/python/emg-common-types/src /opt/emg/libs/python/emg-common-types/src
COPY tools/scripts/provision-keycloak-realm.py /opt/emg/provision-keycloak-realm.py
ENV PYTHONPATH=/opt/emg/libs/python/emg-common-types/src
USER 10001
ENTRYPOINT ["python", "/opt/emg/provision-keycloak-realm.py"]
