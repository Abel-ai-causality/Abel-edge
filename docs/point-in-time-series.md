# Point-in-Time Auxiliary Series

`abel-edge.point-in-time-series/v1` is the framework-owned contract for a
scalar external series that is not adequately identified by a ticker symbol.
It is additive to the existing `bars` and legacy `series` feed kinds.

## Runtime Invariant

Every materialized row has:

| Column | Meaning |
| --- | --- |
| `event_time` | Time represented by the observation |
| `available_at` | First time a backtest may use the observation |
| `value` | Finite scalar value |
| `timestamp` | Runtime alias of `available_at` |
| `revision_id` | Optional source revision identity |

Runtime filtering, point history, and strategy-visible indexing use
`available_at`, not `event_time`. This permits safe representation of releases,
publication delays, calendar-row availability lags, and revisions.

## Declaration

```yaml
feeds:
  cpi:
    kind: point_in_time_series
    series_spec:
      contract: abel-edge.point-in-time-series/v1
      series_id: macro.cpi.us
      source:
        adapter: my_data_adapter
        request:
          dataset: macro.cpi
          country: US
      schema:
        event_time_field: observed_at
        available_at_field: released_at
        value_field: reading
      materialization:
        frequency: irregular
        timezone: UTC
        missing_policy: none
        alignment_policy: asof
      transforms: []
      availability:
        mode: explicit
      provenance:
        source_receipt_sha256: "<64 lowercase hex characters>"
```

Credentials may not appear in the spec. Adapters obtain authentication from
the environment or another declared runtime auth provider.

## Adapter Boundary

The adapter named by `source.adapter` is resolved through the existing adapter
registry. It receives the validated `PointInTimeSeriesSpec` in
`FeedLoadRequest.series_spec` and returns the source fields declared by
`schema`. It must also put the actual source-data SHA-256 in
`frame.attrs["source_receipt_sha256"]`; Edge compares this receipt with the
frozen spec before normalization. The built-in CSV adapter hashes the source
file bytes. The adapter must also return the exact
`frame.attrs["series_spec_sha256"]` it used for materialization so a cache made
under another transform or alignment spec cannot be reused silently.

The framework then:

1. parses all timestamps into UTC;
2. calculates `available_at` when `availability.mode=calendar_days`;
3. requires finite scalar values and unique visibility times;
4. validates an optional UTC calendar-day grid;
5. exposes `available_at` as the runtime timestamp.

The canonical spec hash includes source selection, transforms, availability,
and provenance receipts. A changed schema, transform, source receipt, or
alignment receipt therefore produces a different identity.

## Access Policies

- `alignment_policy: asof` explicitly permits
  `ctx.feed(name).asof_series()`.
- `alignment_policy: native_only` rejects `asof_series()` and requires
  `native_series()` plus explicit strategy-owned calendar alignment.

The latter is intended for graph-native features where forward-filling across
a missing graph row would alter the released graph semantics. It is available
only through `compute_decisions(ctx)`; a legacy `compute_signals()` engine that
declares a native-only feed fails before strategy execution.

## Canonical Graph Nodes

`abel_edge.plugins.abel.canonical_node.compile_canonical_node_series_spec`
compiles `abel-edge.graph-node-spec/v1` into this generic contract and uses
the built-in `abel` adapter by default.

The resolver preserves the canonical node ID, family, dataset, field or
measure, key selectors, aggregation, transform parameters, release receipts,
and event-time alignment. Edge core does not learn graph parent ranks or graph
selection policy.

Canonical nodes are an Abel source capability, not a separately registered
adapter. `AbelDataFeedAdapter` dispatches `kind: point_in_time_series` to the
canonical materializer while continuing to serve ticker `bars` and legacy
`series` requests through the same `abel` registry name. Do not declare or
register an `abel_graph_node` adapter.

The canonical materializer supports market close/volume nodes and catalog
nodes. Target history and canonical close/volume nodes use the front-adjusted
`symbols` mode of Abel `day_bar`; non-market canonical nodes use its exact raw
`node_id` mode. The materializer dispatches these paths by canonical family,
never by guessing a ticker from the node ID. A failed non-market node request
never falls back to symbol mode.

It verifies the frozen raw-data receipt and, for market families, the exchange
reference receipt before Edge normalizes visibility time. A catalog schema
receipt remains part of the frozen node/spec identity, while the online node
registry owns dataset/key resolution for the raw series request.
The materialization request must provide explicit source start and end dates,
either through the runtime window or feed options, because a source receipt is
meaningless without a bounded row set.

Transforms that use weekday de-seasonalization must carry the seven finite
frozen `weekday_centers` in the canonical node spec. A release-array index by
itself is not reproducible and fails closed. Unresolved schemas, keys, event
times, receipts, or transform parameters remain adapter errors.

## Compatibility

Existing ticker `bars` and legacy `series` declarations are unchanged.
Strategies using the new feed kind enter the same execution, ledger, cost,
metrics, and verdict pipeline after feed normalization.
