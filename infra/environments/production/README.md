# Production environment overlay (RC-1A)

This Kustomize overlay is the production deployment artifact for the RC1
single-replica topology, including the Studio frontend and Studio BFF. Render it with:

```sh
kubectl kustomize infra/environments/production
```

Before deployment, the platform operator must:

1. Use ADR-040's generated `production-resolved.yaml`; never deploy this
   overlay's `registry.invalid/...@sha256:...` source fixtures directly. The
   runtime-image release workflow publishes verified GHCR digests, signs and
   attests them, and retains complete rollback evidence. Protected release
   configuration and the first live release remain environment-owned.
2. Replace every `*.production.example.invalid` endpoint with the approved TLS
   endpoint for external PostgreSQL, Neo4j, Keycloak, and other dependencies.
3. Install External Secrets Operator and provide a provider-specific
   `ClusterSecretStore` named `emg-production-secrets` (or patch the reference).
   No provider credentials or secret values belong in this repository.
4. Provision the TLS Secret named `emg-studio-tls` through the cluster's
   certificate mechanism and configure the ingress host.
5. Provide a StorageClass suitable for the Identity audit-spool PVC.
6. Add environment-specific egress NetworkPolicies or CNI policy for each
   approved external dependency.
7. Provision the `emg-postgresql-backup-repository` claim outside this overlay.
   It must expose a POSIX filesystem in an administratively separate failure
   domain, use encrypted transport, deny public access, preserve atomic rename
   and `fsync`, and be readable from the isolated restore environment. The
   overlay intentionally does not select a StorageClass or storage provider.
8. Populate `emg/production/recovery/*` in the approved External Secrets store.
   The DSN must have only physical-backup privileges. The executable encryption,
   signing, and verification wrappers must reach environment-owned custody
   services without logging key material. Keep decryption material and its
   wrapper separately available to authorized restore operators; the scheduled
   backup pod does not receive either.

## RC-E recovery scheduling contract

`emg-postgresql-backup` runs at 01:00 UTC each day. Kubernetes forbids overlap,
allows one retry, and terminates an invocation after two hours. It uses a
dedicated tokenless ServiceAccount, a read-only root filesystem, explicit
resources, the externally provisioned repository claim, and External Secrets
material. Default-deny egress means the job remains nonfunctional until the
environment approves the PostgreSQL and custody endpoints.

The job validates the signed manifest after publication and writes
`recovery-evidence/BACKUP_ID.json` only on success. Its JSON stdout event is
`emg.recovery.backup.verified`; failure emits `emg.recovery.backup.failed` to
stderr and exits nonzero. Monitoring must consume CronJob failure and successful
backup age. Seven days of Job history aid diagnosis but are not durable evidence.

The approved 35-day/two-valid-backup floor remains explicit. Full-backup
deletion remains a reviewed two-step operation; WAL is never removed by the
repository tooling. Environment lifecycle rules may retain more, never less,
and must preserve WAL required by every retained base backup.

This configuration proves scheduling and fail-closed wiring only. Production
certification still requires validation of storage isolation, custody/escrow,
WAL delivery, alerting, capacity and lifecycle controls, plus a witnessed
isolated PITR rehearsal with reviewed evidence.

## ADR-041 ordered provisioning contract

Kubernetes does not infer dependencies between Jobs and Deployments. The
operator/CD system must execute these stages in order and wait for each Job to
complete successfully before continuing:

1. Apply the ExternalSecret resources and wait for the bootstrap, migration,
   Keycloak, inventory, and runtime references required by the Jobs to exist.
   This is part of the external-infrastructure-prerequisite stage; it does not
   make workloads deployable.
2. Run `emg-database-bootstrap` (`10-database-roles`). In addition to converging
   the three governed Audit/projector roles, the two ADR-034 Knowledge Graph
   roles, and the two ADR-043 Identity roles, this command validates any pre-existing local-seed
   Audit tables against the accepted schema contract and transfers ownership of
   only `audit_events` and `evidence_custody_events` to
   `emg_audit_migrator`. A mismatch fails the stage without changing ownership.
3. Run `emg-audit-migration`, `emg-knowledge-graph-migration`, and
   `emg-identity-migration` (`20-postgresql-migrations`) after database bootstrap succeeds.
