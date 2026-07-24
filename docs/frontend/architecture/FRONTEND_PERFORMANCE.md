# Frontend Performance

## Purpose
The EMG™ Frontend Performance specification establishes the mandatory standards for optimizing the performance and scalability of all frontend applications. Its purpose is to guarantee a highly responsive, performant, and reliable user experience, particularly when dealing with complex, data-heavy visualizations like knowledge graphs and decision dashboards.

## Scope
This specification governs client-side performance, including code-level optimization, asset delivery, network utilization, rendering techniques (virtualization), and long-term scalability of the frontend architecture.

## Responsibilities
- **Frontend Engineering:** Responsible for implementing performance-optimized code, conducting regular performance audits, and adhering to performance budgets.
- **SRE/DevOps:** Responsible for monitoring platform-wide frontend performance metrics and alerting on deviations from performance SLOs.

## Dependencies
- **[ADR-017: Enterprise Capacity & Scalability Model](../../architecture/EMG_ADR-017_Enterprise_Capacity_Scalability_Model.md)**: Establishes capacity planning requirements.
- **[ADR-014: Enterprise Presentation Architecture](../../architecture/EMG_ADR-014_Enterprise_Presentation_Architecture.md)**: Establishes progressive disclosure requirements.

## Architecture Alignment
This specification directly supports ADR-014’s principle of "Progressive disclosure over data dump," ensuring that complex context (e.g., knowledge graph neighborhoods) is rendered only when needed, maintaining UI responsiveness.

## Architecture Rationale
Why performance-first?
1. **User Trust:** A sluggish UI erodes trust in an AI-assisted decision-making platform.
2. **Operational Continuity:** In high-pressure, air-gapped scenarios (ADR-014, Section 7), efficient frontend resource management is critical to prevent device-level performance degradation.
3. **Scalability:** By enforcing virtualization and code splitting at the architecture level, we ensure the platform remains performant as datasets grow from thousands to millions of entities.

## Implementation Guidelines

### 1. Performance Monitoring Flow
```mermaid
graph LR
    User[User Session] --> |Telemetry| Browser[Browser APIs]
    Browser --> |Metrics| Obs[Observability System]
    Obs --> |SLA Violation| Alert[Performance Alert]
```

### 2. Implementation Example (Virtualized Component)
```tsx
// @/components/ui/VirtualizedList.tsx
import { FixedSizeList as List } from 'react-window';

export const VirtualizedList = ({ items }: { items: any[] }) => (
  <List height={500} itemCount={items.length} itemSize={35} width={'100%'}>
    {({ index, style }) => <div style={style}>{items[index].name}</div>}
  </List>
);
```

## Security Considerations
- **Resource Exhaustion Attacks:** Maliciously crafted data payloads could trigger excessive rendering/computation on the client. Performance controls (like virtualization) act as a defense-in-depth measure.

## Performance Considerations
- **Core Web Vitals:** All surfaces must meet defined SLOs for LCP (Largest Contentful Paint), CLS (Cumulative Layout Shift), and INP (Interaction to Next Paint).
- **Network Efficiency:** BFF payloads must be minified, and network requests must be batched or throttled.

## Scalability Considerations
- **Rendering Scalability:** Techniques like windowing/virtualization are mandatory for rendering lists or graphs exceeding 100 items.

## Operational Considerations
- **Performance Budgeting:** Each major feature surface has an assigned performance budget. Exceeding this budget triggers mandatory remediation.

## Governance Rules
- Major UI architectural changes require a performance impact assessment.
- CI pipelines must include automated performance budget checks.

## Best Practices
- **Memoization:** Utilize `React.memo`, `useMemo`, and `useCallback` to prevent unnecessary component re-renders.
- **Web Workers:** Offload computationally heavy tasks (like complex graph layout algorithms) to Web Workers.

## Anti-Patterns & Common Mistakes
- **Premature Optimization:** Focusing on micro-optimizations before addressing architectural performance issues (like excessive re-renders).
- **Unbounded Rendering:** Rendering large, un-virtualized lists or graphs.
- **Blocking the Main Thread:** Performing synchronous, long-running JavaScript execution.

## Review Checklist
- [ ] Has the performance budget been verified for this feature?
- [ ] Is virtualization implemented for high-density components?
- [ ] Have Core Web Vitals been assessed in the staging environment?

## Definition of Done (DoD)
- Performance metrics meet defined SLOs in a production-like environment.
- Virtualization and code splitting are correctly implemented.
- Automated performance budget tests pass in CI.

## Future Extensions
- **Predictive Prefetching:** Leveraging AI to prefetch data for predicted user navigation paths.
- **Offline Mode:** Advanced resource caching and management specifically for disconnected environments (ADR-014).
