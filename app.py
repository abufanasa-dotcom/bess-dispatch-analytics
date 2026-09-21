"""
German BESS Dispatch & Degradation Analytics — Portfolio Dashboard.

Read-only Streamlit application presenting techno-economic analysis of a 1 MW / 2 MWh
Battery Energy Storage System operating in the German/Luxembourg day-ahead market (2024).

All data, tables, metrics, and figures are loaded strictly from frozen saved outputs
in the reports/ directory. No live optimization, simulation, or data fetching is performed.
"""

import json
from pathlib import Path
from typing import Any, Dict, Tuple

import pandas as pd
import streamlit as st

# Configure page presentation
st.set_page_config(
    page_title="German BESS Dispatch Analytics",
    page_icon="🔋",
    layout="wide",
)

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"


# -----------------------------------------------------------------------------
# Cached Data Loading (Read-Only)
# -----------------------------------------------------------------------------

@st.cache_data
def load_all_reports() -> Dict[str, Any]:
    """Load precomputed report summaries, sensitivity tables, and figures from disk."""
    with open(REPORTS_DIR / "baseline_summary_2024.json", "r", encoding="utf-8") as f:
        baseline_summary = json.load(f)

    with open(REPORTS_DIR / "optimized_summary_2024.json", "r", encoding="utf-8") as f:
        optimized_summary = json.load(f)

    with open(REPORTS_DIR / "degradation_aware_summary_20eur_2024.json", "r", encoding="utf-8") as f:
        deg_summary_20 = json.load(f)

    df_sensitivity = pd.read_csv(REPORTS_DIR / "degradation_sensitivity_2024.csv")
    df_monthly = pd.read_csv(REPORTS_DIR / "monthly_nominal_performance_2024.csv")
    df_daily_20 = pd.read_csv(REPORTS_DIR / "baseline_vs_degradation_aware_daily_20eur_2024.csv")

    return {
        "baseline_summary": baseline_summary,
        "optimized_summary": optimized_summary,
        "deg_summary_20": deg_summary_20,
        "df_sensitivity": df_sensitivity,
        "df_monthly": df_monthly,
        "df_daily_20": df_daily_20,
    }


def get_representative_day_metrics(df_daily_20: pd.DataFrame) -> Tuple[str, pd.Series]:
    """Dynamically determine the delivery day with highest nominal optimized net margin."""
    top_idx = df_daily_20["optimized_net_margin_eur"].idxmax()
    top_day = df_daily_20.loc[top_idx]
    return str(top_day["delivery_date"]), top_day


# -----------------------------------------------------------------------------
# Main Dashboard
# -----------------------------------------------------------------------------