4. Run `emg-keycloak-provision` (`30-keycloak-clients`). The Job converges the
   repository-governed Identity clients (`emg-identity-service` and
   `emg-svc-identity`) from the same `emg-identity-secrets` keys consumed by
   the runtime, then provisions tenant-scoped Audit Projector clients. It may
   create an absent client, repair descriptive metadata, required scopes,
   required roles, or secret material, but fails closed on authentication-mode,
   unexpected governed-scope, or unexpected governed-role drift. Its final
   JSON record contains client IDs and outcomes only; it never contains secret
   values.
5. Confirm External Secrets has synchronized the final workload material.
6. Run `emg-provisioning-validate` (`50-consistency-validation`). Both its
   database and identity containers must succeed. The identity container
   independently verifies both Identity client contracts and secret equality;
   it performs no convergence in `--validate-only` mode. Preserve its redacted
   JSON output as release evidence. The Identity migration uses the
   separately delivered `emg_identity_migrator` DSN and the runtime Deployment receives
   only the `emg_identity_app` refresh-state DSN.
7. Roll out `emg-identity` (`60-identity-service`) and `emg-audit`
   (`60-audit-service`) and wait for readiness.
8. Roll out `emg-audit-projector` (`70-audit-projector`).

### Transactionally failed Audit V001 recovery

`audit-migrate` deliberately halts when a prior attempt left a dirty marker. If
V001 failed solely because the seed-created Audit tables had not yet completed
the Stage 10 ownership handoff:

1. Preserve the failed Job output and migration-history evidence.
2. Re-run `emg-database-bootstrap`; it must complete the schema-validated,
   bounded ownership handoff successfully.
3. Run the migration image once with
   `python -m emg_persistence.provisioning audit-retry-v001` and the existing
   `EMG_AUDIT_MIGRATION_POSTGRES_DSN` secret.
4. Re-run the ordinary `emg-audit-migration` Job and then the Stage 50
   provisioning validator.

The recovery command accepts only the exact packaged V001 checksum with one
`success=false, dirty=true` history row. It re-executes V001 and marks success
in one PostgreSQL transaction. Any schema mismatch, altered checksum, later
history, non-V001 failure, or second recovery attempt is rejected. Operators
must not edit or delete migration history manually.

### Transactionally failed Knowledge Graph V005 recovery

Historical V005 is checksum-immutable. New migration runs apply its recorded
version/checksum through the scoped V009 privilege contract, which names only
Knowledge Graph objects; V006-V009 then continue normally. Existing successful
V005 histories remain valid and receive V009 as a forward migration.

For the exact released V005 failure caused by co-located Audit or Identity
objects, preserve the failed Job evidence and run the Knowledge Graph image
once with:

```sh
python -m emg_persistence.provisioning knowledge-graph-retry-v005
```

using `EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN`. The command accepts only
canonical successful V001-V004 plus canonical `success=false, dirty=true`
V005. It executes the scoped privilege contract and marks V005 successful in
one transaction. Then rerun the ordinary Knowledge Graph migration Job to
apply V006-V009 and run Stage 50 validation. Never edit or delete the V005
history record manually.

Run the repository preflight before finalization:

```sh
.venv/bin/python tools/ci/validate_production_provisioning.py
```

The `emg.platform/bootstrap-stage` annotations are machine-checkable ordering
metadata, not a claim that `kubectl apply` enforces the sequence. A Kustomize
render or readiness probe never substitutes for completed provisioning.

After the governed backend stages, roll out Knowledge Graph and Studio BFF and wait for readiness,
then roll out Studio. Public ingress targets Studio; Studio's `/bff/*` rewrite is the only browser
path to Studio BFF.

## Network boundary

Portable Kubernetes NetworkPolicy enforces default-deny ingress and egress for
EMG workloads, explicit DNS access, and the declared in-cluster application
flows. Standard NetworkPolicy cannot restrict arbitrary external destinations
by FQDN. `external-egress.example.yaml` is deliberately not included in the
overlay: it documents the CIDR-based input shape without guessing production
addresses. FQDN-aware controls, NAT/egress gateway policy, TLS inspection, and
External Secrets controller egress are cluster/CNI responsibilities.

Until the environment-specific external egress rules exist, workloads and Jobs
fail closed because their mandatory dependencies are unreachable.

Enforcement of NetworkPolicy egress (including the phase-scoped Identity
PostgreSQL rules below) requires a CNI that implements the `egress`
`policyTypes` (e.g. GKE Dataplane V2, Calico, Cilium). Confirm this before
relying on the recovery fence; on a CNI that only enforces ingress, every
egress rule in this overlay -- not only the recovery ones -- is silently
advisory.

