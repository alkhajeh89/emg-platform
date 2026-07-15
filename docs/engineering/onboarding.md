# Engineering Onboarding

Target: a new engineer completes full local setup in under one working day
(Engineering Master Plan §13).

## Prerequisites

- Docker (with Docker Compose v2)
- Python 3.10+
- Node.js 20+
- `gh` (GitHub CLI), for branch-protection scripts only

## Setup

```bash
git clone <repo-url> emg-platform
cd emg-platform
cp .env.example .env
make bootstrap   # installs pre-commit hooks, brings up local infra
```

`make bootstrap` runs `tools/scripts/bootstrap.sh`, which:

1. Installs every `/libs/python/*` package in editable mode.
2. Installs and activates pre-commit hooks (`.pre-commit-config.yaml`).
3. Starts local orchestration via `docker-compose.yml`: Postgres, Redis,
   Keycloak, Neo4j, Qdrant.

## Verify

```bash
make lint    # ruff + black --check across /libs, /services
make test    # pytest across /libs, /services
docker compose ps   # confirm all containers are healthy
```

## Next Steps

- Read `docs/repo-structure.md` to understand directory ownership.
- Read `docs/engineering/coding-standards.md` and
  `docs/engineering/definition-of-done.md` before opening a first PR.
- To scaffold a new service: `make new-service NAME=<service-name>`.

## Local Identity/Authorization (Module 4/5 development)

A lightweight Keycloak instance is already part of `docker-compose.yml`
(port 8080, admin/admin_local_dev_only) so Module 4/5 development does not
require shared infrastructure, per Engineering Master Plan §13. Realm/client
configuration is scaffolded starting FEAT-02-1 (Sprint 2).
