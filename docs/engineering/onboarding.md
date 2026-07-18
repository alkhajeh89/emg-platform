# Engineering Onboarding

Target: a new engineer completes full local setup in under one working day
(Engineering Master Plan §13).

> **Before you clone — repository location matters.** Do **not** put the working
> clone inside a cloud-synced folder (iCloud Drive, including `~/Documents` /
> `~/Desktop` with Desktop & Documents sync, Dropbox, OneDrive, Google Drive).
> Those daemons corrupt editable installs and spawn conflict-copy directories.
> Use an unsynced path like `~/Developer/`. See
> `docs/engineering/repository-location-and-cloud-sync.md`.

## Prerequisites

- **Python 3.10, 3.11, or 3.12** (required). The toolchain targets 3.10 and is
  validated on 3.10–3.12; the version is pinned in `.python-version` (`3.10`).
  Newer interpreters (3.13/3.14) are **not** supported and bootstrap will refuse
  to use one silently — see Troubleshooting.
- Docker (with Docker Compose v2) — *optional*, only for local infra (`make up`).
  `make test` and `make lint` do not require it.
- Node.js 20+ — *optional*, only for front-end tooling under `apps/`.
- `gh` (GitHub CLI) — only for the branch-protection script.

## Setup

Fresh clone, from zero to green tests:

```bash
git clone <repo-url> emg-platform
cd emg-platform
make bootstrap                 # creates .venv, installs everything, hooks, .env
source .venv/bin/activate      # activate the project virtual environment
make test                      # pytest across /libs, /services
make lint                      # ruff + black --check across /libs, /services
```

`make bootstrap` runs `tools/scripts/bootstrap.sh`, which is **idempotent**
(safe to re-run) and:

1. Selects a supported Python interpreter (3.10–3.12) — never a newer default.
2. Creates (or repairs) an isolated virtual environment at `.venv`.
3. Installs the developer toolchain from `requirements-dev.txt`
   (pytest, pytest-asyncio, ruff, black, mypy, pre-commit, build, pip-audit).
4. Editable-installs every `libs/python/*` and every installable `services/*`
   package in single resolver passes, so the proprietary `emg-*` sibling
   dependencies resolve locally (nothing is fetched from PyPI for them).
5. Installs the pre-commit git hooks (`.pre-commit-config.yaml`).
6. Creates `.env` from `.env.example` (local-development defaults) if absent.
7. Starts local orchestration via `docker-compose.yml` (Postgres, Redis,
   Keycloak, Neo4j, Qdrant) **if Docker is available** — otherwise it is skipped
   with a warning and the rest of setup still succeeds.

You do **not** need to activate the venv for bootstrap itself; the script uses
`.venv/bin/python` explicitly. Activation is for your interactive shell.

## Verify

```bash
make setup-check     # diagnose the environment (venv, interpreter, tools, imports)
make test            # pytest across /libs, /services
make lint            # ruff + black --check across /libs, /services
make pre-commit      # run all pre-commit hooks against the whole tree
docker compose ps    # (optional) confirm local containers are healthy
```

## Re-running / updating

- Re-run `make bootstrap` any time (after a pull that adds a package, or to
  repair a broken `.venv`). It reuses a healthy `.venv` and only recreates it if
  the interpreter is missing/broken or unsupported.
- To wipe and start clean: `rm -rf .venv && make bootstrap`.

## Troubleshooting

- **"no supported Python interpreter found" / wrong version.** Your default
  `python3` is outside 3.10–3.12 (commonly 3.13/3.14 from Homebrew). Install a
  supported one, e.g. `pyenv install 3.10 && pyenv local 3.10`, or point bootstrap
  at a specific interpreter: `EMG_PYTHON=/path/to/python3.10 make bootstrap`.
- **`make test`/`make lint` say "no virtual environment found".** Run
  `make bootstrap`, then `source .venv/bin/activate`.
- **No Docker.** `make bootstrap` still completes; infra is skipped. Install
  Docker later and run `make up`. To skip the infra step explicitly:
  `EMG_SKIP_DOCKER=1 make bootstrap`.
- **Pre-commit first run is slow / needs network.** The first hook run downloads
  each hook's environment once; subsequent runs are offline.

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
