FROM python:3.11-slim@sha256:139020233cc412efe4c8135b0efe1c7569dc8b28ddd88bddb109b764f5a2d689

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 emg
COPY tools/scripts/provision-keycloak-realm.py /opt/emg/provision-keycloak-realm.py
USER 10001
ENTRYPOINT ["python", "/opt/emg/provision-keycloak-realm.py"]