### ADR-043 Amendment 1 recovery network fence

`identity-db-egress.normal.example.yaml`, `.phase1.example.yaml`, and
`.phase2.example.yaml` are three mutually exclusive templates for the same
NetworkPolicy object (`emg-identity-db-egress`), scoped only to Identity-owned
workload labels (see comments in each file). They are not included in this
overlay's `kustomization.yaml`; the environment applies exactly one of them at
a time, normally the `normal` variant. `tools/backup/identity-recovery-fence.sh`
applies the phase-appropriate template during a recovery event, reads back
both the object itself and every other NetworkPolicy in the namespace (to
detect a second, broader policy additively granting the same reachability --
see the round-2 remediation note in `external-egress.example.yaml`), and
writes a hash-bound, non-secret fence-evidence file only when both checks
pass. `python -m emg_persistence.provisioning validate-recovery-fence`
independently recomputes that hash from the evidence file's own embedded
canonical policy spec and re-derives the pod-selector labels from it -- never
trusting a separately-asserted label list -- before the recovery coordinator
may proceed to the next A9.6 step. See
`docs/operations/postgresql-backup-recovery.md` for the full procedure.

Audit, Audit Projector, Knowledge Graph, and the bootstrap/Stage-50
provisioning Jobs each have their own dedicated PostgreSQL-egress template
(`audit-db-egress.example.yaml`, `audit-projector-db-egress.example.yaml`,
`knowledge-graph-db-egress.example.yaml`, `provisioning-db-egress.example.yaml`)
rather than sharing the broad `external-egress.example.yaml` selector for
database reachability. `external-egress.example.yaml` remains the correct
place for dependencies with no recovery-phase exclusivity requirement
(Keycloak, the backup repository); it must never carry PostgreSQL content,
and Stage-50 statically rejects it, or any other template, if it does while
its selector also matches an Identity-owned pod.

Two further A9 evidence records are required before Stage-50 recovery
qualification will pass (`python -m emg_persistence.provisioning
validate-recovery-qualification`, or
`infra/kubernetes/base/provisioning-validation-recovery.yaml`): a database-
session-fence record (A9.3), produced by `tools/backup/identity-session-fence.sh`
using the governed database-bootstrap-administrator credential to terminate
and re-prove the absence of surviving `emg_identity_app` PostgreSQL sessions;
and a CNI egress-enforcement qualification record, produced by
`tools/backup/identity-cni-qualification-attest.sh` -- a schema-and-freshness
attestation only, since no packet-level enforcement test can run from this
repository. Ordinary Stage-50 (`emg-provisioning-validate`, `validate-database`)
never requires or consults any of this; only the distinct recovery-mode
command/Job does.

`infra/kubernetes/base/identity-recovery.yaml` additionally defines the
`emg-identity-recovery-qualify` Deployment: the same Identity image and
`emg_identity_app` runtime credential as `emg-identity`, held at zero replicas
outside a recovery window and deliberately not selected by the `emg-identity`
Service. The recovery coordinator scales it to one replica only after the
Phase 2 fence is established (A9.6 step 6); because no Service selects it,
reaching `READY` on this workload has no effect on client-facing traffic.
Final release (A9.6 step 9) scales it back to zero and scales the ordinary
`emg-identity` Deployment from zero to one, which is the only action that
restores client-facing service.

## Secret and job isolation

The checked-in `ExternalSecret` resources contain remote keys only. Kubernetes
Secrets are created by the operator; absent Secrets prevent container startup.
The database bootstrap administrator credential is mounted only in the
database-bootstrap Job. Audit, Knowledge Graph, and Identity migration credentials are
mounted only in bootstrap, migration, and validation Jobs; the Knowledge Graph
runtime DSN is additionally mounted in bootstrap so its role password can be
converged, and in the Knowledge Graph serving workload. The Keycloak administrator
credential is mounted only in provisioning/validation Jobs. Audit and
projector workloads receive the same non-secret identity inventory; only the
projector receives the secret-bearing tenant credential mapping.

## Runtime limitations

All serving workloads are single replica. Studio BFF uses process-local opaque
sessions and `Recreate`; a restart invalidates sessions and users must
reauthenticate. Direct Redis or datastore access by Studio BFF is not introduced.
This limitation blocks horizontal Studio BFF scaling but does not block the
approved single-replica RC1 topology.
