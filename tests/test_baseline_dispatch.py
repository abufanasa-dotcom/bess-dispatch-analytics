"""Comprehensive verification and physics tests for fixed-schedule baseline dispatch."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.baseline_dispatch import simulate_baseline
from src.battery_model import BESSConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRICES_CSV = PROJECT_ROOT / "data" / "processed" / "de_lu_day_ahead_prices_2024.csv"
BASELINE_CSV = PROJECT_ROOT / "reports" / "baseline_dispatch_2024.csv"
SUMMARY_JSON = PROJECT_ROOT / "reports" / "baseline_summary_2024.json"

EXPECTED_ROW_COUNT = 8784
EXPECTED_DELIVERY_DAYS = 366


@pytest.fixture(scope="module")
def input_prices_df() -> pd.DataFrame:
    """Fixture providing input validated prices dataset."""
    assert PRICES_CSV.exists(), f"Prices CSV missing at {PRICES_CSV}"
    return pd.read_csv(PRICES_CSV)


@pytest.fixture(scope="module")
def baseline_df() -> pd.DataFrame:
    """Fixture providing generated baseline dispatch dataset."""
    assert BASELINE_CSV.exists(), f"Baseline CSV missing at {BASELINE_CSV}"
    return pd.read_csv(BASELINE_CSV)


@pytest.fixture(scope="module")
def summary_data() -> dict:
    """Fixture providing generated baseline summary JSON."""
    assert SUMMARY_JSON.exists(), f"Summary JSON missing at {SUMMARY_JSON}"
    with open(SUMMARY_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def test_01_output_rows_count(baseline_df: pd.DataFrame):
    """1. Verify output contains exactly 8,784 rows."""
    assert len(baseline_df) == EXPECTED_ROW_COUNT


def test_02_timestamps_match_input_prices(baseline_df: pd.DataFrame, input_prices_df: pd.DataFrame):
    """2. Verify timestamps exactly match the validated input price dataset."""
    pd.testing.assert_series_equal(baseline_df["timestamp_utc"], input_prices_df["timestamp_utc"])
    pd.testing.assert_series_equal(
        baseline_df["timestamp_europe_berlin"], input_prices_df["timestamp_europe_berlin"]
    )


def test_03_prices_match_input_dataset(baseline_df: pd.DataFrame, input_prices_df: pd.DataFrame):
    """3. Verify prices exactly match the validated input dataset."""
    pd.testing.assert_series_equal(baseline_df["price_eur_per_mwh"], input_prices_df["price_eur_per_mwh"])


def test_04_negative_prices_remain_unchanged(baseline_df: pd.DataFrame, input_prices_df: pd.DataFrame):
    """4. Verify negative prices remain unchanged and unclipped."""
    neg_input = input_prices_df[input_prices_df["price_eur_per_mwh"] < 0]
    neg_baseline = baseline_df[baseline_df["price_eur_per_mwh"] < 0]
    assert len(neg_baseline) == len(neg_input) == 457
    assert baseline_df["price_eur_per_mwh"].min() == pytest.approx(-135.45)


def test_05_exactly_366_delivery_days(baseline_df: pd.DataFrame):
    """5. Verify exactly 366 delivery days exist."""
    assert baseline_df["delivery_date"].nunique() == EXPECTED_DELIVERY_DAYS


def test_06_march_31_contains_23_rows(baseline_df: pd.DataFrame):
    """6. Verify spring DST transition (2024-03-31) contains exactly 23 rows."""
    m31 = baseline_df[baseline_df["delivery_date"] == "2024-03-31"]
    assert len(m31) == 23


def test_07_october_27_contains_25_rows(baseline_df: pd.DataFrame):
    """7. Verify autumn DST transition (2024-10-27) contains exactly 25 rows."""
    o27 = baseline_df[baseline_df["delivery_date"] == "2024-10-27"]
    assert len(o27) == 25


def test_08_four_scheduled_action_hours_occur_on_every_delivery_date(baseline_df: pd.DataFrame):
    """8. Verify all four action hours occur on every delivery date."""
    local_ts = pd.to_datetime(baseline_df["timestamp_europe_berlin"], utc=True).dt.tz_convert("Europe/Berlin")
    action_mask = local_ts.dt.hour.isin([3, 18, 19, 23])
    actions_by_date = baseline_df[action_mask].groupby("delivery_date").size()
    assert len(actions_by_date) == EXPECTED_DELIVERY_DAYS
    assert (actions_by_date == 4).all()


def test_09_charging_occurs_only_at_local_hours_03_and_23(baseline_df: pd.DataFrame):
    """9. Verify charging occurs only at local hours 03 and 23."""
    local_ts = pd.to_datetime(baseline_df["timestamp_europe_berlin"], utc=True).dt.tz_convert("Europe/Berlin")
    charging_mask = baseline_df["actual_charge_power_mw"] > 0
    charging_hours = local_ts[charging_mask].dt.hour.unique()
    assert set(charging_hours).issubset({3, 23})


def test_10_discharging_occurs_only_at_local_hours_18_and_19(baseline_df: pd.DataFrame):
    """10. Verify discharging occurs only at local hours 18 and 19."""
    local_ts = pd.to_datetime(baseline_df["timestamp_europe_berlin"], utc=True).dt.tz_convert("Europe/Berlin")
    discharging_mask = baseline_df["actual_discharge_power_mw"] > 0
    discharging_hours = local_ts[discharging_mask].dt.hour.unique()
    assert set(discharging_hours).issubset({18, 19})


def test_11_no_simultaneous_charging_and_discharging(baseline_df: pd.DataFrame):
    """11. Verify mutual exclusivity: no simultaneous charging and discharging."""
    simultaneous = (baseline_df["actual_charge_power_mw"] > 1e-9) & (baseline_df["actual_discharge_power_mw"] > 1e-9)
    assert not simultaneous.any()


def test_12_no_rated_power_violation(baseline_df: pd.DataFrame):
    """12. Verify actual and requested powers never exceed 1.0 MW rated power."""
    assert (baseline_df["actual_charge_power_mw"] <= 1.0 + 1e-9).all()
    assert (baseline_df["actual_discharge_power_mw"] <= 1.0 + 1e-9).all()
    assert (baseline_df["requested_charge_power_mw"] <= 1.0 + 1e-9).all()
    assert (baseline_df["requested_discharge_power_mw"] <= 1.0 + 1e-9).all()


def test_13_no_grid_connection_violation(baseline_df: pd.DataFrame):
    """13. Verify power interchange never exceeds 1.0 MW grid limit."""
    assert (baseline_df["actual_charge_power_mw"] <= 1.0 + 1e-9).all()
    assert (baseline_df["actual_discharge_power_mw"] <= 1.0 + 1e-9).all()


def test_14_soc_never_below_minimum(baseline_df: pd.DataFrame):
    """14. Verify SOC never drops below soc_min = 0.10."""
    assert (baseline_df["soc_after"] >= 0.10 - 1e-9).all()


def test_15_soc_never_above_maximum(baseline_df: pd.DataFrame):
    """15. Verify SOC never exceeds soc_max = 0.90."""
    assert (baseline_df["soc_after"] <= 0.90 + 1e-9).all()


def test_16_every_delivery_day_starts_at_approx_0_50_soc(baseline_df: pd.DataFrame):
    """16. Verify every delivery day starts at approximately 0.50 SOC."""
    first_hours = baseline_df.groupby("delivery_date").first()
    assert np.allclose(first_hours["soc_before"], 0.50, atol=1e-5)


def test_17_every_delivery_day_ends_at_approx_0_50_soc(baseline_df: pd.DataFrame):
    """17. Verify every delivery day ends at approximately 0.50 SOC."""
    last_hours = baseline_df.groupby("delivery_date").last()
    assert np.allclose(last_hours["soc_after"], 0.50, atol=1e-5)


def test_18_final_annual_soc_approx_0_50(baseline_df: pd.DataFrame):
    """18. Verify final annual SOC is approximately 0.50."""
    final_soc = baseline_df["soc_after"].iloc[-1]
    assert final_soc == pytest.approx(0.50, abs=1e-5)


def test_19_03_actual_charge_approx_0_842105(baseline_df: pd.DataFrame):
    """19. Verify 03:00 actual charge power is approximately 0.8421052632 MW."""
    local_ts = pd.to_datetime(baseline_df["timestamp_europe_berlin"], utc=True).dt.tz_convert("Europe/Berlin")
    h3 = baseline_df[local_ts.dt.hour == 3]
    expected_power = 0.8 / 0.95
    assert np.allclose(h3["actual_charge_power_mw"], expected_power, rtol=1e-5)
    assert np.allclose(h3["soc_after"], 0.90, atol=1e-5)


def test_20_18_actual_discharge_approx_1_0(baseline_df: pd.DataFrame):
    """20. Verify 18:00 actual discharge power is approximately 1.0 MW."""
    local_ts = pd.to_datetime(baseline_df["timestamp_europe_berlin"], utc=True).dt.tz_convert("Europe/Berlin")
    h18 = baseline_df[local_ts.dt.hour == 18]
    assert np.allclose(h18["actual_discharge_power_mw"], 1.0, rtol=1e-5)


def test_21_19_actual_discharge_approx_0_52(baseline_df: pd.DataFrame):
    """21. Verify 19:00 actual discharge power is approximately 0.52 MW."""
    local_ts = pd.to_datetime(baseline_df["timestamp_europe_berlin"], utc=True).dt.tz_convert("Europe/Berlin")
    h19 = baseline_df[local_ts.dt.hour == 19]
    assert np.allclose(h19["actual_discharge_power_mw"], 0.52, rtol=1e-5)
    assert np.allclose(h19["soc_after"], 0.10, atol=1e-5)


def test_22_23_actual_charge_approx_0_842105(baseline_df: pd.DataFrame):
    """22. Verify 23:00 actual charge power is approximately 0.8421052632 MW."""
    local_ts = pd.to_datetime(baseline_df["timestamp_europe_berlin"], utc=True).dt.tz_convert("Europe/Berlin")
    h23 = baseline_df[local_ts.dt.hour == 23]
    expected_power = 0.8 / 0.95
    assert np.allclose(h23["actual_charge_power_mw"], expected_power, rtol=1e-5)
    assert np.allclose(h23["soc_after"], 0.50, atol=1e-5)


def test_23_charging_hours_equals_732(summary_data: dict):
    """23. Verify total charging hours == 732 (366 days * 2 hours)."""
    assert summary_data["charging_hours"] == 732


def test_24_discharging_hours_equals_732(summary_data: dict):
    """24. Verify total discharging hours == 732 (366 days * 2 hours)."""
    assert summary_data["discharging_hours"] == 732


def test_25_active_hours_equals_1464(summary_data: dict):
    """25. Verify total active hours == 1,464 (732 + 732)."""
    assert summary_data["active_hours"] == 1464


def test_26_idle_hours_equals_7320(summary_data: dict):
    """26. Verify total idle hours == 7,320 (8,784 - 1,464)."""
    assert summary_data["idle_hours"] == 7320


def test_27_annual_grid_charge_energy_approx_616_421(summary_data: dict):
    """27. Verify annual grid charge energy is approximately 616.4210526 MWh."""
    expected = 366 * 2 * (0.8 / 0.95)
    assert summary_data["total_grid_charge_energy_mwh"] == pytest.approx(expected, rel=1e-5)


def test_28_annual_grid_discharge_energy_approx_556_32(summary_data: dict):
    """28. Verify annual grid discharge energy is approximately 556.32 MWh."""
    expected = 366 * 1.52
    assert summary_data["total_grid_discharge_energy_mwh"] == pytest.approx(expected, rel=1e-5)


def test_29_realized_round_trip_efficiency_approx_0_9025(summary_data: dict):
    """29. Verify realized round-trip efficiency is approximately 0.9025."""
    assert summary_data["realized_round_trip_efficiency"] == pytest.approx(0.9025, rel=1e-5)


def test_30_annual_cell_throughput_approx_1171_2(summary_data: dict):
    """30. Verify annual cell throughput is approximately 1171.2 MWh."""
    expected = 366 * 3.2
    assert summary_data["total_cell_throughput_mwh"] == pytest.approx(expected, rel=1e-5)


def test_31_annual_efc_approx_292_8(summary_data: dict):
    """31. Verify annual EFC is approximately 292.8."""
    expected = (366 * 3.2) / (2.0 * 2.0)
    assert summary_data["equivalent_full_cycles"] == pytest.approx(expected, rel=1e-5)


def test_32_hourly_charging_cost_arithmetic(baseline_df: pd.DataFrame):
    """32. Verify hourly charging cost arithmetic: cost == grid_charge_energy * price."""
    expected_cost = baseline_df["grid_charge_energy_mwh"] * baseline_df["price_eur_per_mwh"]
    assert np.allclose(baseline_df["charging_cost_eur"], expected_cost, atol=1e-9)


def test_33_hourly_discharge_revenue_arithmetic(baseline_df: pd.DataFrame):
    """33. Verify hourly discharge revenue arithmetic: revenue == grid_discharge_energy * price."""
    expected_rev = baseline_df["grid_discharge_energy_mwh"] * baseline_df["price_eur_per_mwh"]
    assert np.allclose(baseline_df["discharge_revenue_eur"], expected_rev, atol=1e-9)


def test_34_gross_margin_equals_revenue_minus_cost(baseline_df: pd.DataFrame):
    """34. Verify gross margin == discharge_revenue - charging_cost for every hour."""
    expected_margin = baseline_df["discharge_revenue_eur"] - baseline_df["charging_cost_eur"]
    assert np.allclose(baseline_df["gross_margin_eur"], expected_margin, atol=1e-9)


def test_35_annual_financial_totals_equal_sums_of_hourly_values(baseline_df: pd.DataFrame, summary_data: dict):
    """35. Verify annual summary financial totals equal exact sums of hourly columns."""
    assert summary_data["total_charging_cost_eur"] == pytest.approx(baseline_df["charging_cost_eur"].sum(), abs=1e-7)
    assert summary_data["total_discharge_revenue_eur"] == pytest.approx(baseline_df["discharge_revenue_eur"].sum(), abs=1e-7)
    assert summary_data["gross_arbitrage_margin_eur"] == pytest.approx(baseline_df["gross_margin_eur"].sum(), abs=1e-7)


def test_36_repeated_execution_produces_deterministic_results(input_prices_df: pd.DataFrame, baseline_df: pd.DataFrame):
    """36. Verify running the simulation again produces identical deterministic results."""
    df_recomputed, summary_recomputed = simulate_baseline(input_prices_df, config=BESSConfig())
    pd.testing.assert_frame_equal(df_recomputed, baseline_df)
