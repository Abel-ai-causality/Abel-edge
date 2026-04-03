"""CLI entry point tests."""

from pathlib import Path

from click.testing import CliRunner

from causal_edge.cli import main


def test_help():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "causal-edge" in result.output


def test_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_status_empty():
    """Status with empty strategies.yaml should show 0 strategies."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("strategies.yaml").write_text("settings: {}\nstrategies: []\n", encoding="utf-8")
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "Strategies: 0" in result.output


def test_init_creates_project(tmp_path):
    """init should create a project directory with expected files."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["init", "myproject"])
        assert result.exit_code == 0, result.output
        root = Path("myproject")
        assert root.is_dir()
        assert (root / "strategies.yaml").exists()
        assert (root / "strategies" / "sma_crossover" / "engine.py").exists()
        assert (root / "strategies" / "sma_crossover" / "__init__.py").exists()
        assert (root / "data").is_dir()
        assert (root / ".env.example").exists()
        assert (root / "CLAUDE.md").exists()
        assert (root / "AGENTS.md").exists()


def test_init_fails_if_dir_exists(tmp_path):
    """init should fail with a clear error if the directory already exists."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(main, ["init", "myproject"])
        result = runner.invoke(main, ["init", "myproject"])
        assert result.exit_code != 0
        assert "already exists" in result.output


def test_run_empty():
    """Run with no strategies should print message, not crash."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("strategies.yaml").write_text("settings: {}\nstrategies: []\n", encoding="utf-8")
        result = runner.invoke(main, ["run"])
        assert result.exit_code == 0
        assert "No strategies" in result.output


def test_dashboard_empty():
    """Dashboard with no strategies should generate HTML without error."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        # Create minimal strategies.yaml
        Path("strategies.yaml").write_text("settings: {}\nstrategies: []\n", encoding="utf-8")
        result = runner.invoke(main, ["dashboard"])
        assert result.exit_code == 0
        assert Path("dashboard.html").exists()


def test_validate_empty():
    """Validate with no strategies should print message, not crash."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("strategies.yaml").write_text("settings: {}\nstrategies: []\n", encoding="utf-8")
        result = runner.invoke(main, ["validate"])
        assert result.exit_code == 0
        assert "No strategies" in result.output


def test_discover_ethusd_parents(monkeypatch, tmp_path):
    class StubClient:
        def ensure_api_key(self, *, env_path=".env"):
            assert env_path == ".env"
            return "abel_test"

        def discover_parents(self, *, node_id, limit, api_key):
            assert node_id == "ETHUSD"
            assert limit == 20
            assert api_key == "abel_test"
            return [{"node_id": "BTCUSD.price"}, {"node_id": "SOLUSD.price"}]

    from causal_edge.plugins.abel import discover as discover_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discover_module, "AbelClient", StubClient)
    result = CliRunner().invoke(main, ["discover", "ETHUSD", "--limit", "50"])
    assert result.exit_code == 0, result.output
    assert "parents:" in result.output
    assert "ticker: BTCUSD" in result.output
    assert "field: price" in result.output


def test_discover_ethusd_markov_blanket(monkeypatch, tmp_path):
    class StubClient:
        def ensure_api_key(self, *, env_path=".env"):
            return "abel_test"

        def markov_blanket(self, *, node_id, limit, api_key):
            assert node_id == "ETHUSD"
            assert limit == 12
            return [
                {"node_id": "BTCUSD.price", "roles": ["parent"]},
                {"node_id": "SOLUSD.price", "roles": ["spouse"]},
            ]

    from causal_edge.plugins.abel import discover as discover_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discover_module, "AbelClient", StubClient)
    result = CliRunner().invoke(main, ["discover", "ETHUSD", "--mode", "mb", "--limit", "12"])
    assert result.exit_code == 0, result.output
    assert "markov_blanket:" in result.output
    assert "roles: [parent]" in result.output
    assert "roles: [spouse]" in result.output
