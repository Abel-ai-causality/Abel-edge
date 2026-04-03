"""Command-line interface for causal-edge."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

import click


def _get_version() -> str:
    """Return installed package version, or fall back to source version."""
    try:
        return metadata.version("causal-edge")
    except metadata.PackageNotFoundError:
        return __version__


from causal_edge import __version__


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=_get_version(), prog_name="causal-edge")
def main():
    """causal-edge: Agent-native quant framework."""


@main.command("version")
def version():
    """Show causal-edge version."""
    click.echo(f"causal-edge, version {_get_version()}")


@main.command()
@click.argument("name")
def init(name):
    """Scaffold a new causal-edge project."""
    from causal_edge.scaffold import scaffold_project

    try:
        root = scaffold_project(name)
    except FileExistsError as e:
        raise click.ClickException(str(e))

    click.echo(f"Created {root}/")
    click.echo(f"  strategies.yaml          (3 demo strategies)")
    click.echo(f"  strategies/sma_crossover (simple SMA)")
    click.echo(f"  strategies/momentum_ml   (walk-forward GBDT)")
    click.echo(f"  strategies/causal_demo   (Abel causal graph voting)")
    click.echo(f"  CLAUDE.md + AGENTS.md    (agent harness)")
    click.echo(f"  .env.example             (Abel API key, optional)")
    click.echo(f"")
    click.echo(f"Next:")
    click.echo(f"  cd {name}")
    click.echo(f"  causal-edge run")
    click.echo(f"  causal-edge dashboard")
    click.echo(f"  causal-edge validate")


@main.command()
@click.option("--strategy", default=None, help="Run a specific strategy by ID")
@click.option("--config", default="strategies.yaml", help="Config file path")
def run(strategy, config):
    """Run strategies and write trade logs."""
    from causal_edge.config import load_config
    from causal_edge.engine.trader import run_all

    cfg = load_config(config)
    if not cfg["strategies"]:
        click.echo("No strategies configured. Add strategies to strategies.yaml.")
        return

    click.echo(f"Running {len(cfg['strategies'])} strategies...")
    results = run_all(cfg, strategy_id=strategy)
    click.echo(f"Done. {len(results)} strategies executed.")


@main.command()
@click.option("--config", default="strategies.yaml", help="Config file path")
@click.option("--output", default="dashboard.html", help="Output HTML path")
def dashboard(config, output):
    """Generate dashboard HTML."""
    from causal_edge.dashboard.generator import generate

    generate(config, output)
    click.echo(f"Dashboard generated: {output}")


@main.command()
@click.option("--strategy", default=None, help="Validate a specific strategy by ID")
@click.option("--verbose", is_flag=True, help="Show detailed failure info")
@click.option(
    "--csv", "csv_path", default=None, help="Validate a standalone CSV (date,pnl columns)"
)
@click.option("--export", "export_path", default=None, help="Export report to file")
@click.option("--config", default="strategies.yaml", help="Config file path")
def validate(strategy, verbose, csv_path, export_path, config):
    """Run Abel Proof 15-test validation on strategies."""
    import io
    import sys

    from causal_edge.validation.gate import validate_strategy, print_validation_report

    results = {}

    if csv_path:
        # Quick path: validate a standalone CSV without strategies.yaml
        if not Path(csv_path).exists():
            raise click.ClickException(f"CSV not found: {csv_path}")
        result = validate_strategy(csv_path)
        results[Path(csv_path).stem] = result
    else:
        from causal_edge.config import load_config

        cfg = load_config(config)
        strategies_list = cfg["strategies"]
        if strategy:
            strategies_list = [s for s in strategies_list if s["id"] == strategy]

        if not strategies_list:
            click.echo("No strategies to validate.")
            return

        for s_cfg in strategies_list:
            sid = s_cfg["id"]
            log_path = s_cfg.get("trade_log", "")
            if not Path(log_path).exists():
                results[sid] = {
                    "verdict": "SKIP",
                    "score": "0/0",
                    "failures": [f"Trade log not found: {log_path}. Run 'causal-edge run' first."],
                    "metrics": {},
                    "triangle": {"ratio": 0, "rank": 0, "shape": 0},
                    "profile": "unknown",
                }
                continue
            results[sid] = validate_strategy(log_path)

    # Capture output for --export
    if export_path:
        old_stdout = sys.stdout
        sys.stdout = capture = io.StringIO()

    print_validation_report(results)

    if verbose:
        print()
        for sid, r in results.items():
            if r.get("metrics"):
                print(f"  {sid} metrics:")
                m = r["metrics"]
                for key in (
                    "sharpe",
                    "lo_adjusted",
                    "sortino",
                    "total_pnl",
                    "max_dd",
                    "calmar",
                    "dsr",
                    "pbo",
                    "oos_is",
                    "omega",
                    "ic",
                    "ic_hit_rate",
                ):
                    if key in m:
                        print(f"    {key:20s} {m[key]:.4f}")
                if "yearly_sharpes" in m:
                    print(f"    yearly_sharpes:")
                    for yr, sh in sorted(m["yearly_sharpes"].items()):
                        print(f"      {yr}: {sh:.2f}")

    if export_path:
        sys.stdout = old_stdout
        report_text = capture.getvalue()
        click.echo(report_text, nl=False)  # also print to terminal
        Path(export_path).write_text(report_text, encoding="utf-8")
        click.echo(f"\n  Report exported to {export_path}")

    all_pass = all(r["verdict"] in ("PASS", "SKIP") for r in results.values())
    sys.exit(0 if all_pass else 1)


@main.command()
@click.argument("ticker")
@click.option("--mode", type=click.Choice(["parents", "mb"]), default="parents", show_default=True)
@click.option(
    "--limit",
    default=10,
    show_default=True,
    type=int,
    help="Maximum nodes to return (hard cap 20)",
)
def discover(ticker, mode, limit):
    """Discover causal graph nodes for an asset via Abel API."""
    try:
        from causal_edge.plugins.abel.discover import discover_graph_nodes
    except ImportError:
        raise click.ClickException("Abel plugin not installed. See: causal_edge/plugins/AGENTS.md")
    try:
        output = discover_graph_nodes(ticker, mode=mode, limit=limit)
    except Exception as e:
        raise click.ClickException(str(e))
    click.echo(output)


@main.command()
@click.option("--config", default="strategies.yaml", help="Config file path")
def status(config):
    """Show strategy status summary."""
    from causal_edge.config import load_config

    cfg = load_config(config)
    click.echo(f"Strategies: {len(cfg['strategies'])}")
    for s in cfg["strategies"]:
        click.echo(f"  {s['name']:20s}  {s['asset']:6s}  {s.get('badge', '?')}")


if __name__ == "__main__":
    main()
