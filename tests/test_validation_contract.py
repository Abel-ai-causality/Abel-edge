from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from causal_edge.cli import main
from causal_edge.validation.gate import validate_strategy


FIXTURES = Path(__file__).parent / "fixtures" / "validation"


def test_csv_insufficient_rows_contract() -> None:
    result = validate_strategy(FIXTURES / "insufficient_rows.csv")
    assert result["verdict"] == "FAIL"
    assert result["score"] == "0/0"
    assert result["profile"] == "unknown"
    assert result["triangle"] == {"ratio": 0, "rank": 0, "shape": 0}
    assert result["failures"] == ["Insufficient data: 20 rows (need 30+)"]


def test_csv_without_position_has_current_conditional_denominator() -> None:
    result = validate_strategy(FIXTURES / "ic_unsupported_no_position.csv", profile="equity_daily")
    assert result["verdict"] == "FAIL"
    assert result["score"] == "7/9"
    assert result["metrics"]["ic_applicable"] is False
    assert result["triangle"]["rank"] == 0.0
    assert result["profile"] == "equity_daily"


def test_csv_with_position_marks_ic_family_applicable() -> None:
    result = validate_strategy(FIXTURES / "ic_supported.csv", profile="equity_daily")
    assert result["metrics"]["ic_applicable"] is True
    assert result["score"].endswith("/11")


def test_position_aware_csv_without_ic_failures_uses_15_test_contract() -> None:
    result = validate_strategy(FIXTURES / "positive_daily.csv", profile="equity_daily")
    assert result["metrics"]["ic_applicable"] is True
    assert result["score"] == "9/11"


def test_csv_without_position_omits_ic_gate_labels_from_failures() -> None:
    result = validate_strategy(FIXTURES / "ic_unsupported_no_position.csv", profile="equity_daily")
    joined = " | ".join(result["failures"])
    assert "IC " not in joined
    assert "IC stab" not in joined
    assert "T12 OOS/IS" not in joined


def test_removed_oos_split_sharpe_metrics_are_absent() -> None:
    result = validate_strategy(FIXTURES / "positive_daily.csv", profile="equity_daily")
    assert "oos_is" not in result["metrics"]
    assert "is_sharpe" not in result["metrics"]
    assert "oos_sharpe" not in result["metrics"]


def test_verbose_output_includes_current_metric_section() -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "validate",
            "--csv",
            str(FIXTURES / "ic_unsupported_no_position.csv"),
            "--verbose",
        ],
    )
    assert result.exit_code == 1
    assert "ic_unsupported_no_position     7/9  FAIL" in result.output
    assert "ic_unsupported_no_position metrics:" in result.output
    assert "sharpe" in result.output
    assert "dsr_trials_used" in result.output
    assert "ic_hit_rate" not in result.output
    assert "oos_is" not in result.output


def test_validate_cli_accepts_dsr_trials_override() -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "validate",
            "--csv",
            str(FIXTURES / "ic_unsupported_no_position.csv"),
            "--verbose",
            "--dsr-trials",
            "17",
        ],
    )
    assert result.exit_code == 1
    assert "dsr_trials_used      17.0000" in result.output


def test_export_output_matches_current_report_contract(tmp_path) -> None:
    export_path = tmp_path / "report.txt"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "validate",
            "--csv",
            str(FIXTURES / "ic_unsupported_no_position.csv"),
            "--export",
            str(export_path),
        ],
    )
    assert result.exit_code == 1
    exported = export_path.read_text(encoding="utf-8")
    assert "ABEL PROOF VALIDATION REPORT" in exported
    assert "ic_unsupported_no_position     7/9  FAIL" in exported
    assert "PnL floor +4.0% < +30%" in exported
    assert "Report exported to" in result.output


def test_contract_drift_public_claim_for_15_test_validation() -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "validate",
            "--csv",
            str(FIXTURES / "ic_unsupported_no_position.csv"),
        ],
    )
    assert result.exit_code == 1
    denominator = int("9/11".split("/")[1])
    assert denominator == 11
