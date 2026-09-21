"""
Tests for Step 9: analysis reporting, visualizations, and portfolio findings.

Covers all 20 required verification points:
1. all five figures are created
2. files are non-empty
3. monthly table contains exactly 12 months
4. monthly gross margin sums to nominal annual gross margin
5. monthly degradation cost sums to nominal annual degradation cost
6. monthly net margin sums to nominal annual net margin
7. monthly EFC sums to nominal annual EFC
8. monthly grid charge energy sums to nominal annual grid charge energy
9. monthly grid discharge energy sums to nominal annual grid discharge energy
10. sensitivity table contains exactly four scenarios
11. scenario rates are exactly 0, 10, 20, 30
12. nominal 20 EUR scenario is correctly identified
13. report includes perfect-foresight limitation
14. report includes degradation-proxy limitation
15. report does not claim electrochemical SOH prediction
16. report uses "EFC reduction" rather than "wear reduction"
17. representative day is derived from maximum nominal daily net margin
18. representative day data exactly matches the saved nominal hourly output
19. annual headline values in the report agree with saved JSON/CSV outputs
20. repeated analysis generation is deterministic
"""

import json
from pathlib import Path
import pytest
import pandas as pd

from src.analysis_report import (
    get_reports_dir,
    load_saved_results,
    aggregate_monthly_nominal,
    compute_daily_comparison_metrics,
    get_representative_day,
    generate_all,
)


@pytest.fixture(scope="module")
def reports_dir() -> Path:
    return get_reports_dir()


@pytest.fixture(scope="module")
def saved_data(reports_dir: Path) -> dict:
    return load_saved_results(reports_dir)


@pytest.fixture(scope="module")
def monthly_df(reports_dir: Path) -> pd.DataFrame:
    csv_path = reports_dir / "monthly_nominal_performance_2024.csv"
    assert csv_path.exists(), "monthly_nominal_performance_2024.csv should exist"
    return pd.read_csv(csv_path)


@pytest.fixture(scope="module")
def report_md_content(reports_dir: Path) -> str:
    md_path = reports_dir / "portfolio_findings.md"
    assert md_path.exists(), "portfolio_findings.md should exist"
    return md_path.read_text(encoding="utf-8")


# 1. All five figures are created
def test_all_five_figures_exist(reports_dir: Path):
    expected_figures = [
        "degradation_sensitivity_margin.png",
        "degradation_sensitivity_efc.png",
        "monthly_nominal_performance.png",
        "baseline_vs_nominal_daily.png",
        "representative_day_dispatch.png",
    ]
    figures_dir = reports_dir / "figures"
    assert figures_dir.exists(), "figures directory must exist"
    for fig_name in expected_figures:
        fig_path = figures_dir / fig_name
        assert fig_path.exists(), f"Figure {fig_name} is missing"


# 2. Files are non-empty
def test_figure_files_are_non_empty(reports_dir: Path):
    expected_figures = [
        "degradation_sensitivity_margin.png",
        "degradation_sensitivity_efc.png",
        "monthly_nominal_performance.png",
        "baseline_vs_nominal_daily.png",
        "representative_day_dispatch.png",
    ]
    figures_dir = reports_dir / "figures"
    for fig_name in expected_figures:
        fig_path = figures_dir / fig_name
        assert fig_path.stat().st_size > 10_000, f"Figure {fig_name} is unexpectedly small or empty"


# 3. Monthly table contains exactly 12 months
def test_monthly_table_contains_twelve_months(monthly_df: pd.DataFrame):
    assert len(monthly_df) == 12
    expected_months = [f"2024-{m:02d}" for m in range(1, 13)]
    assert monthly_df["month"].tolist() == expected_months


# 4. Monthly gross margin sums to nominal annual gross margin
def test_monthly_gross_margin_sums_to_annual(monthly_df: pd.DataFrame, saved_data: dict):
    expected = saved_data["deg_summary_20"]["gross_arbitrage_margin_eur"]
    assert monthly_df["gross_margin_eur"].sum() == pytest.approx(expected, rel=1e-5)


