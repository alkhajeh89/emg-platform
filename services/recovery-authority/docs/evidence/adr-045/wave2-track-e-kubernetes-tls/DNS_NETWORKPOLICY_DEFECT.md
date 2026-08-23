# Defect 2 — DNS egress NetworkPolicy blocked the kube-dns Service ClusterIP

## Discovery

While validating that `ra-authority-k8squal` could resolve `emg-recovery-signer.ra-k8s-qual.svc.cluster.local` (required for Phase 6/7's real TLS/signerrpc path), a real `nslookup` through the pod's own `/etc/resolv.conf` timed out, despite the landed `emg-dns-egress`-equivalent policy (`namespaceSelector: kube-system` + `podSelector: k8s-app=kube-dns`) being applied.

## Diagnostic matrix (all against the real `emg-staging` GKE Dataplane V2 cluster; `KUBE_DNS_SERVICE_IP=34.118.224.10`, `KUBE_DNS_BACKEND_POD_IP=10.81.0.8`, ports UDP/TCP 53)

| Rule expression | → kube-dns pod IP directly | → kube-dns Service ClusterIP |
|---|---|---|
| Combined `namespaceSelector(kube-system)` + `podSelector(k8s-app=kube-dns)` | **Works** | **Fails** (real `nslookup` times out; TCP handshake times out) |
| `ipBlock: {cidr: <ClusterIP>/32}` (added alongside the rule above) | n/a | **Fails** — no change |
| `ipBlock: {cidr: 0.0.0.0/0}}` (diagnostic only, removed immediately after) | n/a | **Fails** — no change |
| `ipBlock: {cidr: <kube-dns pod IP>/32}` | **Fails** | n/a |
| `namespaceSelector(kube-system)` **alone** (no podSelector) | **Works** | **Works** (UDP and TCP) |

Root-cause isolation, via a disposable same-namespace Service+pod built specifically to separate variables:
- A fresh, correctly-configured (ingress **and** egress both explicitly allowed) same-namespace Service, reached via a `podSelector`-only rule: **both** its ClusterIP and pod IP worked.
- The identical fresh Service reached via an `ipBlock` egress rule for its own ClusterIP: **failed**.
- The real `emg-recovery-signer` Service (already-landed, same-namespace, `podSelector`-only rule, no `namespaceSelector` at all): ClusterIP **and** pod IP **both already worked**, unmodified, throughout.

**Conclusion:** two independent, empirically confirmed behaviors on this cluster/dataplane configuration:
1. `ipBlock`/CIDR-based egress rules never match in-cluster-addressed traffic (neither Service ClusterIPs nor raw pod IPs), at any CIDR breadth, including `0.0.0.0/0`.
2. A **cross-namespace combined** `namespaceSelector`+`podSelector` egress rule fails to permit Service-ClusterIP-directed traffic, while `namespaceSelector` alone (same scope, cross-namespace) and `podSelector` alone (same-namespace) both succeed for ClusterIP-directed traffic.

This is reported as an **empirically reproduced behavior of the qualified `emg-staging` cluster/Dataplane V2 configuration**, not asserted as universal GKE Dataplane V2 or Cilium behavior — official GKE documentation fetched twice did not confirm or deny this exact scenario (one fetch returned content contradicted by direct empirical testing and was discarded as unreliable; a second fetch, targeted at this specific defect, found no documented caveat matching it precisely, only adjacent known issues around Service/virtual-IP traffic and NetworkPolicy).

NodeLocal DNSCache is present in this cluster but was ruled out as a contributing factor: its DaemonSet runs with `hostNetwork: false` and is launched with `-setupiptables=false`, confirmed via direct pod-spec inspection — it is not intercepting any traffic on this path.

Zero NetworkPolicies exist in `kube-system` (`kubectl get networkpolicy -n kube-system` → empty) — the failure is entirely attributable to the qualification namespace's own egress rule, not an ingress restriction on kube-dns itself.

## Why this matters beyond DNS resolution for Track E

The identical `emg-dns-egress` rule shape exists in the real, landed `infra/kubernetes/base/network-policies.yaml`, applied to **every** EMG workload (`podSelector: {app.kubernetes.io/part-of: emg-platform}`). Per Phase 1's inventory, **zero NetworkPolicies are currently applied to the live `emg-staging` namespace** — meaning this defect has never been caught: if this default-deny + DNS-egress policy set were ever actually turned on for real staging workloads, every one of them would lose DNS resolution via the only address their `/etc/resolv.conf` ever uses.

## Remediation selected (Option A, user-authorized)

Replace the combined selector with **`namespaceSelector` alone**, scoped to `kube-system`, restricted strictly to UDP/TCP port 53:

```yaml
egress:
  - to: [{namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}}]
    ports: [{protocol: UDP, port: 53}, {protocol: TCP, port: 53}]
```

**Security classification (explicit, not glossed over):** this knowingly broadens the destination identity boundary from "kube-dns-labelled pods only" to "the `kube-system` namespace as a whole," but **only** on UDP/TCP port 53. Verified empirically that this does **not** open any other port: `authority → kube-dns ClusterIP:443` (a different real kube-system Service, `metrics-server`) remained denied after the fix. Default-deny, namespace confinement, and port confinement are all preserved; no `ipBlock`, no `0.0.0.0/0`, no hardcoded ClusterIP, no arbitrary external DNS egress was introduced. The narrower expression was empirically incompatible with real Service-VIP DNS resolution under this actual enforced dataplane; this is the accepted, proven trade-off.

Rejected alternatives: an `ipBlock` for the ClusterIP (proven completely non-functional, at any breadth, including `0.0.0.0/0` — see matrix above) and keeping the combined selector (functionally broken for real DNS resolution, since every pod's resolver only ever addresses the ClusterIP).

## Post-fix real-cluster requalification (fresh evidence, not inferred from the diagnostic matrix)

On the existing, untouched, already-running qualification pods:

| Test | Result |
|---|---|
| Real `nslookup` via `/etc/resolv.conf` | **Succeeds** — resolves `emg-recovery-signer.ra-k8s-qual.svc.cluster.local` → `34.118.230.34` |
| UDP/53 to ClusterIP | **Succeeds** |
| TCP/53 to ClusterIP | **Succeeds** |
| kube-system non-DNS port (`34.118.224.10:443`) | **Still denied** |
| External DNS (`8.8.8.8:53`) | **Still denied** |
| Authority → signer Service ClusterIP:8443 | **Still allowed**, unaffected |
| Authority → signer pod IP:8443 | **Still allowed**, unaffected |

## Fix applied

`infra/kubernetes/base/network-policies.yaml`'s `emg-dns-egress` rule, and the equivalent qualification-namespace rule. The failed temporary `34.118.224.10/32` `ipBlock` rule was removed completely, never propagated into the base manifest.

## Regression tests added

`tests/infrastructure/test_production_manifests.py`:
- `test_dns_egress_uses_namespace_selector_for_kube_system` (asserts no `podSelector` alongside the `namespaceSelector` — the load-bearing regression)
- `test_dns_egress_allows_only_dns_ports`
- `test_dns_egress_has_no_ipblock_or_wildcard_destination`
- `test_dns_egress_rule_is_single_and_self_contained`
- `test_dns_egress_does_not_broaden_other_network_policies`
- `test_authority_to_signer_restriction_unchanged_by_dns_fix`
- `test_dns_egress_consistent_across_staging_and_production`

Verified: reverting only `infra/kubernetes/base/network-policies.yaml` makes `test_dns_egress_uses_namespace_selector_for_kube_system` fail (`AssertionError: assert 'podSelector' not in {...}`); restoring the fix makes it pass again.
