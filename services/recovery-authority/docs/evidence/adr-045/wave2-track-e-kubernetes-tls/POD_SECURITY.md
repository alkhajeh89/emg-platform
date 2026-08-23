# Live Pod Hardening + RBAC Secret Isolation (Phase 10)

Captured directly from the live pod specs via the Kubernetes API (not from the authored YAML).

| Property | Authority | Signer |
|---|---|---|
| `hostNetwork` / `hostPID` / `hostIPC` | `false` / `false` / `false` | `false` / `false` / `false` |
| `hostPath` volumes | none | none |
| `runAsNonRoot` | `true` | `true` |
| `privileged` | unset (not privileged) | unset (not privileged) |
| `allowPrivilegeEscalation` | `false` | `false` |
| `readOnlyRootFilesystem` | `true` | `true` |
| Capabilities dropped | `["ALL"]` | `["ALL"]` |
| Resource requests/limits | `10m/32Mi` requests, `200m/128Mi` limits | `10m/32Mi` requests, `200m/128Mi` limits |
| Static credential files | none found | none found |
| Service-account key file | none | none |

## RBAC / Kubernetes API secret isolation

Both KSAs have `automountServiceAccountToken: false`, verified structurally (not merely as configuration): `ls /var/run/secrets/kubernetes.io/serviceaccount/` inside the authority pod returned `No such file or directory` — no Kubernetes API token is mounted at all.

`kubectl get rolebinding,clusterrolebinding -A` scanned for either `ra-authority-k8squal` or `ra-signer-k8squal` as a subject: **zero results**. Neither KSA has any RoleBinding or ClusterRoleBinding of any kind.

**Conclusion: the authority workload cannot read the signer's TLS Secret through Kubernetes RBAC** — not because a narrow RBAC rule excludes it, but because it has no Kubernetes API access whatsoever. This is the strongest possible form of the required guarantee; the explicit STOP condition ("if Kubernetes RBAC permits authority workload to read signer TLS Secret") was checked and did not trigger.

TLS private key material: mounted only into the signer pod (`emg-recovery-signer-tls` Secret, `tls` volume, `/var/run/emg-recovery-signer/tls`, read-only). The authority pod's only mounted Secret is the qualification CA bundle (public certificate material only, `ca.crt`) — never the signer's private key. Confirmed via `test_recovery_authority_does_not_mount_signer_tls_secret` and by direct manifest/live-pod review.