# 5. Monthly degradation cost sums to nominal annual degradation cost
def test_monthly_degradation_cost_sums_to_annual(monthly_df: pd.DataFrame, saved_data: dict):
    expected = saved_data["deg_summary_20"]["assumed_degradation_cost_eur"]
    assert monthly_df["degradation_cost_eur"].sum() == pytest.approx(expected, rel=1e-5)


# 6. Monthly net margin sums to nominal annual net margin
def test_monthly_net_margin_sums_to_annual(monthly_df: pd.DataFrame, saved_data: dict):
    expected = saved_data["deg_summary_20"]["net_margin_after_degradation_eur"]
    assert monthly_df["net_margin_eur"].sum() == pytest.approx(expected, rel=1e-5)


# 7. Monthly EFC sums to nominal annual EFC
def test_monthly_efc_sums_to_annual(monthly_df: pd.DataFrame, saved_data: dict):
    expected = saved_data["deg_summary_20"]["equivalent_full_cycles"]
    assert monthly_df["equivalent_full_cycles"].sum() == pytest.approx(expected, rel=1e-5)


# 8. Monthly grid charge energy sums to nominal annual grid charge energy
def test_monthly_grid_charge_energy_sums_to_annual(monthly_df: pd.DataFrame, saved_data: dict):
    expected = saved_data["deg_summary_20"]["grid_charge_energy_mwh"]
    assert monthly_df["grid_charge_energy_mwh"].sum() == pytest.approx(expected, rel=1e-5)


# 9. Monthly grid discharge energy sums to nominal annual grid discharge energy
def test_monthly_grid_discharge_energy_sums_to_annual(monthly_df: pd.DataFrame, saved_data: dict):
    expected = saved_data["deg_summary_20"]["grid_discharge_energy_mwh"]
    assert monthly_df["grid_discharge_energy_mwh"].sum() == pytest.approx(expected, rel=1e-5)


# 10. Sensitivity table contains exactly four scenarios
def test_sensitivity_table_contains_four_scenarios(saved_data: dict):
    df_sens = saved_data["df_sensitivity"]
    assert len(df_sens) == 4


# 11. Scenario rates are exactly 0, 10, 20, 30
def test_sensitivity_table_scenario_rates(saved_data: dict):
    df_sens = saved_data["df_sensitivity"]
    rates = sorted(df_sens["degradation_cost_rate_eur_per_mwh_eq_cycle"].tolist())
    assert rates == [0.0, 10.0, 20.0, 30.0]


# 12. Nominal 20 EUR scenario is correctly identified
def test_nominal_20eur_scenario_identified(saved_data: dict):
    df_sens = saved_data["df_sensitivity"]
    row_20 = df_sens[df_sens["degradation_cost_rate_eur_per_mwh_eq_cycle"] == 20.0]
    assert len(row_20) == 1
    deg_summary_20 = saved_data["deg_summary_20"]
    assert row_20["gross_arbitrage_margin_eur"].iloc[0] == pytest.approx(deg_summary_20["gross_arbitrage_margin_eur"], rel=1e-5)
    assert row_20["net_margin_after_degradation_eur"].iloc[0] == pytest.approx(deg_summary_20["net_margin_after_degradation_eur"], rel=1e-5)
    assert row_20["equivalent_full_cycles"].iloc[0] == pytest.approx(deg_summary_20["equivalent_full_cycles"], rel=1e-5)


# 13. Report includes perfect-foresight limitation
def test_report_includes_perfect_foresight_limitation(report_md_content: str):
    assert "perfect foresight" in report_md_content.lower()


# 14. Report includes degradation-proxy limitation
def test_report_includes_degradation_proxy_limitation(report_md_content: str):
    assert "degradation proxy" in report_md_content.lower() or "simplified economic degradation proxy" in report_md_content.lower()


