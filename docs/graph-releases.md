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
    "release_id": "example-release"
  },
  "expected_release_receipt_sha256": "<lowercase-sha256>"
}
```

V4 requires both `release_id` and the expected receipt. Legacy V3 may omit
them. Credentials, node decoders, transforms, and data are forbidden in this
file; the Abel provider reads authentication from its normal environment and
obtains release facts from CAP.

Equivalent JSON mappings have the same canonical configuration SHA-256.

## Commands

Run the fail-closed gate before consuming a release:

```bash
abel-edge graph-release doctor \
  --graph-release graph-release.json \
  --ticker AAPL.price \
  --json
```

The command exits zero only when CAP reproduces the configured release
identity. For V4 it also requires complete canonical node descriptors rather
than raw node IDs alone.

Select the same release during discovery:

```bash
abel-edge discover AAPL.price \
  --graph-release graph-release.json \
  --mode all \
  --json
```

Discovery emits `abel-edge.graph-discovery/v2`. V3 drivers use typed `symbol`
references. V4 drivers preserve their opaque node IDs and use typed
`canonical_node` references. A V4 discovery response without family and node
spec identity is diagnostic only and must not be materialized.

## Failure Boundary

Edge does not infer a V4 release from `graph_version`, guess a symbol from a
canonical node, load decoder or transform files from S3, or substitute raw
`day_bar` rows for a missing canonical descriptor. If CAP omits the requested
release ID, release receipt, transform, alignment, availability, or source
receipt, the doctor reports `blocked` and downstream integration must stop.
