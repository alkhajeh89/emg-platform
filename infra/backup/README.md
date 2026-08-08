# PostgreSQL backup infrastructure

This directory defines the provider-neutral RC-1B recovery contract. The repository is a
POSIX filesystem mount; replication to separate failure domains is an operator responsibility.

- `backup.example.yaml` defines schedule, retention, encryption, and recovery objectives.
- `postgresql.conf.example` enables continuous WAL archiving for PITR.
- `restore.example.yaml` records an auditable restore plan.
- `manifest.schema.json` is the machine-readable backup manifest contract.
- `sample-manifest.json` is a schema-validation fixture, not a usable backup.

Copy examples into environment-owned configuration. Never commit DSNs, encryption keys, or
recipient material. Install `tools/backup/archive-wal.sh` on the database host and set
`EMG_BACKUP_REPOSITORY`, executable encryption/decryption wrappers, executable detached-manifest
sign/verify wrappers, a non-secret key reference, and the secret-managed DSN in the runtime.
The manifest signature is required because it authenticates restore roles, PostgreSQL WAL/LSN
boundaries, tablespace mappings, and evidence-ledger anchors.

The authoritative procedure and acceptance criteria are in
`docs/operations/postgresql-backup-recovery.md`.
