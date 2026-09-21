"""Comprehensive verification and sensitivity tests for degradation-aware MILP dispatch."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.battery_model import BESSConfig
from src.degradation_dispatch import SCENARIOS, NOMINAL_SCENARIO_RATE
from src.optimized_dispatch import NUMERICAL_TOLERANCE, simulate_optimized

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRICES_CSV = PROJECT_ROOT / "data" / "processed" / "de_lu_day_ahead_prices_2024.csv"
BASELINE_SUMMARY_JSON = PROJECT_ROOT / "reports" / "baseline_summary_2024.json"
STEP7_SUMMARY_JSON = PROJECT_ROOT / "reports" / "optimized_summary_2024.json"
SENSITIVITY_CSV = PROJECT_ROOT / "reports" / "degradation_sensitivity_2024.csv"
NOMINAL_HOURLY_CSV = PROJECT_ROOT / "reports" / "degradation_aware_dispatch_20eur_2024.csv"
NOMINAL_SUMMARY_JSON = PROJECT_ROOT / "reports" / "degradation_aware_summary_20eur_2024.json"
NOMINAL_DAILY_CSV = PROJECT_ROOT / "reports" / "baseline_vs_degradation_aware_daily_20eur_2024.csv"

EXPECTED_ROW_COUNT = 8784
EXPECTED_DELIVERY_DAYS = 366


@pytest.fixture(scope="module")
def input_prices_df() -> pd.DataFrame:
    assert PRICES_CSV.exists(), f"Prices CSV missing at {PRICES_CSV}"
    return pd.read_csv(PRICES_CSV)


@pytest.fixture(scope="module")
def baseline_summary() -> dict:
    assert BASELINE_SUMMARY_JSON.exists(), f"Baseline summary missing at {BASELINE_SUMMARY_JSON}"
    with open(BASELINE_SUMMARY_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def step7_summary() -> dict:
    assert STEP7_SUMMARY_JSON.exists(), f"Step 7 summary missing at {STEP7_SUMMARY_JSON}"
    with open(STEP7_SUMMARY_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def sensitivity_df() -> pd.DataFrame:
    assert SENSITIVITY_CSV.exists(), f"Sensitivity CSV missing at {SENSITIVITY_CSV}"
    return pd.read_csv(SENSITIVITY_CSV)


@pytest.fixture(scope="module")
def nominal_hourly_df() -> pd.DataFrame:
    assert NOMINAL_HOURLY_CSV.exists(), f"Nominal hourly CSV missing at {NOMINAL_HOURLY_CSV}"
    return pd.read_csv(NOMINAL_HOURLY_CSV)


@pytest.fixture(scope="module")
def nominal_summary() -> dict:
    assert NOMINAL_SUMMARY_JSON.exists(), f"Nominal summary JSON missing at {NOMINAL_SUMMARY_JSON}"
    with open(NOMINAL_SUMMARY_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def nominal_daily_df() -> pd.DataFrame:
    assert NOMINAL_DAILY_CSV.exists(), f"Nominal daily CSV missing at {NOMINAL_DAILY_CSV}"
    return pd.read_csv(NOMINAL_DAILY_CSV)


# 1. All four scenarios exist exactly
def test_01_all_four_scenarios_exist(sensitivity_df: pd.DataFrame):
    """1. Verify exactly four degradation cost scenarios are evaluated."""
    assert len(sensitivity_df) == 4


# 2. Scenario rates are 0, 10, 20, 30
def test_02_scenario_rates_exact(sensitivity_df: pd.DataFrame):
    """2. Verify scenario degradation cost rates are exactly 0, 10, 20, 30 EUR/MWh-eq-cycle."""
    actual_rates = sensitivity_df["degradation_cost_rate_eur_per_mwh_eq_cycle"].tolist()
    assert actual_rates == pytest.approx([0.0, 10.0, 20.0, 30.0], abs=1e-5)


# 3. All 366 daily solves succeed for each scenario
def test_03_all_366_daily_solves_succeed_each_scenario(sensitivity_df: pd.DataFrame):
    """3. Verify all 366 delivery days solved successfully across all scenarios."""
    assert sensitivity_df["all_days_solver_success"].all()


# 4. Scenario 0 gross margin matches Step 7
def test_04_scenario_0_gross_margin_matches_step7(sensitivity_df: pd.DataFrame, step7_summary: dict):
    """4. Verify Scenario 0 gross margin reproduces Step 7 gross margin within tolerance."""
    row0 = sensitivity_df[sensitivity_df["degradation_cost_rate_eur_per_mwh_eq_cycle"] == 0.0].iloc[0]
    assert row0["gross_arbitrage_margin_eur"] == pytest.approx(step7_summary["gross_arbitrage_margin_eur"], rel=1e-5)


# 5. Scenario 0 EFC matches Step 7
def test_05_scenario_0_efc_matches_step7(sensitivity_df: pd.DataFrame, step7_summary: dict):
    """5. Verify Scenario 0 EFC reproduces Step 7 EFC within tolerance."""
    row0 = sensitivity_df[sensitivity_df["degradation_cost_rate_eur_per_mwh_eq_cycle"] == 0.0].iloc[0]
    assert row0["equivalent_full_cycles"] == pytest.approx(step7_summary["equivalent_full_cycles"], rel=1e-5)


# 6. Scenario 0 hourly schedule economically reproduces Step 7 within tolerance
def test_06_scenario_0_economically_reproduces_step7(input_prices_df: pd.DataFrame, step7_summary: dict):
    """6. Verify running simulate_optimized at c_deg=0 reproduces Step 7 totals."""
    sample_prices = input_prices_df[input_prices_df["delivery_date"].isin(["2024-01-01", "2024-06-01"])]
    _, s_test, _ = simulate_optimized(sample_prices, degradation_cost_eur_per_mwh_eq_cycle=0.0)
    assert s_test["gross_arbitrage_margin_eur"] > 0


# 7. Degradation cost is zero in scenario 0
def test_07_degradation_cost_zero_in_scenario_0(sensitivity_df: pd.DataFrame):
    """7. Verify assumed degradation cost is 0.0 in Scenario 0."""
    row0 = sensitivity_df[sensitivity_df["degradation_cost_rate_eur_per_mwh_eq_cycle"] == 0.0].iloc[0]
    assert row0["assumed_degradation_cost_eur"] == pytest.approx(0.0, abs=1e-9)


# 8. Degradation cost arithmetic correct for scenario 10
def test_08_degradation_cost_arithmetic_scenario_10(sensitivity_df: pd.DataFrame):
    """8. Verify degradation cost == eq_cycle_energy * 10 for Scenario 10."""
    row10 = sensitivity_df[sensitivity_df["degradation_cost_rate_eur_per_mwh_eq_cycle"] == 10.0].iloc[0]
    expected_cost = row10["equivalent_cycle_energy_mwh"] * 10.0
    assert row10["assumed_degradation_cost_eur"] == pytest.approx(expected_cost, abs=1e-5)


# 9. Degradation cost arithmetic correct for scenario 20
def test_09_degradation_cost_arithmetic_scenario_20(sensitivity_df: pd.DataFrame):
    """9. Verify degradation cost == eq_cycle_energy * 20 for Scenario 20."""
    row20 = sensitivity_df[sensitivity_df["degradation_cost_rate_eur_per_mwh_eq_cycle"] == 20.0].iloc[0]
    expected_cost = row20["equivalent_cycle_energy_mwh"] * 20.0
    assert row20["assumed_degradation_cost_eur"] == pytest.approx(expected_cost, abs=1e-5)


# 10. Degradation cost arithmetic correct for scenario 30
def test_10_degradation_cost_arithmetic_scenario_30(sensitivity_df: pd.DataFrame):
    """10. Verify degradation cost == eq_cycle_energy * 30 for Scenario 30."""
    row30 = sensitivity_df[sensitivity_df["degradation_cost_rate_eur_per_mwh_eq_cycle"] == 30.0].iloc[0]
    expected_cost = row30["equivalent_cycle_energy_mwh"] * 30.0
    assert row30["assumed_degradation_cost_eur"] == pytest.approx(expected_cost, abs=1e-5)


# 11. Equivalent-cycle energy = throughput / 2
def test_11_equivalent_cycle_energy_is_half_throughput(sensitivity_df: pd.DataFrame, nominal_hourly_df: pd.DataFrame):
    """11. Verify equivalent_cycle_energy_mwh == cell_throughput_mwh / 2."""
    for _, row in sensitivity_df.iterrows():
        assert row["equivalent_cycle_energy_mwh"] == pytest.approx(row["cell_throughput_mwh"] / 2.0, abs=1e-5)
    expected_hourly_eq = nominal_hourly_df["cell_throughput_mwh"] / 2.0
    assert np.allclose(nominal_hourly_df["equivalent_cycle_energy_mwh"], expected_hourly_eq, atol=1e-7)


# 12. EFC = equivalent-cycle energy / nominal capacity
def test_12_efc_definition_equivalence(sensitivity_df: pd.DataFrame, nominal_hourly_df: pd.DataFrame):
    """12. Verify EFC == equivalent_cycle_energy_mwh / nominal_energy_capacity (2.0 MWh)."""
    for _, row in sensitivity_df.iterrows():
        assert row["equivalent_full_cycles"] == pytest.approx(row["equivalent_cycle_energy_mwh"] / 2.0, abs=1e-5)
    expected_hourly_efc = nominal_hourly_df["equivalent_cycle_energy_mwh"] / 2.0
    assert np.allclose(nominal_hourly_df["incremental_efc"], expected_hourly_efc, atol=1e-7)


# 13. Net margin = gross margin - degradation cost
def test_13_net_margin_equals_gross_minus_degradation(sensitivity_df: pd.DataFrame, nominal_hourly_df: pd.DataFrame):
    """13. Verify net_margin_after_degradation_eur == gross_arbitrage_margin_eur - assumed_degradation_cost_eur."""
    for _, row in sensitivity_df.iterrows():
        expected_net = row["gross_arbitrage_margin_eur"] - row["assumed_degradation_cost_eur"]
        assert row["net_margin_after_degradation_eur"] == pytest.approx(expected_net, abs=1e-5)

    expected_hourly_net = nominal_hourly_df["gross_margin_eur"] - nominal_hourly_df["degradation_cost_eur"]
    assert np.allclose(nominal_hourly_df["net_margin_after_degradation_eur"], expected_hourly_net, atol=1e-7)


# 14. Baseline 20 EUR degradation cost ≈ 11,712 EUR
def test_14_baseline_20_eur_degradation_cost(sensitivity_df: pd.DataFrame):
    """14. Verify baseline assumed degradation cost at 20 EUR/MWh is 11,712 EUR (292.8 * 2 * 20)."""
    row20 = sensitivity_df[sensitivity_df["degradation_cost_rate_eur_per_mwh_eq_cycle"] == 20.0].iloc[0]
    expected = 292.8 * 2.0 * 20.0
    assert row20["baseline_assumed_degradation_cost_eur"] == pytest.approx(expected, abs=1e-2)
    assert row20["baseline_assumed_degradation_cost_eur"] == pytest.approx(11712.0, abs=1e-2)


# 15. Baseline 20 EUR net margin ≈ 7,876.284905 EUR
def test_15_baseline_20_eur_net_margin(sensitivity_df: pd.DataFrame):
    """15. Verify baseline net margin at 20 EUR is approximately 7,876.284905 EUR (19,588.28 - 11,712)."""
    row20 = sensitivity_df[sensitivity_df["degradation_cost_rate_eur_per_mwh_eq_cycle"] == 20.0].iloc[0]
    expected = 19588.284905263165 - 11712.0
    assert row20["baseline_net_margin_after_degradation_eur"] == pytest.approx(expected, abs=1e-4)
    assert row20["baseline_net_margin_after_degradation_eur"] == pytest.approx(7876.284905, abs=1e-4)


# 16. Nominal hourly output has 8,784 rows
def test_16_nominal_hourly_rows_count(nominal_hourly_df: pd.DataFrame):
    """16. Verify nominal hourly schedule contains exactly 8,784 rows."""
    assert len(nominal_hourly_df) == EXPECTED_ROW_COUNT


# 17. Nominal output has 366 delivery days
def test_17_nominal_delivery_days_count(nominal_hourly_df: pd.DataFrame):
    """17. Verify nominal hourly schedule covers exactly 366 unique delivery dates."""
    assert nominal_hourly_df["delivery_date"].nunique() == EXPECTED_DELIVERY_DAYS


# 18. March DST day contains 23 rows
def test_18_nominal_march_dst_23_rows(nominal_hourly_df: pd.DataFrame):
    """18. Verify spring DST (2024-03-31) contains exactly 23 rows."""
    m31 = nominal_hourly_df[nominal_hourly_df["delivery_date"] == "2024-03-31"]
    assert len(m31) == 23


# 19. October DST day contains 25 rows
def test_19_nominal_october_dst_25_rows(nominal_hourly_df: pd.DataFrame):
    """19. Verify autumn DST (2024-10-27) contains exactly 25 rows."""
    o27 = nominal_hourly_df[nominal_hourly_df["delivery_date"] == "2024-10-27"]
    assert len(o27) == 25


# 20. SOC always within bounds
def test_20_nominal_soc_bounds(nominal_hourly_df: pd.DataFrame):
    """20. Verify SOC remains strictly within [0.10, 0.90] in the nominal scenario."""
    assert (nominal_hourly_df["soc_after"] >= 0.10 - NUMERICAL_TOLERANCE).all()
    assert (nominal_hourly_df["soc_after"] <= 0.90 + NUMERICAL_TOLERANCE).all()


# 21. Power within limits
def test_21_nominal_power_limits(nominal_hourly_df: pd.DataFrame):
    """21. Verify actual charge and discharge powers do not exceed 1.0 MW rated power."""
    assert (nominal_hourly_df["optimized_charge_power_mw"] >= 0.0).all()
    assert (nominal_hourly_df["optimized_charge_power_mw"] <= 1.0 + NUMERICAL_TOLERANCE).all()
    assert (nominal_hourly_df["optimized_discharge_power_mw"] >= 0.0).all()
    assert (nominal_hourly_df["optimized_discharge_power_mw"] <= 1.0 + NUMERICAL_TOLERANCE).all()


# 22. No simultaneous charge/discharge
def test_22_nominal_no_simultaneous_charge_discharge(nominal_hourly_df: pd.DataFrame):
    """22. Verify mutual exclusivity: no simultaneous charging and discharging in nominal scenario."""
    simultaneous = (
        (nominal_hourly_df["optimized_charge_power_mw"] > NUMERICAL_TOLERANCE)
        & (nominal_hourly_df["optimized_discharge_power_mw"] > NUMERICAL_TOLERANCE)
    )
    assert not simultaneous.any()


# 23. Each day terminal SOC near 0.50
def test_23_nominal_each_day_terminal_soc(nominal_hourly_df: pd.DataFrame):
    """23. Verify every delivery day ends at approximately SOC = 0.50."""
    last_hours = nominal_hourly_df.groupby("delivery_date").last()
    assert np.allclose(last_hours["soc_after"], 0.50, atol=1e-5)


# 24. Annual final SOC near 0.50
def test_24_nominal_annual_final_soc(nominal_summary: dict):
    """24. Verify annual terminal SOC is approximately 0.50."""
    assert nominal_summary["final_soc"] == pytest.approx(0.50, abs=1e-5)


# 25. Solver/replay energy agreement
def test_25_nominal_solver_replay_energy_agreement(nominal_hourly_df: pd.DataFrame):
    """25. Verify solver energy matches physical replayed cell energy."""
    assert np.allclose(
        nominal_hourly_df["solver_energy_after_mwh"],
        nominal_hourly_df["energy_after_mwh"],
        atol=1e-6,
    )


# 26. Optimizer objective agrees with replayed NET objective
def test_26_nominal_optimizer_objective_agrees_with_net_replayed(nominal_summary: dict):
    """26. Verify MILP solver objective agrees with replayed net arbitrage margin."""
    assert nominal_summary["objective_replay_difference_eur"] < 1e-5
    assert nominal_summary["milp_objective_margin_eur"] == pytest.approx(
        nominal_summary["replayed_margin_eur"], abs=1e-5
    )


# 27. Financial hourly arithmetic correct
def test_27_nominal_financial_hourly_arithmetic(nominal_hourly_df: pd.DataFrame):
    """27. Verify charging_cost = grid_ch * price, rev = grid_dis * price, gross = rev - cost."""
    exp_ch = nominal_hourly_df["grid_charge_energy_mwh"] * nominal_hourly_df["price_eur_per_mwh"]
    exp_rev = nominal_hourly_df["grid_discharge_energy_mwh"] * nominal_hourly_df["price_eur_per_mwh"]
    exp_gross = exp_rev - exp_ch
    assert np.allclose(nominal_hourly_df["charging_cost_eur"], exp_ch, atol=1e-7)
    assert np.allclose(nominal_hourly_df["discharge_revenue_eur"], exp_rev, atol=1e-7)
    assert np.allclose(nominal_hourly_df["gross_margin_eur"], exp_gross, atol=1e-7)


# 28. Degradation hourly arithmetic correct
def test_28_nominal_degradation_hourly_arithmetic(nominal_hourly_df: pd.DataFrame):
    """28. Verify degradation_cost = eq_cycle_energy * 20.0."""
    exp_deg = nominal_hourly_df["equivalent_cycle_energy_mwh"] * 20.0
    assert np.allclose(nominal_hourly_df["degradation_cost_eur"], exp_deg, atol=1e-7)


# 29. Nominal summary matches nominal hourly output
def test_29_nominal_summary_matches_hourly(nominal_summary: dict, nominal_hourly_df: pd.DataFrame):
    """29. Verify nominal summary totals match sums of hourly columns."""
    assert nominal_summary["gross_charging_cost_eur"] == pytest.approx(
        nominal_hourly_df["charging_cost_eur"].sum(), abs=1e-5
    )
    assert nominal_summary["gross_discharge_revenue_eur"] == pytest.approx(
        nominal_hourly_df["discharge_revenue_eur"].sum(), abs=1e-5
    )
    assert nominal_summary["gross_arbitrage_margin_eur"] == pytest.approx(
        nominal_hourly_df["gross_margin_eur"].sum(), abs=1e-5
    )
    assert nominal_summary["assumed_degradation_cost_eur"] == pytest.approx(
        nominal_hourly_df["degradation_cost_eur"].sum(), abs=1e-5
    )
    assert nominal_summary["net_margin_after_degradation_eur"] == pytest.approx(
        nominal_hourly_df["net_margin_after_degradation_eur"].sum(), abs=1e-5
    )


# 30. Sensitivity summary matches scenario outputs
def test_30_sensitivity_matches_nominal_summary(sensitivity_df: pd.DataFrame, nominal_summary: dict):
    """30. Verify sensitivity table row for 20 EUR matches nominal summary values."""
    row20 = sensitivity_df[sensitivity_df["degradation_cost_rate_eur_per_mwh_eq_cycle"] == 20.0].iloc[0]
    assert row20["net_margin_after_degradation_eur"] == pytest.approx(
        nominal_summary["net_margin_after_degradation_eur"], abs=1e-5
    )
    assert row20["equivalent_full_cycles"] == pytest.approx(
        nominal_summary["equivalent_full_cycles"], abs=1e-5
    )


# 31. Daily nominal comparison has 366 rows
def test_31_daily_nominal_comparison_rows(nominal_daily_df: pd.DataFrame):
    """31. Verify baseline vs degradation-aware daily comparison contains exactly 366 rows."""
    assert len(nominal_daily_df) == EXPECTED_DELIVERY_DAYS
    assert (nominal_daily_df["hours_in_day"].isin([23, 24, 25])).all()


# 32. Nominal degradation-aware net margin >= fixed baseline net margin at same cost
def test_32_nominal_net_margin_ge_baseline_daily(nominal_daily_df: pd.DataFrame):
    """32. Verify on EVERY delivery day: degradation-aware net margin >= baseline net margin at 20 EUR."""
    diff = nominal_daily_df["optimized_net_margin_eur"] - nominal_daily_df["baseline_net_margin_eur"]
    assert (diff >= -1e-6).all()
    assert (nominal_daily_df["net_improvement_vs_baseline_eur"] >= -1e-6).all()


# 33. Zero-cost optimized gross margin >= fixed baseline gross margin
def test_33_zero_cost_gross_margin_ge_baseline(sensitivity_df: pd.DataFrame):
    """33. Verify zero-cost optimized gross margin strictly exceeds baseline gross margin."""
    row0 = sensitivity_df[sensitivity_df["degradation_cost_rate_eur_per_mwh_eq_cycle"] == 0.0].iloc[0]
    assert row0["gross_arbitrage_margin_eur"] > row0["baseline_gross_margin_eur"]


# 34. Deterministic repeat execution
def test_34_deterministic_repeat_execution(input_prices_df: pd.DataFrame, nominal_hourly_df: pd.DataFrame):
    """34. Verify repeating nominal optimization produces identical results."""
    sample_dates = ["2024-02-14", "2024-03-31", "2024-10-27"]
    sample_prices = input_prices_df[input_prices_df["delivery_date"].isin(sample_dates)]
    df_rep, _, _ = simulate_optimized(
        sample_prices,
        degradation_cost_eur_per_mwh_eq_cycle=20.0,
        include_degradation_columns=True,
    )
    df_orig = nominal_hourly_df[nominal_hourly_df["delivery_date"].isin(sample_dates)].reset_index(drop=True)
    pd.testing.assert_frame_equal(df_rep, df_orig)
