# Storage Infrastructure

## Purpose
To define the storage strategy for the EMG platform.

## Scope
Current scope is limited to local development data persistence.

## Repository Evidence
- `docker-compose.yml`: Defines named volumes (`postgres-data`, `keycloak-data`, `neo4j-data`, `qdrant-data`).

## Current Implementation
Persistence for local development is managed via Docker named volumes in `docker-compose.yml`.

## Constraints
TBD — requires engineering or architecture decision

## Dependencies
- Docker Engine

## Security Considerations
Data persistence depends on underlying host disk security.

## Operational Considerations
`docker-compose.yml` volumes allow data to persist across container restarts.

## Open Questions
TBD — requires engineering or architecture decision

## Cross References
- [docker-compose.yml](../../docker-compose.yml)

## Future Considerations
TBD — requires engineering or architecture decision
