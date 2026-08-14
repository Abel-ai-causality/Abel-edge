# Abel Price API Context

This document aligns the planned Abel price API with `abel-edge` runtime needs.

## Goal

`abel-edge` should fetch real price bars from Abel by default, without exposing
database tables or SQL details in user config.

## Endpoint

- Current default environment: Abel prod
- Login endpoint: `GET https://api.abel.ai/echo/web/credentials/oauth/google/authorize/agent`
- CAP graph endpoint: `POST https://cap.abel.ai/api/cap`
- Market bars endpoint: `POST https://cap.abel.ai/api/market/day_bar`
- Auth header: `Authorization: Bearer <ABEL_API_KEY>`
- Override auth base with `ABEL_AUTH_BASE_URL=<custom_base>`
- Override base URL with `ABEL_CAP_BASE_URL=<custom_base>`

Notes:
- `abel-edge` currently uses Abel prod for both graph discovery and market data
- `abel-edge login --json --no-browser` emits a JSON handoff event first, then
  the final authorization result, which is the preferred flow for agent-driven
  environments

## Two Request Modes

`day_bar` has two mutually exclusive modes. Edge never converts one mode into
the other after a failed request.

| Mode | Identity | Intended use | Price adjustment |
| --- | --- | --- | --- |
| market bars | `symbols` | targets, ordinary OHLCV, and canonical close/volume nodes | provider front-adjusted market history |
| graph node | one exact `node_id` | canonical non-market V4 graph parents | raw source values |

Both modes use UTC timestamps. The request must contain exactly one of
`symbols` or `node_id`; `node_ids` batching is not part of this interface.

### Symbol-mode request

```json
{
  "symbols": ["ETHUSD", "BTCUSD"],
  "start": "2023-01-01T00:00:00Z",
  "end": null,
  "timeframe": "1d",
  "limit": 600,
  "fields": ["open", "high", "low", "close", "volume"]
}
```

Notes:
- `symbols` are market-data symbols like `ETHUSD`, `605138.SS`, `9606.HK`,
  or `XFLI.TO`, not public graph IDs such as `ETHUSD.price`
- exchange suffixes are part of the market symbol and must not be stripped or
  interpreted as graph-node field suffixes
- `timeframe` is currently expected to be `1d`
- `limit` is applied per symbol
- `fields` lets the API trim payloads later, but `abel-edge` currently expects
  at least `timestamp`, `symbol`, `close` in the response
- A-share and Hong Kong price history returned by this mode is front-adjusted
  by the provider. Edge does not apply a second adjustment.

### Node-mode request

```json
{
  "node_id": "<exact registered CausalNodeV4 id>",
  "start": "2023-01-01T00:00:00Z",
  "end": null,
  "limit": 600
}
```

Notes:
- the canonical ID is opaque and is sent byte-for-byte; public ticker aliases
  and symbol normalization do not apply
- the response is raw even when the node represents close or volume
- canonical materialization uses this mode for non-market families, then
  applies the frozen graph-release transform in Edge
- canonical close/volume nodes use symbol mode so A-share and Hong Kong
  corporate-action adjustment matches the market-data contract
- a missing node is an error; Edge does not retry it through `symbols`

## Response Shape

Preferred response:

```json
{
  "data": [
    {
      "timestamp": "2026-01-02T00:00:00Z",
      "symbol": "ETHUSD",
      "open": 3360.4,
      "high": 3412.0,
      "low": 3328.9,
      "close": 3398.1,
      "volume": 18234.2
    }
  ]
}
```

Also accepted by the current adapter:
- `{ "result": [...] }`
- `{ "data": { "bars": [...] } }`
- `{ "result": { "items": [...] } }`

Each returned row should represent one daily bar.

Node mode accepts the same response envelopes. Its normalized row shape is:

```json
{
  "timestamp": "2026-01-02T00:00:00Z",
  "node_id": "<exact registered CausalNodeV4 id>",
  "value": 1.25
}
```

A returned `node_id`, when present, must equal the requested ID.

## Runtime Expectations

`abel-edge` normalizes the response into a DataFrame with these standard columns:

- `timestamp`
- `symbol`
- `open`
- `high`
- `low`
- `close`
- `volume`

Minimum required columns:
- `timestamp`
- `symbol`
- `close`

Runtime rules:
- timestamps must be parseable as UTC datetimes
- rows must be sortable by `symbol, timestamp`
- `(symbol, timestamp)` should be unique

Canonical node rows must have a unique UTC day. Their release-specific
alignment, transform, and availability lag are applied after retrieval.

## Why This Contract

- keeps `abel-edge` config simple
- keeps database schema hidden behind Abel
- supports multi-asset strategies and causal parent lookups
- matches the engine contract: strategies need aligned daily close series and may
  optionally use OHLCV fields later
