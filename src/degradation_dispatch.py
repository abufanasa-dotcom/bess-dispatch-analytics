"""Degradation-Aware BESS Dispatch and Sensitivity Analysis.

Implements economic wear cost penalization in day-ahead MILP dispatch across
four degradation cost scenarios (0, 10, 20, 30 EUR/MWh-equivalent-cycle-energy),
evaluating trade-offs between gross arbitrage margin, cycling throughput (EFC),
and net economic margin.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path when executed directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

from src.battery_model import BESSConfig
from src.optimized_dispatch import simulate_optimized

SCENARIOS = [0.0, 10.0, 20.0, 30.0]
NOMINAL_SCENARIO_RATE = 20.0


def run_degradation_pipeline() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], pd.DataFrame]:
    """Execute all four degradation cost scenarios, generate reports, and return datasets.

    Returns:
        Tuple containing:
            1. sensitivity_df: DataFrame with 4 scenario rows
            2. nominal_hourly_df: Detailed 8,784-row dispatch for 20 EUR scenario
            3. nominal_summary: Summary dict for 20 EUR scenario
            4. nominal_daily_df: Daily comparison DataFrame (366 rows) for 20 EUR scenario
    """
    prices_path = PROJECT_ROOT / "data" / "processed" / "de_lu_day_ahead_prices_2024.csv"
    baseline_path = PROJECT_ROOT / "reports" / "baseline_dispatch_2024.csv"
    baseline_summary_path = PROJECT_ROOT / "reports" / "baseline_summary_2024.json"
    step7_summary_path = PROJECT_ROOT / "reports" / "optimized_summary_2024.json"
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading prices from {prices_path}...")
    prices_df = pd.read_csv(prices_path)

    print(f"Loading baseline dispatch from {baseline_path}...")
    baseline_df = pd.read_csv(baseline_path)

    with open(baseline_summary_path, "r", encoding="utf-8") as f:
        baseline_summary = json.load(f)

    with open(step7_summary_path, "r", encoding="utf-8") as f:
        step7_summary = json.load(f)

    base_gross_margin = float(baseline_summary["gross_arbitrage_margin_eur"])
    base_efc = float(baseline_summary["equivalent_full_cycles"])
    base_eq_cycle_energy = base_efc * 2.0  # nominal capacity = 2.0 MWh

    step7_gross_margin = float(step7_summary["gross_arbitrage_margin_eur"])
    step7_efc = float(step7_summary["equivalent_full_cycles"])

    # Pre-calculate baseline daily values
    baseline_daily = (
        baseline_df.groupby("delivery_date")
        .agg(
            gross_margin=("gross_margin_eur", "sum"),
            efc=("incremental_efc", "sum"),
            hours=("timestamp_utc", "count"),
        )
        .reset_index()
    )

    sensitivity_rows: list[dict[str, Any]] = []

    nominal_hourly_df: pd.DataFrame | None = None
    nominal_summary: dict[str, Any] | None = None
    nominal_daily_df: pd.DataFrame | None = None

    for rate in SCENARIOS:
        print(f"\n--- Running Optimization for Scenario: {rate:.0f} EUR/MWh-eq-cycle ---")
        is_nominal = math.isclose(rate, NOMINAL_SCENARIO_RATE, abs_tol=1e-5)

        hourly_df, summary, _ = simulate_optimized(
            prices_df=prices_df,
            baseline_df=baseline_df,
            config=BESSConfig(),
            degradation_cost_eur_per_mwh_eq_cycle=rate,
            include_degradation_columns=is_nominal,
        )

        gross_margin = summary["gross_arbitrage_margin_eur"]
        tot_throughput = summary["total_cell_throughput_mwh"]
        eq_cycle_energy = tot_throughput / 2.0
        efc = summary["equivalent_full_cycles"]
        deg_cost = eq_cycle_energy * rate
        net_margin = gross_margin - deg_cost

        base_deg_cost = base_eq_cycle_energy * rate
        base_net_margin = base_gross_margin - base_deg_cost
        net_improvement = net_margin - base_net_margin
        pct_improvement = (net_improvement / base_net_margin * 100.0) if base_net_margin > 0 else None

        realized_gross_val_per_mwh = (gross_margin / eq_cycle_energy) if eq_cycle_energy > 0 else 0.0
        gross_val_per_efc = (gross_margin / efc) if efc > 0 else 0.0

        scenario_record = {
            "degradation_cost_rate_eur_per_mwh_eq_cycle": rate,
            "gross_charging_cost_eur": summary["total_charging_cost_eur"],
            "gross_discharge_revenue_eur": summary["total_discharge_revenue_eur"],
            "gross_arbitrage_margin_eur": gross_margin,
            "equivalent_cycle_energy_mwh": eq_cycle_energy,
            "cell_throughput_mwh": tot_throughput,
            "equivalent_full_cycles": efc,
            "assumed_degradation_cost_eur": deg_cost,
            "net_margin_after_degradation_eur": net_margin,
            "baseline_gross_margin_eur": base_gross_margin,
            "baseline_equivalent_full_cycles": base_efc,
            "baseline_assumed_degradation_cost_eur": base_deg_cost,
            "baseline_net_margin_after_degradation_eur": base_net_margin,
            "net_improvement_vs_baseline_eur": net_improvement,
            "net_improvement_vs_baseline_percent": pct_improvement,
            "grid_charge_energy_mwh": summary["total_grid_charge_energy_mwh"],
            "grid_discharge_energy_mwh": summary["total_grid_discharge_energy_mwh"],
            "charging_hours": summary["charging_hours"],
            "discharging_hours": summary["discharging_hours"],
            "idle_hours": summary["idle_hours"],
            "utilization_percent": summary["utilization_percent"],
            "minimum_soc": summary["minimum_soc"],
            "maximum_soc": summary["maximum_soc"],
            "final_soc": summary["final_soc"],
            "all_days_solver_success": summary["optimized_days_successful"] == 366,
            "realized_gross_value_per_mwh_eq_cycle": realized_gross_val_per_mwh,
            "gross_value_per_efc_eur": gross_val_per_efc,
        }
        sensitivity_rows.append(scenario_record)

        if is_nominal:
            nominal_hourly_df = hourly_df

            # Construct nominal summary
            efc_reduction = step7_efc - efc
            efc_reduction_pct = (efc_reduction / step7_efc * 100.0) if step7_efc > 0 else 0.0
            gross_reduction = step7_gross_margin - gross_margin

            nominal_summary = {
                "strategy_name": "Degradation-Aware Perfect-Foresight MILP Dispatch (20 EUR/MWh)",
                "strategy_description": (
                    "Ex-post perfect-foresight MILP benchmark with economic wear cost penalty. "
                    "Not a deployable trading forecast."
                ),
                "modeling_warning": (
                    "Degradation cost is a simplified economic sensitivity assumption and "
                    "does not represent electrochemical State of Health prediction."
                ),
                "degradation_cost_rate": rate,
                "degradation_cost_unit": "EUR/MWh-equivalent-cycle-energy",
                "analysis_year": 2024,
                "delivery_days": summary["delivery_days"],
                "all_days_solver_success": summary["optimized_days_successful"] == 366,
                "gross_charging_cost_eur": summary["total_charging_cost_eur"],
                "gross_discharge_revenue_eur": summary["total_discharge_revenue_eur"],
                "gross_arbitrage_margin_eur": gross_margin,
                "equivalent_cycle_energy_mwh": eq_cycle_energy,
                "cell_throughput_mwh": tot_throughput,
                "equivalent_full_cycles": efc,
                "assumed_degradation_cost_eur": deg_cost,
                "net_margin_after_degradation_eur": net_margin,
                "baseline_net_margin_at_same_cost_eur": base_net_margin,
                "net_improvement_vs_baseline_eur": net_improvement,
                "net_improvement_vs_baseline_percent": pct_improvement,
                "gross_step7_margin_eur": step7_gross_margin,
                "gross_step7_efc": step7_efc,
                "gross_margin_reduction_vs_step7_eur": gross_reduction,
                "efc_reduction_vs_step7": efc_reduction,
                "efc_reduction_vs_step7_percent": efc_reduction_pct,
                "grid_charge_energy_mwh": summary["total_grid_charge_energy_mwh"],
                "grid_discharge_energy_mwh": summary["total_grid_discharge_energy_mwh"],
                "realized_round_trip_efficiency": summary["realized_round_trip_efficiency"],
                "charging_hours": summary["charging_hours"],
                "discharging_hours": summary["discharging_hours"],
                "idle_hours": summary["idle_hours"],
                "active_hours": summary["active_hours"],
                "utilization_percent": summary["utilization_percent"],
                "minimum_soc": summary["minimum_soc"],
                "maximum_soc": summary["maximum_soc"],
                "average_soc": summary["average_soc"],
                "final_soc": summary["final_soc"],
                "negative_price_hours_total": summary["negative_price_hours_total"],
                "charge_during_negative_price_hours": summary["charge_during_negative_price_hours"],
                "discharge_during_negative_price_hours": summary["discharge_during_negative_price_hours"],
                "milp_objective_margin_eur": summary["milp_objective_margin_eur"],
                "replayed_margin_eur": net_margin,
                "objective_replay_difference_eur": abs(summary["milp_objective_margin_eur"] - net_margin),
                "maximum_solver_replay_energy_difference_mwh": summary["maximum_solver_replay_energy_difference_mwh"],
                "spring_dst_day_hours": summary["spring_dst_day_hours"],
                "autumn_dst_day_hours": summary["autumn_dst_day_hours"],
            }

            # Build nominal daily comparison
            daily_nominal_rows: list[dict[str, Any]] = []
            for d, grp in hourly_df.groupby("delivery_date"):
                d_str = str(d)
                t_day = len(grp)
                d_gross = float(grp["gross_margin_eur"].sum())
                d_deg = float(grp["degradation_cost_eur"].sum())
                d_net = float(grp["net_margin_after_degradation_eur"].sum())
                d_efc = float(grp["incremental_efc"].sum())

                # Baseline for this date
                base_row = baseline_daily[baseline_daily["delivery_date"] == d_str]
                b_gross = float(base_row["gross_margin"].iloc[0]) if len(base_row) > 0 else 0.0
                b_efc_day = float(base_row["efc"].iloc[0]) if len(base_row) > 0 else 0.0
                b_deg = b_efc_day * 2.0 * rate
                b_net = b_gross - b_deg

                net_imp_day = d_net - b_net
                prices_day = grp["price_eur_per_mwh"]
                min_p = float(prices_day.min())
                max_p = float(prices_day.max())

                daily_nominal_rows.append(
                    {
                        "delivery_date": d_str,
                        "hours_in_day": t_day,
                        "baseline_gross_margin_eur": b_gross,
                        "baseline_degradation_cost_eur": b_deg,
                        "baseline_net_margin_eur": b_net,
                        "baseline_efc": b_efc_day,
                        "optimized_gross_margin_eur": d_gross,
                        "optimized_degradation_cost_eur": d_deg,
                        "optimized_net_margin_eur": d_net,
                        "optimized_efc": d_efc,
                        "net_improvement_vs_baseline_eur": net_imp_day,
                        "minimum_price_eur_per_mwh": min_p,
                        "maximum_price_eur_per_mwh": max_p,
                        "daily_price_spread_eur_per_mwh": max_p - min_p,
                    }
                )
            nominal_daily_df = pd.DataFrame(daily_nominal_rows)

    sensitivity_df = pd.DataFrame(sensitivity_rows)

    # Save report files
    out_sensitivity = reports_dir / "degradation_sensitivity_2024.csv"
    out_hourly = reports_dir / "degradation_aware_dispatch_20eur_2024.csv"
    out_summary = reports_dir / "degradation_aware_summary_20eur_2024.json"
    out_daily = reports_dir / "baseline_vs_degradation_aware_daily_20eur_2024.csv"

    print(f"\nSaving sensitivity report to {out_sensitivity}...")
    sensitivity_df.to_csv(out_sensitivity, index=False)

    print(f"Saving nominal hourly schedule to {out_hourly}...")
    nominal_hourly_df.to_csv(out_hourly, index=False)

    print(f"Saving nominal summary JSON to {out_summary}...")
    with open(out_summary, "w", encoding="utf-8") as f:
        json.dump(nominal_summary, f, indent=2)

    print(f"Saving nominal daily comparison to {out_daily}...")
    nominal_daily_df.to_csv(out_daily, index=False)

    print("\n--- Degradation Sensitivity Pipeline Complete ---")
    for _, row in sensitivity_df.iterrows():
        c_rate = row["degradation_cost_rate_eur_per_mwh_eq_cycle"]
        print(
            f"Rate={c_rate:2.0f} EUR/MWh: Gross={row['gross_arbitrage_margin_eur']:,.2f} EUR | "
            f"DegCost={row['assumed_degradation_cost_eur']:,.2f} EUR | "
            f"Net={row['net_margin_after_degradation_eur']:,.2f} EUR | "
            f"EFC={row['equivalent_full_cycles']:.2f} | "
            f"Util={row['utilization_percent']:.1f}%"
        )

    return sensitivity_df, nominal_hourly_df, nominal_summary, nominal_daily_df


if __name__ == "__main__":
    run_degradation_pipeline()