# 15. Report does not claim electrochemical SOH prediction
def test_report_does_not_claim_electrochemical_soh(report_md_content: str):
    lower = report_md_content.lower()
    assert "no electrochemical soh model" in lower
    assert "does not simulate sei layer growth" in lower or "does not represent electrochemical" in lower


# 16. Report uses "EFC reduction" rather than "wear reduction"
def test_report_uses_efc_reduction_not_wear_reduction(report_md_content: str):
    assert "wear reduction" not in report_md_content.lower()
    assert "efc reduction" in report_md_content.lower() or "reduction in modeled cycling" in report_md_content.lower()


# 17. Representative day is derived from maximum nominal daily net margin
def test_representative_day_is_derived_from_max_net_margin(saved_data: dict):
    df_daily = saved_data["df_daily_20"]
    df_hourly = saved_data["df_hourly_20"]
    top_series, hourly_day = get_representative_day(df_daily, df_hourly)

    expected_idx = df_daily["optimized_net_margin_eur"].idxmax()
    expected_date = df_daily.loc[expected_idx, "delivery_date"]
    expected_margin = df_daily.loc[expected_idx, "optimized_net_margin_eur"]

    assert top_series["delivery_date"] == expected_date
    assert top_series["optimized_net_margin_eur"] == expected_margin
    assert top_series["delivery_date"] == "2024-12-12"


# 18. Representative day data exactly matches saved nominal hourly output
def test_representative_day_hourly_data_matches_saved_output(saved_data: dict):
    df_daily = saved_data["df_daily_20"]
    df_hourly = saved_data["df_hourly_20"]
    top_series, hourly_day = get_representative_day(df_daily, df_hourly)

    date = top_series["delivery_date"]
    expected_hourly = df_hourly[df_hourly["delivery_date"] == date].reset_index(drop=True)

    assert len(hourly_day) == len(expected_hourly)
    pd.testing.assert_frame_equal(hourly_day, expected_hourly)


# 19. Annual headline values in report agree with saved JSON/CSV outputs
def test_annual_headline_values_agree_with_saved_outputs(report_md_content: str, saved_data: dict):
    b_summary = saved_data["baseline_summary"]
    opt_summary = saved_data["optimized_summary"]
    deg_20 = saved_data["deg_summary_20"]

    # Verify formatted baseline values are in report
    assert f"€{b_summary['gross_arbitrage_margin_eur']:,.2f}" in report_md_content
    assert f"{b_summary['equivalent_full_cycles']:.2f} EFC" in report_md_content

    # Verify Step 7 optimized values
    assert f"€{opt_summary['gross_arbitrage_margin_eur']:,.2f}" in report_md_content
    assert f"{opt_summary['equivalent_full_cycles']:.2f} EFC" in report_md_content

    # Verify nominal 20 EUR values
    assert f"€{deg_20['gross_arbitrage_margin_eur']:,.2f}" in report_md_content
    assert f"€{deg_20['net_margin_after_degradation_eur']:,.2f}" in report_md_content
    assert f"{deg_20['equivalent_full_cycles']:.2f} EFC" in report_md_content
    assert f"€{deg_20['assumed_degradation_cost_eur']:,.2f}" in report_md_content


# 20. Repeated analysis generation is deterministic
def test_repeated_generation_is_deterministic(reports_dir: Path):
    result1 = generate_all(reports_dir)
    csv_bytes_1 = (reports_dir / "monthly_nominal_performance_2024.csv").read_bytes()
    md_text_1 = (reports_dir / "portfolio_findings.md").read_text(encoding="utf-8")

    result2 = generate_all(reports_dir)
    csv_bytes_2 = (reports_dir / "monthly_nominal_performance_2024.csv").read_bytes()
    md_text_2 = (reports_dir / "portfolio_findings.md").read_text(encoding="utf-8")

    assert csv_bytes_1 == csv_bytes_2, "Monthly CSV should be deterministic across runs"
    assert md_text_1 == md_text_2, "Markdown report should be deterministic across runs"
