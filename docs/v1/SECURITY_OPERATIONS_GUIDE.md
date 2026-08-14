# EMG v1 security operations guide

## Trust boundaries

Browser → Studio → Studio BFF is same-origin HTTPS. The browser receives only opaque session/CSRF
material. BFF → services uses registered service identity plus governed human delegation. Service
HTTP layers authenticate and authorize every request. PostgreSQL roles separate bootstrap,
migration, application, and projector authority. Neo4j is never an authorization or persistence
authority.

## Credential and secret rotation matrix

| Material | Custodian | Rotation rule | Validation before retirement | Evidence |
| --- | --- | --- | --- | --- |
| BFF OIDC client secret | Identity/Security | Environment policy; dual-valid overlap if provider supports it | Login, callback, session, delegation and logout | Sanitized run + witness |
| Service client secrets | Identity/Security | One registered identity retained; rotate secret, not logical client ID | Issuer/audience/tenant/role claims and service readiness | Sanitized token metadata only |
| PostgreSQL role passwords | Database/Security | Independently rotate bootstrap/migrator/runtime/projector DSNs | Role attributes, connectivity, migrations/readiness; no excess privilege | Role names/results, never DSNs |
| Neo4j credential | Database/Security | Environment policy | TLS connection, projection checkpoint/hash and repair | Sanitized result |
| Search cursor keys | Security/KMS custodian | New active key plus prior keys retained for every unexpired cursor lifetime | Rapid-rotation/unexpired cursor qualification; unknown/expired/disabled keys fail | Key IDs and windows only |
| Backup encryption/signing/wrapper material | Recovery/Security | Approved custody policy with escrow | Backup verification and isolated restore before retirement | Manifest/key IDs, no material |
| Approved Recovery Authority access (ADR-043) | Recovery/Security | Provider-specific; must independently satisfy the eight-property A3 qualification gate (single-linearization-point serialized rotation, monotonic non-reused version history) before use | Authority read/rotate capability and re-verification of the qualification gate | Provider audit-log reference only; the `(generation, authority_revision)` pair itself is non-secret audit-trail data, never a credential |
| TLS certificates | Platform/Security | Renew before expiry with overlap | DNS/SNI/chain/client and ingress health | Certificate fingerprints/dates |
| GitHub/OIDC signing identity | Release/Security | Workflow/repository trust policy | Cosign identity and provenance verification | Public signature/provenance |

Provider-specific schedules and custodians are `PENDING_LIVE`. No fixed interval is invented here.

## Operational security checklist

- No literal production Secrets, dev passwords, insecure URLs, mutable images, or placeholder
  endpoints in the resolved bundle.
- Service accounts, IAM and Workload Identity grant only required target permissions.
- Pods are non-root, read-only where defined, capability-dropped, seccomp-confined, resource-bounded,
  and do not automatically mount service-account tokens.
- NetworkPolicy default deny and required flows are active, not merely rendered.
- Tokens verify signature, issuer, exact audience, expiry, tenant and registered roles.
- Audit, projector, search, migration, recovery, vulnerability, signature and provenance failures
  remain blocking.
- During an Identity recovery event, every A9 fence-evidence record (network, database-session, CNI
  qualification) must be attributable to the exact governed recovery-coordinator identity performing
  that recovery, and network-fence evidence must match the exact namespace being recovered; Stage-50
  recovery qualification rejects a missing, blank, wrong-owner, wrong-namespace, or cross-namespace
  replayed record even if every other field is otherwise valid. Fence-owner/actor identity strings
  are audit-trail attribution values, never credentials.
- Logs/evidence contain no credentials, tokens, cookies, DSNs, cursor ciphertext, or raw sensitive
  search terms.

## Incident response ownership

Security leads containment and evidence handling for credential exposure, privilege escalation,
tenant/classification disclosure, Audit/integrity failure, signing/provenance mismatch, or backup
custody loss. The component owner diagnoses; the release authority stops promotion; the database
or platform owner performs approved recovery. No one-person role may both alter evidence and supply
the final independent witness.

## Incident minimum record

Record classification, detection time, affected environment/release/digests, correlation IDs,
scope, containment, integrity impact, recovery actions, owner, security reviewer, witness, and
follow-up. Store secrets separately under approved custody; redact them from the incident record.
