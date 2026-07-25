# Container Architecture

## Purpose
To define the containerization strategy for the EMG platform.

## Scope
Current scope is limited to local development containerization.

## Repository Evidence
- `docker-compose.yml`: Defines local orchestration of services and datastores.
- `services/identity/Dockerfile`: Defines the build for the identity service.
- `services/audit/Dockerfile`: Defines the build for the audit service.

## Current Implementation
Local development relies on container orchestration via Docker Compose. Services are built using context-based Dockerfiles.

## Constraints
TBD — requires engineering or architecture decision

## Dependencies
- Docker Engine
- Docker Compose

## Security Considerations
`docker-compose.yml` contains development-only secrets and environment settings labeled `local_dev_only`.

## Operational Considerations
`make up` and `make down` targets in `Makefile` manage the container lifecycle.

## Open Questions
TBD — requires engineering or architecture decision

## Cross References
- [Makefile](../../Makefile)
- [docker-compose.yml](../../docker-compose.yml)

## Future Considerations
TBD — requires engineering or architecture decision
