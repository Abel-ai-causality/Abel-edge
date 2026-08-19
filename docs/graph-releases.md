# Abel Graph Releases

Abel Edge treats V3 and V4 as releases of the same optional `abel` provider.
Consumers pass a release configuration to Edge; they do not call CAP or the
market API directly.

## Configuration

The contract is `abel-edge.graph-release/v1`:

```json
{
  "contract": "abel-edge.graph-release/v1",
  "provider": "abel",
  "graph_ref": {
    "graph_id": "abel-main",
    "graph_version": "CausalNodeV4",
    "edge_set": "recall"
  }
}
```

This selects the V4 graph currently served by CAP. It is not a reference to a
downloaded `allnodes_causal_graph_*` package. `release_id` and
`expected_release_receipt_sha256` are optional assertions: Edge verifies them
when supplied, but does not invent them when CAP exposes only graph version.
For V4, `graph_ref.edge_set` accepts `precision` or `recall` and defaults to
`recall` when omitted. V3 does not accept this field. The normalized selector
is included in the canonical configuration hash and is sent to CAP as
`context.graph_ref.edge_set`.
Credentials and data are forbidden in this file; the Abel provider reads
authentication from its normal environment.

Equivalent JSON mappings have the same canonical configuration SHA-256.

## Commands

Run the fail-closed gate before consuming a release:

```bash
abel-edge graph-release doctor \
  --graph-release graph-release.json \
  --ticker AAPL.price \
  --json
```

The command exits zero only when CAP reproduces the configured graph identity
and every discovered driver in the probe is usable through its typed data
route. V3 parents are probed through their adjusted symbol routes; V4 parents
are probed through either adjusted symbol or exact canonical-node routes. Use a
ticker with a non-market parent when testing arbitrary-family V4 support; a
market-only target proves only the adjusted symbol route.

Select the same release during discovery:

```bash
abel-edge discover AAPL.price \
  --graph-release graph-release.json \
  --mode all \
  --json
```

Discovery emits `abel-edge.graph-discovery/v2`. V3 drivers use typed `symbol`
references. V4 preserves the original graph node ID and dispatches it as:

- `.price`, `.volume`, `_close`, or `_volume`: typed `symbol` reference with
  `close` or `volume`, routed through provider-adjusted market data.
- every other node: typed `canonical_node` reference routed byte-for-byte
  through `node_id`, requesting CAP's UTC scalar-series shape with no price
  adjustment.

Each typed reference has a canonical `driver_ref_sha256`. It is a routing
identity, not a transform or source-data receipt.

## Failure Boundary

Edge does not load an old S3 graph package, route price/volume graph nodes via
raw `node_id`, guess a symbol for other families, or silently aggregate raw
records. It sends `shape=series` for an exact non-market node and requires
`mode=node_series`, the same response node ID, one finite value per UTC
timestamp, and an advancing cursor. CAP owns the registry lookup and any
internal filtering or aggregation. A `node_records` response means the scalar
shape is unavailable; the doctor reports `blocked` and downstream integration
must stop.
