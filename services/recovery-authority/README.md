# ADR-043 recovery-authority foundation

This directory is the isolated implementation boundary for the ADR-043 recovery authority.
The governing architecture remains exactly two provider components: Google Cloud Spanner is
the sole transition authority, and retention-locked GCS is the passive immutable rollback
witness.

This foundation does not implement or call either provider. A future Spanner adapter must use
the raw `spannerpb.SpannerClient` Commit RPC over gRPC with configured retries and resolver
service configuration disabled. The generated GAX client, high-level retrying transaction
helpers, and multiplexed sessions are prohibited for the authority Commit path.

`rotationcommit.acceptedRotationContext` is an ephemeral, package-private process capability.
It cannot be serialized or reconstructed by recovery code. Any ambiguous Commit outcome means
the old epoch must terminate and a new epoch with a fresh Spanner resource is required.

Deterministic protocol records use RFC 8949 deterministic CBOR. Decoders added in later work
must reject duplicate keys, unknown fields for the selected schema, indefinite lengths,
floating-point values, and non-minimal encodings.

This scaffold is not provider integration, environment qualification, ADR acceptance, or
authorization to provision infrastructure.
