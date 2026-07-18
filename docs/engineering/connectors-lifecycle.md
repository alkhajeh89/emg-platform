# Connector & Plugin Lifecycle (EPIC-13 / FEAT-13-1)

Two fixed, closed, deterministic state machines. A transition is either in the
table or it is rejected with the typed `ConnectorLifecycleError`. State only — no
side effects, no I/O.

## Connector-instance lifecycle (`ConnectorLifecycle`)

States (`ConnectorLifecycleState`): `registered`, `configured`, `validated`,
`active`, `paused`, `stopped`, `failed`, `retired`.

```
registered ─▶ configured ─▶ validated ─▶ active ─┬─▶ paused ─┬─▶ active
                              ▲    │               │           └─▶ stopped ─┬─▶ active
                              │    │               ├─▶ stopped ─────────────┘  └─▶ retired
                              └────┘ (reconfigure) └─▶ failed ─┬─▶ stopped
                                                               └─▶ retired
```

- `registered → configured` — a validated configuration is bound.
- `configured → validated` — configuration + capabilities validated.
- `validated → active` — placed in service; `validated → configured` — reconfigure.
- `active → {paused, stopped, failed}`; `paused → {active, stopped}`;
  `stopped → {active, retired}`; `failed → {stopped, retired}`.
- `retired` is terminal.

`AbstractConnector.transition(to_state)` enforces this table.

## Plugin lifecycle (`PluginLifecycle`)

States (`PluginLifecycleState`): `discovered`, `validated`, `registered`,
`enabled`, `disabled`, `retired`.

```
discovered ─▶ validated ─▶ registered ─┬─▶ enabled ─┬─▶ disabled ─┬─▶ enabled
                                        │            │             └─▶ retired
                                        └─▶ disabled └─▶ retired
```

`ConnectorPluginLoader.register` advances a plugin `discovered → validated →
registered → enabled` (after compatibility + validation checks);
`ConnectorPluginLoader.set_state` enforces the table for later transitions.
`retired` is terminal.

## Events

Lifecycle/operational moments are described by the immutable `ConnectorEvent`
(`ConnectorEventType`: `registered`, `configured`, `validated`, `activated`,
`paused`, `stopped`, `retired`, `sync_started`, `sync_completed`,
`change_detected`, `snapshot_taken`, `health_changed`, `error`). The framework
*models* these; it emits nothing itself — a connector or a future orchestration
layer produces them.

## Status

`ConnectorStatus` is an immutable snapshot combining the lifecycle state, the
declared `ConnectorHealth`, the `ConnectorStatistics` counters, and the last event
type — the single object a supervisor reads.
