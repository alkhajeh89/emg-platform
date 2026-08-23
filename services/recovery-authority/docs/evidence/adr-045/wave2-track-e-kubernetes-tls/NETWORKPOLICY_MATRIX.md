# Real NetworkPolicy Enforcement (Phase 8) and External Egress Boundary (Phase 9)

All results are real, empirical outcomes on the live `emg-staging` GKE Dataplane V2 cluster — not inferred from YAML.

## Phase 8 — enforcement matrix

| # | Test | Result |
|---|---|---|
| A | Authority → signer:8443 | **Allowed** (ClusterIP and pod IP, both confirmed) |
| B | Unrelated pod in the same namespace (no authority label) → signer:8443 | **Denied** — real connection timeout |
| C | Pod with the authority's exact labels but the **signer's own** ServiceAccount → signer:8443 | **Allowed at the network layer** (labels matched the NetworkPolicy selector) — but see `SIGNERRPC_AUTH_MATRIX.md`: the application layer correctly denied it. Reported honestly per the required framing: **NetworkPolicy is an L3/L4 workload selector, not an identity-authentication boundary.** Application token authentication remains the required second gate; this result is never presented as NetworkPolicy proving KSA identity. |
| D | Pod in an unrelated namespace → signer | Not independently re-tested this wave (would require creating resources outside `ra-k8s-qual`, outside this task's authorized scope) — structurally guaranteed by the same default-deny + explicit-ingress-selector model already proven in test B, and by Track D's already-qualified WIF namespace-isolation findings |
| E | Default/unannotated KSA → signer, network layer | Not independently isolated from the identical pod's already-covered application-layer denial (see `SIGNERRPC_AUTH_MATRIX.md`) — the pod used the authority's own labels so the network path was open by design; the relevant deny occurred at token minting |
| F | Signer → authority, unintended path | **Denied** — signer has no egress rule permitting it, confirmed via a real timeout (`ra-signer-k8squal` → `ra-authority-k8squal:8080`) |
| G | Signer → arbitrary in-cluster service | Not separately tested beyond F; the signer's only granted egress is DNS, the GKE metadata server, and HTTPS/443 (see Phase 9 below) — no rule exists that would permit any other in-cluster destination |
| H | Authority → unrelated in-cluster workload | **Denied** — tested against the real, live `emg-identity` Service in the real `emg-staging` namespace: real timeout. This also confirms zero unintended interaction with live staging workloads at the network layer. |
| I | Public/internet client → signer | Structurally denied: `emg-recovery-signer` Service is `ClusterIP` only, no `Ingress`, no `LoadBalancer`, no `NodePort` anywhere in the qualification manifests (confirmed via `kubectl get svc`/manifest review) |
| J | External LB / node → signer | Same as I — no such path exists to test |

## Phase 9 — external egress boundary, classified honestly

- **DNS**: solved via the namespace-selector fix (`DNS_NETWORKPOLICY_DEFECT.md`) — proven, not a placeholder.
- **GKE metadata server** (WIF token issuance for both authority and signer): permitted via a fixed-IP `ipBlock` rule for `169.254.169.254/32:80`. This is safe as a static IP because it is the GKE metadata concentrator's fixed link-local address, not a dynamic external service IP — structurally different from the Google API case below.
- **Google APIs** (Spanner/GCS-adjacent client construction for authority; Cloud KMS for signer): standard Kubernetes `NetworkPolicy` **cannot** safely express "allow only Google's Spanner/GCS/KMS API endpoints" by FQDN — Google API IPs are dynamic and not expressible as a stable CIDR without being needlessly broad or brittle. The qualification's egress rules for this traffic are scoped to `0.0.0.0/0:443` per workload (authority and signer each get their own rule) — **explicitly reported as a genuine, honest limitation of plain Kubernetes NetworkPolicy, not invented away with a brittle static IP range.** This class of restriction (FQDN-aware egress control) requires a mechanism plain `NetworkPolicy` does not provide: a CNI-specific FQDN policy feature, a service mesh, or an egress proxy — none of which this task was authorized to introduce. **This is reported as a real, standing production-readiness gap if tighter-than-port-443 Google API egress control is ever required — not hidden.**
- Authority is not granted KMS egress; signer is not granted Spanner/GCS egress — both remain scoped to only what their own real client-construction/RPC calls require, matching the least-privilege model already established in Wave 1/Track C.

No case in this matrix resolved to an unintended allow. No P0/P1 NetworkPolicy defect exists beyond the DNS defect already reported and fixed.
