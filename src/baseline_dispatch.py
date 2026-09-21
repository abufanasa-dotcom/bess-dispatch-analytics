"""Fixed-Schedule Baseline BESS Dispatch Simulation.

Simulates a transparent, fixed local-time benchmark schedule across the complete
German 2024 market delivery year using the physical BatteryModel.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path when executed directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.battery_model import BESSConfig, BatteryModel

SCHEDULE_HOURS = {
    3: {"charge_power_mw": 1.0, "discharge_power_mw": 0.0, "target_soc": None},
    18: {"charge_power_mw": 0.0, "discharge_power_mw": 1.0, "target_soc": None},
    19: {"charge_power_mw": 0.0, "discharge_power_mw": 1.0, "target_soc": None},
    23: {"charge_power_mw": 1.0, "discharge_power_mw": 0.0, "target_soc": 0.50},
}


def simulate_baseline(
    prices_df: pd.DataFrame,
    config: BESSConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Simulate the baseline dispatch strategy continuously across the entire year.

    Args:
        prices_df: Validated day-ahead electricity prices DataFrame containing
                   timestamp_utc, price_eur_per_mwh, timestamp_europe_berlin, delivery_date.
        config: Optional immutable BESS configuration. Defaults to BESSConfig().

    Returns:
        Tuple of (detailed hourly dispatch DataFrame, comprehensive summary dict).
    """
    if config is None:
        config = BESSConfig()

    # Create ONE stateful battery model instance at the start of the year
    model = BatteryModel(config)

    # Parse local hours reliably from timestamp_europe_berlin (preserving timezone offsets)
    local_ts = pd.to_datetime(prices_df["timestamp_europe_berlin"], utc=True).dt.tz_convert("Europe/Berlin")
    local_hours = local_ts.dt.hour

    records: list[dict[str, Any]] = []

    for i in range(len(prices_df)):
        row = prices_df.iloc[i]
        hour = local_hours.iloc[i]
        price = float(row["price_eur_per_mwh"])

        if hour in SCHEDULE_HOURS:
            action = SCHEDULE_HOURS[hour]
            req_charge = action["charge_power_mw"]
            req_discharge = action["discharge_power_mw"]
            target_soc = action["target_soc"]
            step_res = model.step(
                charge_power_mw=req_charge,
                discharge_power_mw=req_discharge,
                target_soc=target_soc,
            )
        else:
            step_res = model.step(charge_power_mw=0.0, discharge_power_mw=0.0)

        # Financial accounting (GRID-side energy)
        charging_cost = step_res.grid_charge_energy_mwh * price
        discharge_revenue = step_res.grid_discharge_energy_mwh * price
        gross_margin = discharge_revenue - charging_cost

        # Throughput & EFC (CELL-side energy)
        cell_throughput = step_res.cell_charge_energy_mwh + step_res.cell_discharge_energy_mwh
        incremental_efc = cell_throughput / (2.0 * config.nominal_energy_capacity_mwh)

        records.append(
            {
                "timestamp_utc": row["timestamp_utc"],
                "timestamp_europe_berlin": row["timestamp_europe_berlin"],
                "delivery_date": row["delivery_date"],
                "price_eur_per_mwh": price,
                "requested_charge_power_mw": step_res.requested_charge_power_mw,
                "requested_discharge_power_mw": step_res.requested_discharge_power_mw,
                "actual_charge_power_mw": step_res.actual_charge_power_mw,
                "actual_discharge_power_mw": step_res.actual_discharge_power_mw,
                "grid_charge_energy_mwh": step_res.grid_charge_energy_mwh,
                "grid_discharge_energy_mwh": step_res.grid_discharge_energy_mwh,
                "cell_charge_energy_mwh": step_res.cell_charge_energy_mwh,
                "cell_discharge_energy_mwh": step_res.cell_discharge_energy_mwh,
                "energy_before_mwh": step_res.energy_before_mwh,
                "energy_after_mwh": step_res.energy_after_mwh,
                "soc_before": step_res.soc_before,
                "soc_after": step_res.soc_after,
                "conversion_loss_mwh": step_res.conversion_loss_mwh,
                "was_soc_limited": step_res.was_soc_limited,
                "charging_cost_eur": charging_cost,
                "discharge_revenue_eur": discharge_revenue,
                "gross_margin_eur": gross_margin,
                "cell_throughput_mwh": cell_throughput,
                "incremental_efc": incremental_efc,
            }
        )

    dispatch_df = pd.DataFrame(records)

    # Compute aggregate KPI metrics
    tot_ch_cost = float(dispatch_df["charging_cost_eur"].sum())
    tot_dis_rev = float(dispatch_df["discharge_revenue_eur"].sum())
    tot_margin = float(dispatch_df["gross_margin_eur"].sum())

    tot_grid_ch = float(dispatch_df["grid_charge_energy_mwh"].sum())
    tot_grid_dis = float(dispatch_df["grid_discharge_energy_mwh"].sum())
    tot_cell_th = float(dispatch_df["cell_throughput_mwh"].sum())
    tot_efc = float(dispatch_df["incremental_efc"].sum())
    realized_rte = float(tot_grid_dis / tot_grid_ch) if tot_grid_ch > 0 else 0.0

    avg_soc = float(dispatch_df["soc_after"].mean())
    min_soc = float(dispatch_df["soc_after"].min())
    max_soc = float(dispatch_df["soc_after"].max())

    charging_hours = int((dispatch_df["actual_charge_power_mw"] > 0).sum())
    discharging_hours = int((dispatch_df["actual_discharge_power_mw"] > 0).sum())
    active_hours = charging_hours + discharging_hours
    idle_hours = int(((dispatch_df["actual_charge_power_mw"] == 0) & (dispatch_df["actual_discharge_power_mw"] == 0)).sum())
    utilization_pct = float(active_hours / len(dispatch_df) * 100)

    delivery_days_count = int(dispatch_df["delivery_date"].nunique())
    day_counts = dispatch_df.groupby("delivery_date").size()
    m31_hours = int(day_counts.get("2024-03-31", 0))
    o27_hours = int(day_counts.get("2024-10-27", 0))
    neg_hours = int((dispatch_df["price_eur_per_mwh"] < 0).sum())

    summary: dict[str, Any] = {
        "strategy_name": "Fixed Local-Time Baseline Schedule",
        "strategy_description": (
            "Fixed local-time engineering benchmark. Action hours are predetermined "
            "and are not selected using realized electricity prices."
        ),
        "analysis_year": 2024,
        "initial_soc": float(config.initial_soc),
        "final_soc": float(model.soc),
        "total_charging_cost_eur": tot_ch_cost,
        "total_discharge_revenue_eur": tot_dis_rev,
        "gross_arbitrage_margin_eur": tot_margin,
        "total_grid_charge_energy_mwh": tot_grid_ch,
        "total_grid_discharge_energy_mwh": tot_grid_dis,
        "total_cell_throughput_mwh": tot_cell_th,
        "equivalent_full_cycles": tot_efc,
        "realized_round_trip_efficiency": realized_rte,
        "average_soc": avg_soc,
        "minimum_soc": min_soc,
        "maximum_soc": max_soc,
        "charging_hours": charging_hours,
        "discharging_hours": discharging_hours,
        "idle_hours": idle_hours,
        "active_hours": active_hours,
        "utilization_percent": utilization_pct,
        "delivery_days": delivery_days_count,
        "spring_dst_day_hours": m31_hours,
        "autumn_dst_day_hours": o27_hours,
        "negative_price_hours_total": neg_hours,
    }

    return dispatch_df, summary


def run_baseline_pipeline(
    project_root: Path | None = None,
    config: BESSConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Execute complete baseline simulation pipeline and generate reports."""
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    prices_path = project_root / "data" / "processed" / "de_lu_day_ahead_prices_2024.csv"
    reports_dir = project_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    output_csv = reports_dir / "baseline_dispatch_2024.csv"
    output_json = reports_dir / "baseline_summary_2024.json"

    if not prices_path.exists():
        raise FileNotFoundError(f"Prices dataset not found at {prices_path}.")

    prices_df = pd.read_csv(prices_path)
    dispatch_df, summary = simulate_baseline(prices_df, config=config)

    # Save CSV without rounding
    dispatch_df.to_csv(output_csv, index=False)

    # Save summary JSON
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return dispatch_df, summary


if __name__ == "__main__":
    df, summ = run_baseline_pipeline()
    print("Baseline simulation finished successfully.")
    print(f"Gross Margin: {summ['gross_arbitrage_margin_eur']:.2f} EUR")
    print(f"EFC: {summ['equivalent_full_cycles']:.2f}")
    print(f"Realized RTE: {summ['realized_round_trip_efficiency']:.4f}")
