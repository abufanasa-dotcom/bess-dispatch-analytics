"""Comprehensive verification and physics tests for ex-post MILP optimized dispatch."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.battery_model import BESSConfig
from src.optimized_dispatch import NUMERICAL_TOLERANCE, simulate_optimized, solve_day_milp

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRICES_CSV = PROJECT_ROOT / "data" / "processed" / "de_lu_day_ahead_prices_2024.csv"
BASELINE_CSV = PROJECT_ROOT / "reports" / "baseline_dispatch_2024.csv"
BASELINE_SUMMARY_JSON = PROJECT_ROOT / "reports" / "baseline_summary_2024.json"
OPTIMIZED_CSV = PROJECT_ROOT / "reports" / "optimized_dispatch_2024.csv"
OPTIMIZED_SUMMARY_JSON = PROJECT_ROOT / "reports" / "optimized_summary_2024.json"
DAILY_COMP_CSV = PROJECT_ROOT / "reports" / "baseline_vs_optimized_daily_2024.csv"

EXPECTED_ROW_COUNT = 8784
EXPECTED_DELIVERY_DAYS = 366


@pytest.fixture(scope="module")
def input_prices_df() -> pd.DataFrame:
    """Fixture providing input validated prices dataset."""
    assert PRICES_CSV.exists(), f"Prices CSV missing at {PRICES_CSV}"
    return pd.read_csv(PRICES_CSV)


@pytest.fixture(scope="module")
def baseline_df() -> pd.DataFrame:
    """Fixture providing baseline dispatch dataset."""
    assert BASELINE_CSV.exists(), f"Baseline CSV missing at {BASELINE_CSV}"
    return pd.read_csv(BASELINE_CSV)


@pytest.fixture(scope="module")
def optimized_df() -> pd.DataFrame:
    """Fixture providing generated optimized dispatch dataset."""
    assert OPTIMIZED_CSV.exists(), f"Optimized CSV missing at {OPTIMIZED_CSV}"
    return pd.read_csv(OPTIMIZED_CSV)


@pytest.fixture(scope="module")
def summary_data() -> dict:
    """Fixture providing generated optimized summary JSON."""
    assert OPTIMIZED_SUMMARY_JSON.exists(), f"Summary JSON missing at {OPTIMIZED_SUMMARY_JSON}"
    with open(OPTIMIZED_SUMMARY_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def daily_comp_df() -> pd.DataFrame:
    """Fixture providing baseline vs optimized daily comparison dataset."""
    assert DAILY_COMP_CSV.exists(), f"Daily comparison CSV missing at {DAILY_COMP_CSV}"
    return pd.read_csv(DAILY_COMP_CSV)


# 1. Output row count
def test_01_optimized_output_rows_count(optimized_df: pd.DataFrame):
    """1. Verify optimized output contains exactly 8,784 rows."""
    assert len(optimized_df) == EXPECTED_ROW_COUNT


# 2. Exactly 366 delivery dates
def test_02_exactly_366_delivery_dates(optimized_df: pd.DataFrame):
    """2. Verify exactly 366 unique delivery dates exist."""
    assert optimized_df["delivery_date"].nunique() == EXPECTED_DELIVERY_DAYS


# 3. March 31 has 23 rows
def test_03_march_31_contains_23_rows(optimized_df: pd.DataFrame):
    """3. Verify spring DST transition (2024-03-31) contains exactly 23 rows."""
    m31 = optimized_df[optimized_df["delivery_date"] == "2024-03-31"]
    assert len(m31) == 23


# 4. October 27 has 25 rows
def test_04_october_27_contains_25_rows(optimized_df: pd.DataFrame):
    """4. Verify autumn DST transition (2024-10-27) contains exactly 25 rows."""
    o27 = optimized_df[optimized_df["delivery_date"] == "2024-10-27"]
    assert len(o27) == 25


# 5. All 366 daily solves succeed
def test_05_all_366_daily_solves_succeed(summary_data: dict):
    """5. Verify all 366 daily solves succeeded with 0 failures."""
    assert summary_data["optimized_days_successful"] == EXPECTED_DELIVERY_DAYS
    assert summary_data["optimized_days_failed"] == 0


# 6. Prices unchanged from source dataset
def test_06_prices_unchanged_from_source(optimized_df: pd.DataFrame, input_prices_df: pd.DataFrame):
    """6. Verify electricity prices match the validated source dataset exactly."""
    pd.testing.assert_series_equal(optimized_df["price_eur_per_mwh"], input_prices_df["price_eur_per_mwh"])


# 7. Negative prices preserved
def test_07_negative_prices_preserved(optimized_df: pd.DataFrame, input_prices_df: pd.DataFrame):
    """7. Verify negative prices are preserved and unclipped."""
    neg_input = input_prices_df[input_prices_df["price_eur_per_mwh"] < 0]
    neg_opt = optimized_df[optimized_df["price_eur_per_mwh"] < 0]
    assert len(neg_opt) == len(neg_input) == 457
    assert optimized_df["price_eur_per_mwh"].min() == pytest.approx(-135.45)


# 8. No simultaneous charging and discharging
def test_08_no_simultaneous_charging_and_discharging(optimized_df: pd.DataFrame):
    """8. Verify strict mutual exclusivity between charging and discharging."""
    simultaneous = (
        (optimized_df["optimized_charge_power_mw"] > NUMERICAL_TOLERANCE)
        & (optimized_df["optimized_discharge_power_mw"] > NUMERICAL_TOLERANCE)
    )
    assert not simultaneous.any()


# 9. Charge power <= rated/grid limits
def test_09_charge_power_within_limits(optimized_df: pd.DataFrame):
    """9. Verify optimized charge power does not exceed rated 1.0 MW limit."""
    assert (optimized_df["optimized_charge_power_mw"] >= 0.0).all()
    assert (optimized_df["optimized_charge_power_mw"] <= 1.0 + NUMERICAL_TOLERANCE).all()


# 10. Discharge power <= rated/grid limits
def test_10_discharge_power_within_limits(optimized_df: pd.DataFrame):
    """10. Verify optimized discharge power does not exceed rated 1.0 MW limit."""
    assert (optimized_df["optimized_discharge_power_mw"] >= 0.0).all()
    assert (optimized_df["optimized_discharge_power_mw"] <= 1.0 + NUMERICAL_TOLERANCE).all()


# 11. Energy never below 0.2 MWh
def test_11_energy_never_below_minimum(optimized_df: pd.DataFrame):
    """11. Verify stored cell energy never falls below E_min = 0.2 MWh."""
    assert (optimized_df["energy_after_mwh"] >= 0.2 - NUMERICAL_TOLERANCE).all()


# 12. Energy never above 1.8 MWh
def test_12_energy_never_above_maximum(optimized_df: pd.DataFrame):
    """12. Verify stored cell energy never exceeds E_max = 1.8 MWh."""
    assert (optimized_df["energy_after_mwh"] <= 1.8 + NUMERICAL_TOLERANCE).all()


# 13. SOC never below 0.10
def test_13_soc_never_below_minimum(optimized_df: pd.DataFrame):
    """13. Verify SOC never drops below soc_min = 0.10."""
    assert (optimized_df["soc_after"] >= 0.10 - 1e-6).all()


# 14. SOC never above 0.90
def test_14_soc_never_above_maximum(optimized_df: pd.DataFrame):
    """14. Verify SOC never exceeds soc_max = 0.90."""
    assert (optimized_df["soc_after"] <= 0.90 + 1e-6).all()


# 15. Every day starts near SOC 0.50
def test_15_every_day_starts_near_0_50_soc(optimized_df: pd.DataFrame):
    """15. Verify every delivery day starts at approximately 0.50 SOC."""
    first_hours = optimized_df.groupby("delivery_date").first()
    assert np.allclose(first_hours["soc_before"], 0.50, atol=1e-5)


# 16. Every day ends near SOC 0.50
def test_16_every_day_ends_near_0_50_soc(optimized_df: pd.DataFrame):
    """16. Verify every delivery day ends at approximately 0.50 SOC."""
    last_hours = optimized_df.groupby("delivery_date").last()
    assert np.allclose(last_hours["soc_after"], 0.50, atol=1e-5)


# 17. Annual final SOC near 0.50
def test_17_annual_final_soc_near_0_50(optimized_df: pd.DataFrame):
    """17. Verify final annual SOC is approximately 0.50."""
    assert optimized_df["soc_after"].iloc[-1] == pytest.approx(0.50, abs=1e-5)


# 18. MILP energy balance equation holds
def test_18_milp_energy_balance_equation(optimized_df: pd.DataFrame):
    """18. Verify MILP energy balance equation holds across all hours."""
    # e_after[t] = e_before[t] + p_ch*eta_ch*dt - p_dis/eta_dis*dt
    expected_e = (
        optimized_df["energy_before_mwh"]
        + optimized_df["optimized_charge_power_mw"] * 0.95 * 1.0
        - (optimized_df["optimized_discharge_power_mw"] / 0.95) * 1.0
    )
    assert np.allclose(optimized_df["solver_energy_after_mwh"], expected_e, atol=1e-7)


# 19. Physical replay energy balance holds
def test_19_physical_replay_energy_balance(optimized_df: pd.DataFrame):
    """19. Verify physical replay energy balance holds exactly."""
    expected_e = (
        optimized_df["energy_before_mwh"]
        + optimized_df["cell_charge_energy_mwh"]
        - optimized_df["cell_discharge_energy_mwh"]
    )
    assert np.allclose(optimized_df["energy_after_mwh"], expected_e, atol=1e-7)


# 20. Optimized schedule does not require material BatteryModel clipping
def test_20_no_material_battery_model_clipping(optimized_df: pd.DataFrame):
    """20. Verify BatteryModel replayed powers match requested powers without clipping."""
    diff_ch = np.abs(optimized_df["optimized_charge_power_mw"] - (optimized_df["grid_charge_energy_mwh"] / 1.0))
    diff_dis = np.abs(optimized_df["optimized_discharge_power_mw"] - (optimized_df["grid_discharge_energy_mwh"] / 1.0))
    assert np.max(diff_ch) < NUMERICAL_TOLERANCE
    assert np.max(diff_dis) < NUMERICAL_TOLERANCE


# 21. Solver energy approximately equals replay energy
def test_21_solver_energy_equals_replay_energy(optimized_df: pd.DataFrame):
    """21. Verify solver-predicted stored energy matches physical replayed stored energy."""
    assert np.allclose(optimized_df["solver_energy_after_mwh"], optimized_df["energy_after_mwh"], atol=1e-6)


# 22. Maximum solver/replay energy difference below tolerance
def test_22_max_solver_replay_energy_difference_below_tolerance(summary_data: dict):
    """22. Verify maximum solver/replay energy difference is below tolerance."""
    assert summary_data["maximum_solver_replay_energy_difference_mwh"] < 1e-6


# 23. Financial arithmetic is correct per hour
def test_23_hourly_financial_arithmetic(optimized_df: pd.DataFrame):
    """23. Verify hourly financial formulas: cost = grid_ch * price, rev = grid_dis * price, margin = rev - cost."""
    expected_cost = optimized_df["grid_charge_energy_mwh"] * optimized_df["price_eur_per_mwh"]
    expected_rev = optimized_df["grid_discharge_energy_mwh"] * optimized_df["price_eur_per_mwh"]
    expected_margin = expected_rev - expected_cost
    assert np.allclose(optimized_df["charging_cost_eur"], expected_cost, atol=1e-7)
    assert np.allclose(optimized_df["discharge_revenue_eur"], expected_rev, atol=1e-7)
    assert np.allclose(optimized_df["gross_margin_eur"], expected_margin, atol=1e-7)


# 24. Annual financial totals equal hourly sums
def test_24_annual_financial_totals_equal_hourly_sums(optimized_df: pd.DataFrame, summary_data: dict):
    """24. Verify annual summary financial totals equal exact sums of hourly columns."""
    assert summary_data["total_charging_cost_eur"] == pytest.approx(optimized_df["charging_cost_eur"].sum(), abs=1e-5)
    assert summary_data["total_discharge_revenue_eur"] == pytest.approx(optimized_df["discharge_revenue_eur"].sum(), abs=1e-5)
    assert summary_data["gross_arbitrage_margin_eur"] == pytest.approx(optimized_df["gross_margin_eur"].sum(), abs=1e-5)


# 25. MILP objective agrees with replayed margin
def test_25_milp_objective_agrees_with_replayed_margin(summary_data: dict):
    """25. Verify MILP solver objective agrees with replayed gross margin within tolerance."""
    diff = summary_data["objective_replay_difference_eur"]
    assert diff < 1e-5
    assert summary_data["milp_objective_margin_eur"] == pytest.approx(summary_data["replayed_margin_eur"], abs=1e-5)


# 26. Throughput arithmetic correct
def test_26_throughput_arithmetic(optimized_df: pd.DataFrame):
    """26. Verify cell throughput arithmetic: throughput = cell_ch + cell_dis."""
    expected_tp = optimized_df["cell_charge_energy_mwh"] + optimized_df["cell_discharge_energy_mwh"]
    assert np.allclose(optimized_df["cell_throughput_mwh"], expected_tp, atol=1e-7)


# 27. EFC arithmetic correct
def test_27_efc_arithmetic(optimized_df: pd.DataFrame):
    """27. Verify incremental EFC arithmetic: EFC = throughput / (2 * E_nom)."""
    expected_efc = optimized_df["cell_throughput_mwh"] / (2.0 * 2.0)
    assert np.allclose(optimized_df["incremental_efc"], expected_efc, atol=1e-7)


# 28. Realized round-trip efficiency physically consistent
def test_28_realized_round_trip_efficiency(summary_data: dict):
    """28. Verify realized RTE equals nominal RTE (0.9025) because initial SOC == final SOC."""
    expected_rte = 0.95 * 0.95
    assert summary_data["realized_round_trip_efficiency"] == pytest.approx(expected_rte, rel=1e-5)


# 29. Every optimized day margin >= baseline day margin within tolerance
def test_29_every_optimized_day_margin_ge_baseline(daily_comp_df: pd.DataFrame):
    """29. Verify for EVERY delivery date: optimized margin >= baseline margin."""
    diff = daily_comp_df["optimized_margin_eur"] - daily_comp_df["baseline_margin_eur"]
    assert (diff >= -1e-6).all()
    # Also verify absolute improvement column
    assert (daily_comp_df["absolute_improvement_eur"] >= -1e-6).all()


# 30. Annual optimized margin >= baseline annual margin
def test_30_annual_optimized_margin_ge_baseline(summary_data: dict):
    """30. Verify annual optimized gross margin strictly exceeds baseline margin."""
    with open(BASELINE_SUMMARY_JSON, "r", encoding="utf-8") as f:
        baseline_summary = json.load(f)
    assert summary_data["gross_arbitrage_margin_eur"] > baseline_summary["gross_arbitrage_margin_eur"]


# 31. Deterministic repeat execution produces equivalent results
def test_31_deterministic_repeat_execution(input_prices_df: pd.DataFrame, optimized_df: pd.DataFrame):
    """31. Verify re-running optimization produces identical results."""
    # Test on a subset of 3 distinct dates (standard day, spring DST, autumn DST)
    sample_dates = ["2024-01-15", "2024-03-31", "2024-10-27"]
    sample_prices = input_prices_df[input_prices_df["delivery_date"].isin(sample_dates)]
    df_rep, _, _ = simulate_optimized(sample_prices)

    df_orig = optimized_df[optimized_df["delivery_date"].isin(sample_dates)].reset_index(drop=True)
    pd.testing.assert_frame_equal(df_rep, df_orig)


# 32. Solver status checked and successful
def test_32_solver_status_success(input_prices_df: pd.DataFrame):
    """32. Verify solve_day_milp returns status 0 (optimal) and non-empty output."""
    day_df = input_prices_df[input_prices_df["delivery_date"] == "2024-01-01"]
    sol = solve_day_milp(day_df["price_eur_per_mwh"].to_numpy(dtype=float), BESSConfig(), "2024-01-01")
    assert sol["solver_status"] == 0
    assert "optimal" in sol["solver_message"].lower() or "terminated successfully" in sol["solver_message"].lower()


# 33. Binary operating-state values valid
def test_33_binary_operating_states_valid(optimized_df: pd.DataFrame):
    """33. Verify binary operating mode indicators are strictly in {0, 1}."""
    assert set(optimized_df["charge_binary"].unique()).issubset({0, 1})
    assert set(optimized_df["discharge_binary"].unique()).issubset({0, 1})
    # And binary sum <= 1
    assert ((optimized_df["charge_binary"] + optimized_df["discharge_binary"]) <= 1).all()


# 34. Charge/discharge binary linkage valid
def test_34_binary_linkage_valid(optimized_df: pd.DataFrame):
    """34. Verify positive power flows only occur when corresponding binary is 1."""
    charging = optimized_df["optimized_charge_power_mw"] > NUMERICAL_TOLERANCE
    assert (optimized_df.loc[charging, "charge_binary"] == 1).all()

    discharging = optimized_df["optimized_discharge_power_mw"] > NUMERICAL_TOLERANCE
    assert (optimized_df.loc[discharging, "discharge_binary"] == 1).all()


# 35. Terminal equality enforced on 23-hour DST day
def test_35_terminal_equality_spring_dst(optimized_df: pd.DataFrame):
    """35. Verify terminal energy equals 1.0 MWh on 23-hour DST day (2024-03-31)."""
    m31 = optimized_df[optimized_df["delivery_date"] == "2024-03-31"]
    assert len(m31) == 23
    assert m31["energy_after_mwh"].iloc[-1] == pytest.approx(1.0, abs=1e-5)
    assert m31["soc_after"].iloc[-1] == pytest.approx(0.50, abs=1e-5)


# 36. Terminal equality enforced on 25-hour DST day
def test_36_terminal_equality_autumn_dst(optimized_df: pd.DataFrame):
    """36. Verify terminal energy equals 1.0 MWh on 25-hour DST day (2024-10-27)."""
    o27 = optimized_df[optimized_df["delivery_date"] == "2024-10-27"]
    assert len(o27) == 25
    assert o27["energy_after_mwh"].iloc[-1] == pytest.approx(1.0, abs=1e-5)
    assert o27["soc_after"].iloc[-1] == pytest.approx(0.50, abs=1e-5)


# 37. Summary JSON agrees with hourly output
def test_37_summary_agrees_with_hourly_output(optimized_df: pd.DataFrame, summary_data: dict):
    """37. Verify summary JSON KPI metrics agree with hourly dataframe metrics."""
    assert summary_data["total_grid_charge_energy_mwh"] == pytest.approx(optimized_df["grid_charge_energy_mwh"].sum(), abs=1e-5)
    assert summary_data["total_grid_discharge_energy_mwh"] == pytest.approx(optimized_df["grid_discharge_energy_mwh"].sum(), abs=1e-5)
    assert summary_data["total_cell_throughput_mwh"] == pytest.approx(optimized_df["cell_throughput_mwh"].sum(), abs=1e-5)
    assert summary_data["equivalent_full_cycles"] == pytest.approx(optimized_df["incremental_efc"].sum(), abs=1e-5)


# 38. Daily comparison file has exactly 366 rows
def test_38_daily_comparison_file_rows(daily_comp_df: pd.DataFrame):
    """38. Verify daily comparison file contains exactly 366 rows."""
    assert len(daily_comp_df) == EXPECTED_DELIVERY_DAYS
    assert (daily_comp_df["hours_in_day"].isin([23, 24, 25])).all()
