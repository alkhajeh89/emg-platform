# Defect 1 — Secret volume unreadable by non-root runtime (fsGroup absent)

## Discovery

Both `ra-authority-k8squal` and `ra-signer-k8squal` crash-looped on first real deployment:

```
recovery-authority: dependency composition (fail-closed on misconfiguration): construct signer TLS trust configuration (fail-closed): read signer CA file: open /var/run/emg-ra-k8s-qual/ca/ca.crt: permission denied
recovery-signer: TLS configuration (fail-closed): lifecycle: load TLS certificate/key pair: open /var/run/emg-recovery-signer/tls/tls.crt: permission denied
```

## Root cause (empirically confirmed with a throwaway busybox debug pod, deleted after use)

A pod under the identical `securityContext`/Secret-volume configuration as `recovery-signer.yaml` showed:

```
-r--r----- root root  tls.crt   (mode 0440, owner root, group root)
uid=10001 gid=10001 groups=10001
cat: can't open '/tls/tls.crt': Permission denied
```

Kubernetes always mounts Secret-volume files as `root:root` — `defaultMode` only sets permission bits, never ownership. A process running as `runAsUser: 10001, runAsGroup: 10001` (as both the base manifest and the qualification copy specified) is neither the file's owner nor a member of group `root`, so neither the owner-read nor group-read bit applies. The manifest never set `pod.spec.securityContext.fsGroup`, the only field that changes a mounted Secret volume's group ownership.

This is **not specific to the qualification copy** — the qualification manifest mirrored `infra/kubernetes/base/recovery-signer.yaml`'s `tls` volume block verbatim. The real, landed `recovery-signer` Deployment could not have started in any real cluster before this fix. This was never caught because no prior wave (A/B/C/D) had ever deployed these manifests to a real cluster; `kubectl kustomize` rendering (exercised by `tests/infrastructure/test_production_manifests.py`) only validates YAML text, never a real Pod's filesystem permissions.

## Fact-check

A `WebFetch` against `kubernetes.io`'s security-context documentation returned a summary claiming Secret volumes are "exempt" from `fsGroup` and default to mode 0600 — this directly contradicted both well-established Kubernetes documentation and the qualification's own prior observation (the debug pod's `defaultMode: 0o440` was honored exactly, not silently coerced to 0600). That fetched content was treated as unreliable and discarded. The real, authoritative verification was empirical, against the live cluster:

```
securityContext: {runAsUser: 10001, runAsGroup: 10001, fsGroup: 10001, ...}
volumes: [{name: tls, secret: {secretName: emg-recovery-signer-tls, defaultMode: 0o440}}]
```
Result:
```
drwxrwsrwt root 10001  .   (directory group changed to fsGroup)
-r--r----- root emg    tls.crt   (readable by group 10001/"emg", still not world-readable)
uid=10001(emg) gid=10001(emg) groups=10001(emg)
```
Real file content was read successfully by the non-root process, and the mode remained non-world-readable throughout.

## Fix applied

`infra/kubernetes/base/recovery-signer.yaml`: added `fsGroup: 10001, fsGroupChangePolicy: OnRootMismatch` to the pod's `securityContext`, matching the exact convention already used correctly elsewhere in this repository (`identity.yaml`, `postgresql-backup.yaml` — confirming this is an isolated oversight in `recovery-signer.yaml`, not a systemic gap). No other file changed: `runAsNonRoot`, `runAsUser`, `runAsGroup`, `allowPrivilegeEscalation=false`, `readOnlyRootFilesystem`, dropped capabilities, seccomp, and the Secret's `defaultMode: 0o440` were all preserved unchanged — no permission bit was loosened; only ownership was corrected.

`infra/kubernetes/base/recovery-authority.yaml` was **not** changed: its base topology mounts no Secret volume (Spanner/GCS/signer-RPC are all WIF/ADC-authenticated, no static credential). The qualification-only CA-bundle mount (needed only because Track E uses a self-issued, non-publicly-trusted qualification CA) received the equivalent `fsGroup` fix in the qualification manifest only, since it is not a base-manifest topology element.

## Out-of-scope related finding (not fixed, reported only)

`infra/kubernetes/base/identity-recovery.yaml` and `infra/kubernetes/base/provisioning-validation-recovery.yaml` mount Secrets (`emg-identity-recovery-authority`, `emg-provisioning-validate-recovery-input`) with the identical missing-`fsGroup` pattern. These are unrelated services (identity bootstrap/provisioning Jobs, not Recovery Authority/Signer) and are explicitly outside this bounded remediation's authorized scope — reported here for future action, not modified.

## Regression tests added

`tests/infrastructure/test_production_manifests.py`:
- `test_recovery_signer_fsgroup_matches_runtime_group` (both overlays)
- `test_recovery_signer_tls_secret_mode_excludes_world_access` (both overlays)
- `test_recovery_signer_has_no_chown_workaround`
- `test_recovery_authority_does_not_mount_signer_tls_secret`
- `test_recovery_authority_secret_volumes_have_compatible_fsgroup`
- `test_recovery_signer_and_authority_fsgroup_consistent_across_overlays`

Verified: reverting only `infra/kubernetes/base/recovery-signer.yaml` (via `git stash`) makes `test_recovery_signer_fsgroup_matches_runtime_group` fail with `KeyError: 'fsGroup'`; restoring the fix makes it pass again. All other tests unaffected.