def main():
    data = load_all_reports()
    baseline = data["baseline_summary"]
    opt = data["optimized_summary"]
    nom = data["deg_summary_20"]
    df_sens = data["df_sensitivity"]
    df_monthly = data["df_monthly"]
    df_daily = data["df_daily_20"]

    # Header
    st.title("German BESS Dispatch & Degradation Analytics")
    st.caption("1 MW / 2 MWh battery | German day-ahead market | 2024")

    # Mandatory Disclaimer Banner
    st.info(
        "**Engineering & Modeling Benchmark Disclaimer**  \n"
        "Historical perfect-foresight engineering benchmark using realized SMARD day-ahead prices. "
        "Results are retrospective and are not a live trading strategy or investment advice. "
        "Degradation cost is an economic sensitivity proxy, not an electrochemical State of Health (SOH) model."
    )

    # Top KPI Cards
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric(
            label="Baseline Gross Margin",
            value=f"€{baseline['gross_arbitrage_margin_eur']:,.0f}",
            help="Fixed local-time benchmark (price-blind schedule).",
        )
    with col2:
        st.metric(
            label="Zero-Cost Optimized Gross",
            value=f"€{opt['gross_arbitrage_margin_eur']:,.0f}",
            delta=f"+€{opt['gross_arbitrage_margin_eur'] - baseline['gross_arbitrage_margin_eur']:,.0f}",
            help="Ex-post upper benchmark under perfect foresight with zero cycling penalty.",
        )
    with col3:
        st.metric(
            label="Nominal 20 EUR Net Margin",
            value=f"€{nom['net_margin_after_degradation_eur']:,.0f}",
            delta=f"+€{nom['net_improvement_vs_baseline_eur']:,.0f} vs baseline net @ same €20 cycling-cost assumption",
            help="Nominal optimized net margin (€44,685) vs fixed baseline net margin (€7,876) under the same €20/MWh-eq-cycle assumed cycling cost (net improvement: +€36,809.16).",
        )
    with col4:
        st.metric(
            label="Nominal Annual EFC",
            value=f"{nom['equivalent_full_cycles']:.1f}",
            delta=f"-{nom['efc_reduction_vs_step7_percent']:.1f}% vs 0-cost",
            delta_color="inverse",
            help="Equivalent Full Cycles per year (throughput / (2 * capacity)).",
        )
    with col5:
        st.metric(
            label="EFC Reduction",
            value=f"{nom['efc_reduction_vs_step7_percent']:.2f}%",
            help="Modeled cycling reduction from €0/MWh to €20/MWh assumption.",
        )
    with col6:
        st.metric(
            label="Negative-Price Hours",
            value=f"{opt['negative_price_hours_total']:,} hrs",
            help="Total negative day-ahead settlement hours in Germany/Luxembourg 2024.",
        )

    st.markdown("---")

    # Tabs
    tab_overview, tab_baseline, tab_sens, tab_monthly, tab_rep, tab_methodology = st.tabs([
        "Overview",
        "Baseline vs Optimized",
        "Degradation Sensitivity",
        "Monthly Performance",
        "Representative Day",
        "Methodology & Limitations",
    ])

    # -------------------------------------------------------------------------
    # TAB 1: OVERVIEW
    # -------------------------------------------------------------------------
    with tab_overview:
        st.header("Project Overview & System Configuration")
        c_left, c_right = st.columns([1.2, 1.0])

        with c_left:
            st.subheader("Market Dataset (2024)")
            st.markdown(
                """
                - **Series**: SMARD / Bundesnetzagentur Day-Ahead Spot Wholesale Electricity Prices (Filter 4169, Region DE/LU).
                - **Evaluation Period**: Calendar year 2024 (8,784 hourly intervals, 366 Europe/Berlin delivery days).
                - **Daylight Saving Time**: Full compliance with local German market time, including 23-hour spring and 25-hour autumn transition days.
                - **Negative Prices**: 457 hours with prices below 0.00 EUR/MWh (minimum: -130.90 EUR/MWh).
                - **Objective**: Rigorously evaluate the techno-economic value of grid-scale battery storage under fixed, optimized, and degradation-penalized dispatch rules.
                """
            )

            st.subheader("Key Findings")
            st.markdown(
                """
                1. **Arbitrage Opportunity**: A price-blind fixed baseline generates **€19,588** gross arbitrage margin, while ex-post perfect-foresight MILP recovers **€64,831** (+231%).
                2. **Degradation Trade-Off**: Introducing a nominal **€20/MWh-equivalent-cycle-energy** marginal assumed cycling-cost penalty reduces annual cycling by **32.44% EFC reduction** (from 619.12 to 418.30 EFC) while sacrificing only **5.26%** of gross arbitrage revenue. A 32.44% EFC reduction represents fewer modeled equivalent full cycles and does not establish physical wear reduction, capacity fade prevention, or battery lifetime extension.
                3. **Quality of Throughput**: Realized gross arbitrage value per EFC increases from **€104.72/EFC** (zero penalty) to **€146.83/EFC** (nominal €20 penalty), demonstrating that an assumed cycling-cost penalty effectively eliminates shallow, low-spread cycles.
                4. **Consistent Outperformance**: Across all 366 delivery days, the nominal 20 EUR optimizer beat the baseline on **364 days**, matched on **2 days**, and never underperformed.
                """
            )

        with c_right:
            st.subheader("Battery Configuration")
            spec_df = pd.DataFrame([
                {"Parameter": "Nominal Energy Capacity", "Value": "2.0 MWh"},
                {"Parameter": "Rated Charge / Discharge Power", "Value": "1.0 MW"},
                {"Parameter": "Operating State of Charge (SOC)", "Value": "10.0% – 90.0%"},
                {"Parameter": "Operational Usable Energy Window", "Value": "1.6 MWh"},
                {"Parameter": "Initial & Terminal Daily SOC", "Value": "50.0% (1.0 MWh)"},
                {"Parameter": "One-Way Charge Efficiency", "Value": "95.0%"},
                {"Parameter": "One-Way Discharge Efficiency", "Value": "95.0%"},
                {"Parameter": "Round-Trip Efficiency (AC-to-AC)", "Value": "90.25%"},
                {"Parameter": "Grid Connection Limit", "Value": "1.0 MW"},
            ])
            st.table(spec_df)

        st.subheader("Strategy Comparison Summary")
        comp_df = pd.DataFrame([
            {
                "Strategy": "Fixed Local Baseline",
                "Gross Margin (EUR)": f"€{baseline['gross_arbitrage_margin_eur']:,.2f}",
                "Assumed Cycling Cost (EUR)": "€11,712.00",
                "Net Margin (EUR)": f"€{nom['baseline_net_margin_at_same_cost_eur']:,.2f}",
                "Annual EFC": f"{baseline['equivalent_full_cycles']:.2f}",
                "Utilization": f"{baseline['utilization_percent']:.2f}%",
                "Grid Charge (MWh)": f"{baseline['total_grid_charge_energy_mwh']:.2f}",
                "Grid Discharge (MWh)": f"{baseline['total_grid_discharge_energy_mwh']:.2f}",
            },
            {
                "Strategy": "Zero-Cost Perfect-Foresight MILP",
                "Gross Margin (EUR)": f"€{opt['gross_arbitrage_margin_eur']:,.2f}",
                "Assumed Cycling Cost (EUR)": "€0.00",
                "Net Margin (EUR)": f"€{opt['gross_arbitrage_margin_eur']:,.2f}",
                "Annual EFC": f"{opt['equivalent_full_cycles']:.2f}",
                "Utilization": f"{opt['utilization_percent']:.2f}%",
                "Grid Charge (MWh)": f"{opt['total_grid_charge_energy_mwh']:.2f}",
                "Grid Discharge (MWh)": f"{opt['total_grid_discharge_energy_mwh']:.2f}",
            },
            {
                "Strategy": "Nominal 20 EUR Degradation-Aware MILP",
                "Gross Margin (EUR)": f"€{nom['gross_arbitrage_margin_eur']:,.2f}",
                "Assumed Cycling Cost (EUR)": f"€{nom['assumed_degradation_cost_eur']:,.2f}",
                "Net Margin (EUR)": f"€{nom['net_margin_after_degradation_eur']:,.2f}",
                "Annual EFC": f"{nom['equivalent_full_cycles']:.2f}",
                "Utilization": f"{nom['utilization_percent']:.2f}%",
                "Grid Charge (MWh)": f"{nom['grid_charge_energy_mwh']:.2f}",
                "Grid Discharge (MWh)": f"{nom['grid_discharge_energy_mwh']:.2f}",
            },
        ])
        st.dataframe(comp_df, use_container_width=True, hide_index=True)
        st.caption(
            "Note on baseline net margin: The physical baseline schedule itself does not change; "
            "only the same assumed economic cycling cost (€20/MWh-equivalent-cycle-energy × 585.60 MWh equivalent-cycle energy = €11,712.00) "
            "is applied to calculate baseline net margin (€7,876.28) for fair net-margin comparison against the nominal optimized scenario."
        )

    # -------------------------------------------------------------------------
    # TAB 2: BASELINE VS OPTIMIZED
    # -------------------------------------------------------------------------
    with tab_baseline:
        st.header("Baseline vs Optimized Dispatch Performance")
        st.markdown(
            """
            - **Fixed Baseline**: A transparent reference schedule with predetermined, price-blind action hours:
              - Charge at 03:00 Europe/Berlin
              - Discharge at 18:00 Europe/Berlin
              - Discharge at 19:00 Europe/Berlin
              - Charge at 23:00 Europe/Berlin to return to the 50% terminal SOC target
              - All other hours idle
              Because action hours are fixed and price-blind regardless of realized market spreads, the baseline incurs negative daily margins on adverse spread days.
            - **Ex-Post MILP**: Formulated as a Mixed-Integer Linear Program solved with HiGHS, with complete realization of day-ahead prices across each daily delivery horizon.
            - *Note*: The zero-cost optimizer serves as a theoretical gross-value upper benchmark under model assumptions, not a deployable trading forecast.
            """
        )

        b_col1, b_col2, b_col3, b_col4 = st.columns(4)
        with b_col1:
            st.metric("Baseline Gross Margin", f"€{baseline['gross_arbitrage_margin_eur']:,.2f}")
            st.metric("Baseline Annual EFC", f"{baseline['equivalent_full_cycles']:.2f}")
        with b_col2:
            st.metric("Optimized Gross Margin", f"€{opt['gross_arbitrage_margin_eur']:,.2f}")
            st.metric("Optimized Annual EFC", f"{opt['equivalent_full_cycles']:.2f}")
        with b_col3:
            st.metric(
                "Absolute Improvement",
                f"+€{opt['gross_arbitrage_margin_eur'] - baseline['gross_arbitrage_margin_eur']:,.2f}",
            )
            st.metric("Baseline Utilization", f"{baseline['utilization_percent']:.2f}%")
        with b_col4:
            pct_imp = (opt['gross_arbitrage_margin_eur'] / baseline['gross_arbitrage_margin_eur'] - 1.0) * 100.0
            st.metric("Relative Improvement", f"+{pct_imp:.2f}%")
            st.metric("Optimized Utilization", f"{opt['utilization_percent']:.2f}%")

        fig4_path = FIGURES_DIR / "baseline_vs_nominal_daily.png"
        if fig4_path.exists():
            st.image(str(fig4_path), caption="Daily Comparison: Fixed Baseline vs 20 EUR Degradation-Aware Optimized Net Margin across 366 Days", use_container_width=True)

    # -------------------------------------------------------------------------
    # TAB 3: DEGRADATION SENSITIVITY
    # -------------------------------------------------------------------------
    with tab_sens:
        st.header("Degradation-Cost Sensitivity Analysis")
        st.markdown(
            """
            Because physical battery cycling incurs degradation, we evaluate dispatch response under four assumed
            marginal cycling penalty levels: **0, 10, 20, and 30 EUR / MWh-equivalent-cycle-energy** (where equivalent-cycle energy = cell throughput / 2).
            
            *Important*: These rates represent **assumed cycling costs** for economic dispatch dampening. They do not constitute an electrochemical SOH or capacity fade model.
            """
        )

        display_sens = df_sens[[
            "degradation_cost_rate_eur_per_mwh_eq_cycle",
            "gross_arbitrage_margin_eur",
            "equivalent_full_cycles",
            "assumed_degradation_cost_eur",
            "net_margin_after_degradation_eur",
            "gross_value_per_efc_eur",
            "utilization_percent",
        ]].copy()
        display_sens.columns = [
            "Assumed Cost Rate (EUR/MWh-eq-cycle)",
            "Gross Margin (EUR)",
            "Annual EFC",
            "Assumed Degradation Cost (EUR)",
            "Net Margin (EUR)",
            "Gross Arbitrage Value / EFC (EUR/EFC)",
            "Utilization (%)",
        ]
        st.dataframe(
            display_sens.style.format({
                "Assumed Cost Rate (EUR/MWh-eq-cycle)": "{:.1f}",
                "Gross Margin (EUR)": "€{:,.2f}",
                "Annual EFC": "{:.2f}",
                "Assumed Degradation Cost (EUR)": "€{:,.2f}",
                "Net Margin (EUR)": "€{:,.2f}",
                "Gross Arbitrage Value / EFC (EUR/EFC)": "€{:,.2f}",
                "Utilization (%)": "{:.2f}%",
            }),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Economic Sensitivity Visualizations")
        col_fig1, col_fig2 = st.columns(2)
        fig1_path = FIGURES_DIR / "degradation_sensitivity_margin.png"
        fig2_path = FIGURES_DIR / "degradation_sensitivity_efc.png"
        with col_fig1:
            if fig1_path.exists():
                st.image(str(fig1_path), caption="Arbitrage Value vs Assumed Cycling Cost", use_container_width=True)
        with col_fig2:
            if fig2_path.exists():
                st.image(str(fig2_path), caption="Battery Cycling Response to Assumed Degradation Cost", use_container_width=True)

    # -------------------------------------------------------------------------
    # TAB 4: MONTHLY PERFORMANCE
    # -------------------------------------------------------------------------
    with tab_monthly:
        st.header("Monthly Nominal Dispatch Performance (20 EUR Scenario)")
        st.markdown(
            "Monthly aggregation of nominal 20 EUR/MWh-eq-cycle dispatch based on Europe/Berlin delivery dates."
        )

        best_m = df_monthly.loc[df_monthly["net_margin_eur"].idxmax()]
        worst_m = df_monthly.loc[df_monthly["net_margin_eur"].idxmin()]
        max_efc_m = df_monthly.loc[df_monthly["equivalent_full_cycles"].idxmax()]
        min_efc_m = df_monthly.loc[df_monthly["equivalent_full_cycles"].idxmin()]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Best Month (Net Margin)", f"{best_m['month']}", f"€{best_m['net_margin_eur']:,.2f}")
        m2.metric("Worst Month (Net Margin)", f"{worst_m['month']}", f"€{worst_m['net_margin_eur']:,.2f}")
        m3.metric("Highest Cycling Month", f"{max_efc_m['month']}", f"{max_efc_m['equivalent_full_cycles']:.1f} EFC")
        m4.metric("Lowest Cycling Month", f"{min_efc_m['month']}", f"{min_efc_m['equivalent_full_cycles']:.1f} EFC")

        fig3_path = FIGURES_DIR / "monthly_nominal_performance.png"
        if fig3_path.exists():
            st.image(str(fig3_path), caption="Monthly Arbitrage Margins and Cycling Progression", use_container_width=True)

        st.subheader("12-Month Performance Table")
        st.dataframe(
            df_monthly.style.format({
                "gross_margin_eur": "€{:,.2f}",
                "degradation_cost_eur": "€{:,.2f}",
                "net_margin_eur": "€{:,.2f}",
                "equivalent_full_cycles": "{:.2f}",
                "grid_charge_energy_mwh": "{:.2f} MWh",
                "grid_discharge_energy_mwh": "{:.2f} MWh",
            }),
            use_container_width=True,
            hide_index=True,
        )

    # -------------------------------------------------------------------------
    # TAB 5: REPRESENTATIVE DAY
    # -------------------------------------------------------------------------
    with tab_rep:
        st.header("Representative High-Value Delivery Day")
        rep_date, top_day = get_representative_day_metrics(df_daily)

        st.markdown(
            f"The representative day is dynamically identified as **{rep_date}**, which recorded the highest "
            f"single-day nominal optimized net margin across all 366 delivery days in 2024."
        )

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Optimized Net Margin", f"€{top_day['optimized_net_margin_eur']:,.2f}")
        r2.metric("Baseline Net Margin", f"€{top_day['baseline_net_margin_eur']:,.2f}")
        r3.metric("Net Improvement", f"+€{top_day['net_improvement_vs_baseline_eur']:,.2f}")
        r4.metric("Daily Price Spread", f"€{top_day['daily_price_spread_eur_per_mwh']:,.2f}/MWh")

        fig5_path = FIGURES_DIR / "representative_day_dispatch.png"
        if fig5_path.exists():
            st.image(str(fig5_path), caption=f"Hourly Day-Ahead Price, Dispatch Power, and SOC Trajectory ({rep_date})", use_container_width=True)

        st.markdown(
            """
            ### What the Dispatch Demonstrates:
            - **Optimized Arbitrage Timing**: The battery charges during off-peak morning and early afternoon price dips and discharges during morning and evening peak hours.
            - **Strict Physical Feasibility**: Charge power and discharge power never exceed 1.0 MW, simultaneous charging and discharging is avoided, and SOC remains strictly within 10% to 90%.
            - **Midnight Terminal Equality**: BESS completes the day with terminal SOC equal to the initial 50.0% boundary.
            - *Clarification*: This ex-post dispatch demonstrates what is physically feasible within the simplified historical benchmark, not a predictive forecasting model or live trading strategy.
            """
        )

    # -------------------------------------------------------------------------
    # TAB 6: METHODOLOGY & LIMITATIONS
    # -------------------------------------------------------------------------
    with tab_methodology:
        st.header("Methodology, Modeling Scope & Engineering Limitations")

        st.subheader("Methodology Summary")
        st.markdown(
            """
            1. **Data Ingestion**: Programmatic acquisition and strict schema validation of German SMARD day-ahead electricity prices for 2024.
            2. **Time-Series Integrity**: Exact UTC timestamps mapped to Europe/Berlin market delivery days, safely preserving 23-hour spring and 25-hour autumn DST transitions.
            3. **Physics-Based Battery Engine**: Object-oriented physical battery model implementing asymmetric charging and discharging efficiencies, strict SOC boundaries, and energy conservation.
            4. **Fixed Baseline Reference**: Transparent, price-blind local-time schedule (charge at 03:00, discharge at 18:00 and 19:00, charge at 23:00 to return to 50% terminal SOC target, all other hours idle) establishing an un-optimized engineering benchmark.
            5. **Mixed-Integer Linear Programming**: Daily ex-post MILP formulated with SciPy / HiGHS solver to maximize gross or net margin while preventing simultaneous charging/discharging.
            6. **Physical Simulation Replay**: Every hourly schedule solved by MILP is independently replayed through BatteryModel to verify mathematical and physical consistency within numerical tolerance (< 1e-10 EUR difference). Solver/simulation consistency verifies internal mathematical correctness and is not a real-world commercial validation.
            7. **Degradation Sensitivity**: Multi-scenario evaluation of marginal cycling cost penalties (€0, €10, €20, €30/MWh-eq-cycle).
            """
        )

        st.subheader("Model Limitations & Disclaimers")
        st.warning(
            "**Core Engineering Limitations:**\n\n"
            "- **perfect foresight**: Ex-post optimization uses realized settlement prices known in advance. Real-world commercial trading requires forecasting and faces market risk.\n"
            "- **wholesale energy-only economics**: Considers day-ahead wholesale arbitrage only; excludes intraday continuous trading, frequency containment reserves (FCR), and aFRR balancing markets.\n"
            "- **no taxes / grid tariffs / market fees**: Excludes grid connection tariffs, network levies, trading venue fees, and corporate taxation.\n"
            "- **no imbalance costs**: Assumes zero balancing group deviation penalties.\n"
            "- **no ancillary-service revenue**: Revenue stacking from primary and secondary frequency reserves is omitted.\n"
            "- **simplified economic degradation proxy**: An economic cycling-cost proxy is modeled as a linear cost heuristic per MWh-equivalent-cycle-energy for dispatch dampening; it does not represent physical wear, capacity fade, or battery lifetime extension.\n"
            "- **no electrochemical SOH model**: The model does not simulate SEI layer growth, lithium plating, impedance rise, or capacity fade.\n"
            "- **no calendar ageing**: Rest-period degradation and calendar fade are excluded.\n"
            "- **no thermal model**: Battery ambient temperature and cell thermal dynamics are not simulated.\n"
            "- **no forecast uncertainty**: Analysis does not account for price forecast errors or bid rejection.\n"
            "- **no battery CAPEX / full project economics**: Focuses purely on operating arbitrage margins; project Capex, financing, land lease, and O&M costs are omitted."
        )

        st.info(
            "**Key Principles:**\n\n"
            "- *This project does not predict electrochemical State of Health.*\n"
            "- *Historical optimization results are not forecasts of future revenue.*"
        )


if __name__ == "__main__":
    main()
