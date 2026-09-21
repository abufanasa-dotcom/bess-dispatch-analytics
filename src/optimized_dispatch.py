"""Ex-Post Perfect-Foresight MILP Dispatch Optimization for BESS.

Solves day-ahead market energy arbitrage for each German delivery date in 2024
using SciPy's HiGHS solver backend and validates all power flows continuously
through the physical BatteryModel.
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
from scipy.optimize import Bounds, LinearConstraint, milp

from src.battery_model import BESSConfig, BatteryModel

NUMERICAL_TOLERANCE = 1e-7


def solve_day_milp(
    prices: np.ndarray,
    config: BESSConfig,
    delivery_date: str,
    degradation_cost_eur_per_mwh_eq_cycle: float = 0.0,
) -> dict[str, Any]:
    """Solve the MILP arbitrage maximization problem for a single delivery day.

    Formulation:
        Variables (size 5 * T):
            p_ch[t]:      Continuous charging power at grid interface (MW >= 0)
            p_dis[t]:     Continuous discharge power at grid interface (MW >= 0)
            e_after[t]:   Continuous cell-stored energy after hour t (MWh)
            u_ch[t]:      Binary charging mode indicator in {0, 1}
            u_dis[t]:     Binary discharging mode indicator in {0, 1}

        Objective:
            Minimize: sum_t [ (price[t] + 0.5 * c_deg * eta_ch) * p_ch[t] * dt
                            - (price[t] - 0.5 * c_deg / eta_dis) * p_dis[t] * dt ]
            (Equivalent to maximizing net day-ahead arbitrage margin after degradation)

        Constraints:
            1. Energy balance:
               e_after[0] = E_initial + p_ch[0]*eta_ch*dt - p_dis[0]/eta_dis*dt
               e_after[t] = e_after[t-1] + p_ch[t]*eta_ch*dt - p_dis[t]/eta_dis*dt  (t >= 1)
            2. Terminal stored energy equality:
               e_after[T-1] = E_initial
            3. Power - binary state linking:
               p_ch[t] <= P_ch_limit * u_ch[t]
               p_dis[t] <= P_dis_limit * u_dis[t]
            4. Mutual exclusivity of operational modes:
               u_ch[t] + u_dis[t] <= 1

    Args:
        prices: Array of day-ahead prices in EUR/MWh for each hour of the delivery date.
        config: Immutable BESS configuration specification.
        delivery_date: String date label (YYYY-MM-DD) for error tracking.
        degradation_cost_eur_per_mwh_eq_cycle: Assumed wear cost in EUR/MWh-equivalent-cycle.

    Returns:
        Dictionary containing optimized vectors and solver telemetry.

    Raises:
        RuntimeError: If the MILP solver fails to find an optimal solution.
    """
    T = len(prices)
    dt = config.timestep_hours
    eta_ch = config.charge_efficiency
    eta_dis = config.discharge_efficiency
    E_nom = config.nominal_energy_capacity_mwh
    E_init = config.initial_soc * E_nom
    E_min = config.soc_min * E_nom
    E_max = config.soc_max * E_nom
    P_ch_limit = min(config.rated_charge_power_mw, config.grid_connection_limit_mw)
    P_dis_limit = min(config.rated_discharge_power_mw, config.grid_connection_limit_mw)

    # 1. Objective vector c (minimize c^T x)
    # Indices:
    # 0..T-1: p_ch
    # T..2T-1: p_dis
    # 2T..3T-1: e_after
    # 3T..4T-1: u_ch
    # 4T..5T-1: u_dis
    c = np.zeros(5 * T)
    c[0:T] = (prices + 0.5 * degradation_cost_eur_per_mwh_eq_cycle * eta_ch) * dt
    c[T : 2 * T] = (-prices + (0.5 * degradation_cost_eur_per_mwh_eq_cycle / eta_dis)) * dt

    # 2. Integrality vector (0: continuous, 1: integer/binary)
    integrality = np.zeros(5 * T)
    integrality[3 * T : 5 * T] = 1

    # 3. Variable bounds
    lb = np.zeros(5 * T)
    ub = np.zeros(5 * T)
    lb[0:T] = 0.0
    ub[0:T] = P_ch_limit
    lb[T : 2 * T] = 0.0
    ub[T : 2 * T] = P_dis_limit
    lb[2 * T : 3 * T] = E_min
    ub[2 * T : 3 * T] = E_max
    lb[3 * T : 5 * T] = 0.0
    ub[3 * T : 5 * T] = 1.0
    bounds = Bounds(lb, ub)

    # 4. Linear Constraints: (4 * T + 1 rows)
    # - T rows: Energy balance
    # - 1 row:  Terminal energy equality
    # - T rows: Charge power linking (p_ch - P_ch_limit * u_ch <= 0)
    # - T rows: Discharge power linking (p_dis - P_dis_limit * u_dis <= 0)
    # - T rows: Mode exclusivity (u_ch + u_dis <= 1)
    num_constraints = 4 * T + 1
    A = np.zeros((num_constraints, 5 * T))
    lhs = np.full(num_constraints, -np.inf)
    rhs = np.full(num_constraints, np.inf)

    row = 0
    # Interval 0: e_after[0] - eta_ch*dt*p_ch[0] + (dt/eta_dis)*p_dis[0] = E_init
    A[row, 2 * T] = 1.0
    A[row, 0] = -eta_ch * dt
    A[row, T] = dt / eta_dis
    lhs[row] = E_init
    rhs[row] = E_init
    row += 1

    # Intervals 1..T-1: e_after[t] - e_after[t-1] - eta_ch*dt*p_ch[t] + (dt/eta_dis)*p_dis[t] = 0
    for t in range(1, T):
        A[row, 2 * T + t] = 1.0
        A[row, 2 * T + t - 1] = -1.0
        A[row, t] = -eta_ch * dt
        A[row, T + t] = dt / eta_dis
        lhs[row] = 0.0
        rhs[row] = 0.0
        row += 1

    # Terminal equality: e_after[T-1] = E_init
    A[row, 2 * T + T - 1] = 1.0
    lhs[row] = E_init
    rhs[row] = E_init
    row += 1

    # Charge power linking: p_ch[t] - P_ch_limit * u_ch[t] <= 0
    for t in range(T):
        A[row, t] = 1.0
        A[row, 3 * T + t] = -P_ch_limit
        rhs[row] = 0.0
        row += 1

    # Discharge power linking: p_dis[t] - P_dis_limit * u_dis[t] <= 0
    for t in range(T):
        A[row, T + t] = 1.0
        A[row, 4 * T + t] = -P_dis_limit
        rhs[row] = 0.0
        row += 1

    # Mode exclusivity: u_ch[t] + u_dis[t] <= 1
    for t in range(T):
        A[row, 3 * T + t] = 1.0
        A[row, 4 * T + t] = 1.0
        rhs[row] = 1.0
        row += 1

    constraints = LinearConstraint(A, lhs, rhs)

    # 5. Solve MILP using HiGHS backend
    res = milp(c=c, integrality=integrality, bounds=bounds, constraints=constraints)

    if not res.success:
        raise RuntimeError(
            f"Optimization failed for delivery date {delivery_date}: "
            f"status={res.status}, message='{res.message}'"
        )

    # Clean small solver residuals (< NUMERICAL_TOLERANCE)
    p_ch_sol = np.where(res.x[0:T] < NUMERICAL_TOLERANCE, 0.0, res.x[0:T])
    p_dis_sol = np.where(res.x[T : 2 * T] < NUMERICAL_TOLERANCE, 0.0, res.x[T : 2 * T])
    e_after_sol = res.x[2 * T : 3 * T]
    u_ch_sol = np.rint(res.x[3 * T : 4 * T]).astype(int)
    u_dis_sol = np.rint(res.x[4 * T : 5 * T]).astype(int)

    return {
        "p_charge": p_ch_sol,
        "p_discharge": p_dis_sol,
        "e_after": e_after_sol,
        "u_charge": u_ch_sol,
        "u_discharge": u_dis_sol,
        "objective_margin_eur": float(-res.fun),
        "solver_status": int(res.status),
        "solver_message": str(res.message),
    }


def simulate_optimized(
    prices_df: pd.DataFrame,
    baseline_df: pd.DataFrame | None = None,
    config: BESSConfig | None = None,
    degradation_cost_eur_per_mwh_eq_cycle: float = 0.0,
    include_degradation_columns: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    """Run ex-post perfect-foresight MILP optimization and continuous physical replay.

    Args:
        prices_df: Validated hourly prices DataFrame for 2024 German delivery dates.
        baseline_df: Optional baseline dispatch DataFrame for daily comparison.
        config: Optional BESS configuration (defaults to BESSConfig()).
        degradation_cost_eur_per_mwh_eq_cycle: Wear penalty rate in EUR/MWh-equivalent-cycle.
        include_degradation_columns: Whether to include degradation metrics in hourly output.

    Returns:
        Tuple containing:
            1. Detailed hourly DataFrame (8,784 rows)
            2. Annual summary KPI dictionary
            3. Daily comparison DataFrame (366 rows)
    """
    if config is None:
        config = BESSConfig()

    unique_dates = prices_df["delivery_date"].unique()
    total_dates = len(unique_dates)

    # Single continuous battery model initialized at start of year (SOC 0.50)
    model = BatteryModel(config)

    hourly_records: list[dict[str, Any]] = []
    daily_records: list[dict[str, Any]] = []

    # Pre-aggregate baseline daily values if available
    baseline_daily_map: dict[str, dict[str, float]] = {}
    if baseline_df is not None:
        for d, grp in baseline_df.groupby("delivery_date"):
            baseline_daily_map[str(d)] = {
                "margin_eur": float(grp["gross_margin_eur"].sum()),
                "efc": float(grp["incremental_efc"].sum()),
                "grid_charge_mwh": float(grp["grid_charge_energy_mwh"].sum()),
                "grid_discharge_mwh": float(grp["grid_discharge_energy_mwh"].sum()),
            }

    annual_milp_objective_margin = 0.0
    successful_days = 0
    max_solver_replay_energy_diff = 0.0

    for d in unique_dates:
        day_prices = prices_df[prices_df["delivery_date"] == d]
        T_day = len(day_prices)
        prices_arr = day_prices["price_eur_per_mwh"].to_numpy(dtype=float)

        # Solve day's MILP
        sol = solve_day_milp(
            prices=prices_arr,
            config=config,
            delivery_date=str(d),
            degradation_cost_eur_per_mwh_eq_cycle=degradation_cost_eur_per_mwh_eq_cycle,
        )
        successful_days += 1
        annual_milp_objective_margin += sol["objective_margin_eur"]

        day_charge = sol["p_charge"]
        day_discharge = sol["p_discharge"]
        day_e_solver = sol["e_after"]
        day_u_charge = sol["u_charge"]
        day_u_discharge = sol["u_discharge"]

        day_replayed_margin = 0.0
        day_grid_charge = 0.0
        day_grid_discharge = 0.0
        day_cell_throughput = 0.0

        for t in range(T_day):
            row = day_prices.iloc[t]
            price = float(row["price_eur_per_mwh"])

            p_ch_req = float(day_charge[t])
            p_dis_req = float(day_discharge[t])

            # Replay through BatteryModel
            step_res = model.step(
                charge_power_mw=p_ch_req,
                discharge_power_mw=p_dis_req,
            )

            # Check if BatteryModel was forced to clip power beyond tolerance
            power_clipped_ch = abs(step_res.actual_charge_power_mw - p_ch_req)
            power_clipped_dis = abs(step_res.actual_discharge_power_mw - p_dis_req)
            if power_clipped_ch > NUMERICAL_TOLERANCE or power_clipped_dis > NUMERICAL_TOLERANCE:
                raise RuntimeError(
                    f"Physical BatteryModel required unexpected power clipping on {d} hour {t}: "
                    f"req_ch={p_ch_req}, act_ch={step_res.actual_charge_power_mw}, "
                    f"req_dis={p_dis_req}, act_dis={step_res.actual_discharge_power_mw}"
                )

            # Financial accounting (GRID-side energy)
            charging_cost = step_res.grid_charge_energy_mwh * price
            discharge_revenue = step_res.grid_discharge_energy_mwh * price
            gross_margin = discharge_revenue - charging_cost

            # Throughput & EFC (CELL-side energy)
            cell_throughput = (
                step_res.cell_charge_energy_mwh + step_res.cell_discharge_energy_mwh
            )
            incremental_efc = cell_throughput / (2.0 * config.nominal_energy_capacity_mwh)

            energy_diff = abs(step_res.energy_after_mwh - day_e_solver[t])
            if energy_diff > max_solver_replay_energy_diff:
                max_solver_replay_energy_diff = energy_diff

            day_replayed_margin += gross_margin
            day_grid_charge += step_res.grid_charge_energy_mwh
            day_grid_discharge += step_res.grid_discharge_energy_mwh
            day_cell_throughput += cell_throughput

            rec = {
                "timestamp_utc": row["timestamp_utc"],
                "timestamp_europe_berlin": row["timestamp_europe_berlin"],
                "delivery_date": str(d),
                "price_eur_per_mwh": price,
                "optimized_charge_power_mw": step_res.actual_charge_power_mw,
                "optimized_discharge_power_mw": step_res.actual_discharge_power_mw,
                "charge_binary": int(day_u_charge[t]),
                "discharge_binary": int(day_u_discharge[t]),
                "grid_charge_energy_mwh": step_res.grid_charge_energy_mwh,
                "grid_discharge_energy_mwh": step_res.grid_discharge_energy_mwh,
                "cell_charge_energy_mwh": step_res.cell_charge_energy_mwh,
                "cell_discharge_energy_mwh": step_res.cell_discharge_energy_mwh,
                "energy_before_mwh": step_res.energy_before_mwh,
                "energy_after_mwh": step_res.energy_after_mwh,
                "soc_before": step_res.soc_before,
                "soc_after": step_res.soc_after,
                "conversion_loss_mwh": step_res.conversion_loss_mwh,
                "charging_cost_eur": charging_cost,
                "discharge_revenue_eur": discharge_revenue,
                "gross_margin_eur": gross_margin,
                "cell_throughput_mwh": cell_throughput,
                "incremental_efc": incremental_efc,
                "solver_energy_after_mwh": float(day_e_solver[t]),
                "solver_vs_replay_energy_difference_mwh": float(energy_diff),
            }
            if include_degradation_columns:
                eq_cyc = cell_throughput / 2.0
                deg_c = eq_cyc * degradation_cost_eur_per_mwh_eq_cycle
                rec["equivalent_cycle_energy_mwh"] = float(eq_cyc)
                rec["degradation_cost_rate_eur_per_mwh_eq_cycle"] = float(degradation_cost_eur_per_mwh_eq_cycle)
                rec["degradation_cost_eur"] = float(deg_c)
                rec["net_margin_after_degradation_eur"] = float(gross_margin - deg_c)

            hourly_records.append(rec)

        # Check terminal energy of the delivery day
        if abs(model.soc - config.initial_soc) > 1e-5:
            raise RuntimeError(
                f"Terminal SOC balance violated on delivery date {d}: "
                f"terminal SOC = {model.soc:.6f}, expected = {config.initial_soc:.6f}"
            )

        # Build daily comparison row
        base_stats = baseline_daily_map.get(str(d), {})
        b_margin = base_stats.get("margin_eur", 0.0)
        b_efc = base_stats.get("efc", 0.0)
        b_ch = base_stats.get("grid_charge_mwh", 0.0)
        b_dis = base_stats.get("grid_discharge_mwh", 0.0)

        abs_improvement = day_replayed_margin - b_margin

        # Percent improvement calculation: safe handling of zero/negative baseline
        if b_margin > 0:
            pct_improvement = (abs_improvement / b_margin) * 100.0
        else:
            # Baseline is negative or zero: undefined percentage
            pct_improvement = None

        min_p = float(np.min(prices_arr))
        max_p = float(np.max(prices_arr))

        daily_records.append(
            {
                "delivery_date": str(d),
                "hours_in_day": T_day,
                "baseline_margin_eur": b_margin,
                "optimized_margin_eur": day_replayed_margin,
                "absolute_improvement_eur": abs_improvement,
                "percent_improvement": pct_improvement,
                "baseline_efc": b_efc,
                "optimized_efc": day_cell_throughput / (2.0 * config.nominal_energy_capacity_mwh),
                "baseline_grid_charge_mwh": b_ch,
                "optimized_grid_charge_mwh": day_grid_charge,
                "baseline_grid_discharge_mwh": b_dis,
                "optimized_grid_discharge_mwh": day_grid_discharge,
                "minimum_price_eur_per_mwh": min_p,
                "maximum_price_eur_per_mwh": max_p,
                "daily_price_spread_eur_per_mwh": max_p - min_p,
            }
        )

    hourly_df = pd.DataFrame(hourly_records)
    daily_df = pd.DataFrame(daily_records)

    # Compute annual totals and metrics
    total_charging_cost = float(hourly_df["charging_cost_eur"].sum())
    total_discharge_revenue = float(hourly_df["discharge_revenue_eur"].sum())
    replayed_gross_margin = float(hourly_df["gross_margin_eur"].sum())

    total_grid_charge = float(hourly_df["grid_charge_energy_mwh"].sum())
    total_grid_discharge = float(hourly_df["grid_discharge_energy_mwh"].sum())
    total_cell_throughput = float(hourly_df["cell_throughput_mwh"].sum())
    annual_efc = float(hourly_df["incremental_efc"].sum())

    realized_rte = total_grid_discharge / total_grid_charge if total_grid_charge > 0 else 0.0

    charging_hours = int((hourly_df["optimized_charge_power_mw"] > NUMERICAL_TOLERANCE).sum())
    discharging_hours = int((hourly_df["optimized_discharge_power_mw"] > NUMERICAL_TOLERANCE).sum())
    active_hours = charging_hours + discharging_hours
    idle_hours = len(hourly_df) - active_hours
    utilization_pct = (active_hours / len(hourly_df)) * 100.0

    neg_price_mask = hourly_df["price_eur_per_mwh"] < 0
    neg_price_total = int(neg_price_mask.sum())
    charge_at_neg = int((neg_price_mask & (hourly_df["optimized_charge_power_mw"] > NUMERICAL_TOLERANCE)).sum())
    discharge_at_neg = int((neg_price_mask & (hourly_df["optimized_discharge_power_mw"] > NUMERICAL_TOLERANCE)).sum())

    total_deg_cost = float((total_cell_throughput / 2.0) * degradation_cost_eur_per_mwh_eq_cycle)
    replayed_net_margin = float(replayed_gross_margin - total_deg_cost)
    obj_replay_diff = abs(annual_milp_objective_margin - replayed_net_margin)

    # Identify DST hours
    m31_hours = len(hourly_df[hourly_df["delivery_date"] == "2024-03-31"])
    o27_hours = len(hourly_df[hourly_df["delivery_date"] == "2024-10-27"])

    summary: dict[str, Any] = {
        "strategy_name": (
            "Ex-Post Perfect-Foresight MILP Optimization"
            if degradation_cost_eur_per_mwh_eq_cycle == 0.0
            else f"Degradation-Aware MILP Optimization ({degradation_cost_eur_per_mwh_eq_cycle:.0f} EUR/MWh)"
        ),
        "strategy_description": (
            "Ex-post perfect-foresight MILP benchmark using realized German "
            "day-ahead prices. Not a deployable trading forecast."
        ),
        "analysis_year": 2024,
        "delivery_days": total_dates,
        "optimized_days_successful": successful_days,
        "optimized_days_failed": 0,
        "initial_soc": config.initial_soc,
        "final_soc": float(model.soc),
        "total_charging_cost_eur": total_charging_cost,
        "total_discharge_revenue_eur": total_discharge_revenue,
        "gross_arbitrage_margin_eur": replayed_gross_margin,
        "total_grid_charge_energy_mwh": total_grid_charge,
        "total_grid_discharge_energy_mwh": total_grid_discharge,
        "total_cell_throughput_mwh": total_cell_throughput,
        "equivalent_full_cycles": annual_efc,
        "realized_round_trip_efficiency": realized_rte,
        "average_soc": float(hourly_df["soc_after"].mean()),
        "minimum_soc": float(hourly_df["soc_after"].min()),
        "maximum_soc": float(hourly_df["soc_after"].max()),
        "charging_hours": charging_hours,
        "discharging_hours": discharging_hours,
        "idle_hours": idle_hours,
        "active_hours": active_hours,
        "utilization_percent": utilization_pct,
        "negative_price_hours_total": neg_price_total,
        "charge_during_negative_price_hours": charge_at_neg,
        "discharge_during_negative_price_hours": discharge_at_neg,
        "milp_objective_margin_eur": annual_milp_objective_margin,
        "replayed_margin_eur": replayed_gross_margin,
        "objective_replay_difference_eur": obj_replay_diff,
        "maximum_solver_replay_energy_difference_mwh": max_solver_replay_energy_diff,
        "spring_dst_day_hours": m31_hours,
        "autumn_dst_day_hours": o27_hours,
        "degradation_cost_rate_eur_per_mwh_eq_cycle": float(degradation_cost_eur_per_mwh_eq_cycle),
        "assumed_degradation_cost_eur": total_deg_cost,
        "net_margin_after_degradation_eur": replayed_net_margin,
    }

    return hourly_df, summary, daily_df


def run_optimized_pipeline() -> None:
    """Execute end-to-end optimization pipeline and write report artifacts."""
    prices_path = PROJECT_ROOT / "data" / "processed" / "de_lu_day_ahead_prices_2024.csv"
    baseline_path = PROJECT_ROOT / "reports" / "baseline_dispatch_2024.csv"
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading prices from {prices_path}...")
    prices_df = pd.read_csv(prices_path)

    baseline_df = None
    if baseline_path.exists():
        print(f"Loading baseline from {baseline_path}...")
        baseline_df = pd.read_csv(baseline_path)

    print("Running MILP optimization and physical replay for 366 delivery dates...")
    hourly_df, summary, daily_df = simulate_optimized(
        prices_df=prices_df,
        baseline_df=baseline_df,
    )

    out_csv = reports_dir / "optimized_dispatch_2024.csv"
    out_json = reports_dir / "optimized_summary_2024.json"
    out_daily = reports_dir / "baseline_vs_optimized_daily_2024.csv"

    print(f"Saving hourly dispatch to {out_csv}...")
    hourly_df.to_csv(out_csv, index=False)

    print(f"Saving summary metrics to {out_json}...")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"Saving daily comparison to {out_daily}...")
    daily_df.to_csv(out_daily, index=False)

    print("\nOptimization Pipeline Completed Successfully.")
    print(f"Annual Gross Arbitrage Margin: {summary['gross_arbitrage_margin_eur']:,.2f} EUR")
    print(f"Total Equivalent Full Cycles:  {summary['equivalent_full_cycles']:,.2f} EFC")
    print(f"Realized Round-Trip Efficiency:{summary['realized_round_trip_efficiency'] * 100:.2f}%")
    print(f"Active Operating Hours:        {summary['active_hours']} / {len(hourly_df)} ({summary['utilization_percent']:.1f}%)")


if __name__ == "__main__":
    run_optimized_pipeline()
