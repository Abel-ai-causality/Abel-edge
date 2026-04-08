# Plugins Subsystem

Optional integrations. Removing this entire directory must not break anything.
`TestPluginsOptional` enforces this mechanically.

## I want to...

### Use Abel causal discovery
1. Run: `causal-edge discover <TICKER>`
2. Complete browser OAuth if prompted; key is stored in `.env`
3. Use `--mode parents` or `--mode mb` depending on the discovery need
4. Copy the output YAML into your `strategies.yaml`
5. No API key? Fill `parents:` manually — framework works identically

### Align Abel price APIs
- Default real-price source is Abel market data
- See `docs/abel-price-api.md` for the request/response contract
- Abel currently uses the SIT stack for both graph discovery and market data
- OAuth base: `https://api-sit.abel.ai/echo`
- CAP endpoint: `POST https://cap-sit.abel.ai/api/cap`
- Market endpoint: `POST https://cap-sit.abel.ai/api/market/day_bar`

### Understand plugin isolation
- Framework uses `try/except ImportError` to detect plugins, not registry
- No plugin code is imported at framework startup
- Core tests pass with `plugins/` directory deleted

### Build a new plugin (future)
- Create `causal_edge/plugins/<name>/` directory
- Expose capabilities via top-level functions
- Framework discovers via `try/except` import in `causal_edge/cli.py`
- No registry pattern until second plugin exists (YAGNI)
