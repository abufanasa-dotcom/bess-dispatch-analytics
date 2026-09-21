# Project Specification: BESS Dispatch Analytics

**Battery Energy Storage System Performance, Dispatch & Degradation Analysis**

---

## 1. Project Objective

The objective of this project is to build a rigorous, fully reproducible Python analysis of a grid-scale Battery Energy Storage System (BESS) operating in the German day-ahead electricity market across German delivery days in calendar year 2024 (from `2024-01-01 00:00:00` Europe/Berlin inclusive through `2025-01-01 00:00:00` Europe/Berlin exclusive).

The project evaluates:
1. **Battery Charging/Discharging Behavior**: Physical power profiles and operational states over time.
2. **State of Charge (SOC)**: Dynamic tracking of stored energy relative to operational boundaries.
3. **Round-Trip Efficiency (RTE)**: Energy conversion losses across charging and discharging stages.
4. **Energy Throughput**: Total cell-side energy processed through the system.
5. **Equivalent Full Cycles (EFC)**: Standardized battery utilization metric.
6. **Electricity-Price Arbitrage**: Capturing value from temporal wholesale price spreads and negative-price hours.
7. **Technical Operating Constraints**: Strict adherence to power limits, capacity bounds, and non-simultaneity.
8. **Degradation-Aware Dispatch Strategy**: Incorporating battery wear cost assumptions into scheduling decisions.
9. **Dispatch Comparison**: Quantitative benchmarking of baseline heuristic dispatch versus mathematical optimization.

---

## 2. Initial BESS Assumptions & System Parameters

The analysis models a front-of-the-meter (FTM) utility-scale lithium-ion battery energy storage system. All parameters must be modular and configurable (e.g., encapsulated in a dedicated configuration class or schema) rather than hard-coded across scripts:

| Parameter | Value | Unit | Notes / Definition |
| :--- | :--- | :--- | :--- |
| **Nominal Energy Capacity ($E_{\text{nom}}$)** | 2.0 | MWh | Total nameplate energy capacity (SOC denominator) |
| **Rated Power ($P_{\text{rated}}$)** | 1.0 | MW | Nominal continuous active power rating |
| **Duration (C-rate)** | 2.0 | hours | 0.5 C rate ($E_{\text{nom}} / P_{\text{rated}}$) |
| **Minimum State of Charge ($\text{SOC}_{\min}$)** | 10 | % | Lower operational reserve buffer ($0.10 \times E_{\text{nom}} = 0.2\,\text{MWh}$) |
| **Maximum State of Charge ($\text{SOC}_{\max}$)** | 90 | % | Upper operational reserve buffer ($0.90 \times E_{\text{nom}} = 1.8\,\text{MWh}$) |
| **Operational Energy Window** | 1.6 | MWh | Usable operational range: $E_{\text{nom}} \times (\text{SOC}_{\max} - \text{SOC}_{\min})$ |
| **Initial / Delivery-Day Start SOC ($\text{SOC}_{\text{start}}$)** | 50 | % | Starting state of charge ($0.50 \times E_{\text{nom}} = 1.0\,\text{MWh}$) |
| **Terminal SOC Target ($\text{SOC}_{\text{end}}$)** | 50 | % | End-of-horizon condition: $\text{SOC}_{\text{end}} = \text{SOC}_{\text{start}}$ |
| **Maximum Charge Power ($P_{\text{ch, max}}$)** | 1.0 | MW | Peak charging rate at grid connection point |
| **Maximum Discharge Power ($P_{\text{dis, max}}$)** | 1.0 | MW | Peak discharging rate at grid connection point |
| **Charge Efficiency ($\eta_{\text{ch}}$)** | 95.0 | % | Grid-to-cell energy conversion efficiency |
| **Discharge Efficiency ($\eta_{\text{dis}}$)** | 95.0 | % | Cell-to-grid energy conversion efficiency |
| **Round-Trip Efficiency ($\text{RTE}$)** | 90.25 | % | $\text{RTE} = \eta_{\text{ch}} \times \eta_{\text{dis}} = 0.95 \times 0.95$ |
| **Grid Connection Limit ($P_{\text{grid}}$)** | 1.0 | MW | Maximum active power interchange with the grid |
| **Simultaneous Charge/Discharge** | Disallowed | — | Strictly mutually exclusive: $P_{\text{ch}, t} \cdot P_{\text{dis}, t} = 0$ |
| **Time Resolution ($\Delta t$)** | 1.0 | hour | Hourly operational time-steps |

> [!IMPORTANT]
> **Capacity Definition**: The 2.0 MWh figure represents the **nominal energy capacity** ($E_{\text{nom}}$), **not** the usable energy capacity. With $\text{SOC}_{\min} = 10\%$ and $\text{SOC}_{\max} = 90\%$, the physical operational energy window is $2.0\,\text{MWh} \times (0.90 - 0.10) = 1.6\,\text{MWh}$. The dynamic SOC balance equation strictly uses $E_{\text{nom}} = 2.0\,\text{MWh}$ as its denominator.

---

## 3. Market Data & Price Treatment

### Primary Market Series Configuration
- **Primary Market**: German/Luxembourg (DE-LU) Bidding Zone Day-Ahead Electricity Market.
- **Primary Data Source**: SMARD platform hosted by the German Federal Network Agency (*Bundesnetzagentur* - BNetzA).
- **SMARD Filter ID**: `4169`
- **Series Name**: Marktpreis Deutschland/Luxemburg (Day-ahead wholesale electricity price).
- **API Region Endpoint**: `DE`
- **Resolution**: Hourly (`hour`).
- **Currency / Unit**: EUR/MWh (€/MWh).
- **Analysis Period (German Market Year)**:
  - Local market time: `2024-01-01 00:00:00` Europe/Berlin inclusive through `2025-01-01 00:00:00` Europe/Berlin exclusive.
  - Canonical UTC interval: `2023-12-31T23:00:00Z` inclusive through `2024-12-31T23:00:00Z` exclusive.
  - First UTC timestamp: `2023-12-31T23:00:00Z` (`2024-01-01T00:00:00+01:00`).
  - Last UTC timestamp: `2024-12-31T22:00:00Z` (`2024-12-31T23:00:00+01:00`).
  - Total observations: Exactly 8,784 hourly intervals across 366 German delivery days.

### Market-Day Definition & Daylight Saving Time (DST) Handling
- **Canonical Storage**: All timestamps are stored, indexed, and processed internally in **UTC** (`timestamp_utc`) to maintain monotonic continuity.
- **German Delivery Days**: For dispatch scheduling and market grouping, timestamps are mapped to `Europe/Berlin` to determine the local `delivery_date`.
- **Variable Horizon Lengths on DST Days**:
  - German local delivery days are not uniformly 24 hours.
  - **Spring DST Transition (2024-03-31)**: Contains **23 hourly observations** (clocks advance from 02:00 to 03:00 CEST).
  - **Autumn DST Transition (2024-10-27)**: Contains **25 hourly observations** (clocks fall back from 03:00 to 02:00 CET). The repeated 02:00 clock hour is legitimate; it has distinct UTC timestamps and distinct UTC offsets (`+02:00` vs `+01:00`) and is never treated as a duplicate.
  - **Standard Delivery Days (364 days)**: Each contains exactly 24 hourly observations.
  - Total: $364 \times 24 + 23 + 25 = 8,784$ hours across 366 delivery days.

### Negative Price Mechanics
- **Unclipped Preservation**: Negative wholesale electricity prices are preserved exactly as published by SMARD and EPEX SPOT. They must **never** be clipped to zero.
- **Economic Mechanism**: In this simplified wholesale-market model, charging during a negative-price hour ($\lambda_t < 0$) produces a negative charging cost (the asset is effectively paid to consume energy from the grid). Discharging during a negative price hour incurs a financial cost.
- **Optimization Response**: The mathematical optimization model will naturally leverage negative-price intervals as high-value charging opportunities, subject to SOC availability and power limits.

### Market Cost Scope & Exclusions
The primary economic analysis focuses purely on wholesale day-ahead energy-arbitrage value. To maintain transparency, the primary model explicitly **excludes**:
- Grid fees / network tariffs (*Netzentgelte*)
- Concession fees, statutory surcharges, and green-energy levies (e.g., *KWKG-Umlage*, *StromNEV-Umlage*)
- Electricity taxes (*Stromsteuer*)
- Wholesale exchange transaction and clearing fees
- Balancing / imbalance settlement charges (*Ausgleichsenergie*)
- Ancillary service revenues (FCR, aFRR, mFRR)
- Capacity market or network security redispatch mechanisms

---

## 4. Baseline Dispatch Strategy

To quantify the economic and operational uplift delivered by mathematical optimization, the project establishes a transparent, fixed local-time engineering benchmark:
- **Strategy Philosophy**: The baseline schedule is deliberately simple, deterministic, and static. It does not select operating hours based on realized or forecasted electricity prices. It provides an intuitive, physically sound engineering reference that reflects conventional time-of-use operational heuristics without perfect foresight.
- **Fixed Daily Schedule (Europe/Berlin Local Time)**:
  - **03:00 local**: Request charging power $P_{\text{ch}} = 1.0\,\text{MW}$ (typical overnight low-demand window).
  - **18:00 local**: Request discharge power $P_{\text{dis}} = 1.0\,\text{MW}$ (early evening peak demand window).
  - **19:00 local**: Request discharge power $P_{\text{dis}} = 1.0\,\text{MW}$ (evening peak continuation, throttled by $\text{SOC}_{\min}$).
  - **23:00 local**: Request charging power $P_{\text{ch}} = 1.0\,\text{MW}$ targeting recovery to daily baseline $\text{SOC}_{\text{start}} = 50\%$.
  - **All other hours**: System remains idle ($P_{\text{ch}} = 0, P_{\text{dis}} = 0$).
- **Expected Daily Physical Dynamics**:
  - Start of delivery day: $\text{SOC} = 0.50$ ($1.0\,\text{MWh}$ stored).
  - 03:00: Charges from 0.50 to 0.90 ($\text{SOC}_{\max}$). Headroom $= 0.8\,\text{MWh}$ cell energy, requiring $0.8 / 0.95 \approx 0.8421\,\text{MW}$ actual grid charge.
  - 18:00: Discharges 1.0 MW grid ($1.0 / 0.95 \approx 1.0526\,\text{MWh}$ cell energy), lowering SOC to $\approx 0.3737$.
  - 19:00: Discharges remaining cell energy above $\text{SOC}_{\min} = 0.10$ ($0.5474\,\text{MWh}$ cell), delivering $0.5474 \times 0.95 = 0.5200\,\text{MW}$ grid discharge to reach $\text{SOC} = 0.10$.
  - 23:00: Charges from 0.10 back to 0.50 baseline. Cell energy needed $= 0.8\,\text{MWh}$, drawing $0.8 / 0.95 \approx 0.8421\,\text{MW}$ actual grid charge to end the day at exactly $\text{SOC} = 0.50$.
- **Cycle & Throughput Metrics**:
  - Daily cell throughput: $0.8\,\text{MWh} \text{ (ch)} + 1.6\,\text{MWh} \text{ (dis)} + 0.8\,\text{MWh} \text{ (ch)} = 3.2\,\text{MWh/day}$.
  - Daily EFC: Under the nominal capacity convention ($\text{EFC} = \text{Throughput}_{\text{cell}} / [2 \times E_{\text{nom}}]$), one complete $10\% \leftrightarrow 90\%$ operational window sweep ($1.6\,\text{MWh}$ charge $+ 1.6\,\text{MWh}$ discharge) corresponds to $3.2 / 4.0 = 0.80\,\text{EFC/day}$.
  - Annual expected EFC: $366 \times 0.80 = 292.8\,\text{EFC}$.
- **Benchmarking Role**: Provides a completely un-optimized, zero-foresight baseline. Mathematical optimization (MILP) in Step 7 will be evaluated directly against this baseline to isolate the pure value of optimization.

---

## 5. Optimized Dispatch Strategy

A mixed-integer linear programming (MILP) formulation that maximizes net day-ahead market arbitrage value over local German market delivery days.

### Optimization Framework & Solver
- **Optimization Library**: `scipy.optimize.milp`
- **Solver Backend**: **HiGHS** (high-performance simplex/interior-point/branch-and-bound solver integrated directly into SciPy).
- **Binary Variables**: Binary operational state indicators ($u_{\text{ch}, t}, u_{\text{dis}, t} \in \{0, 1\}$) are utilized to enforce strict mutual exclusivity between charging and discharging modes.

### Optimization Horizon & Terminal Conditions
- **One Optimization Horizon per Europe/Berlin Delivery Date**:
  - Each German delivery date $d \in \{1, \dots, 366\}$ is optimized independently across its $T_d$ hourly intervals ($t = 1, \dots, T_d$).
  - For standard days: $T_d = 24$.
  - For spring DST transition (2024-03-31): $T_d = 23$.
  - For autumn DST transition (2024-10-27): $T_d = 25$.
- **Initial Condition**: Each delivery-day run begins at $\text{SOC}_{\text{start}} = 50\%$ ($1.0\,\text{MWh}$ in storage).
- **Terminal Equality Constraint**:
  $$\text{SOC}_{T_d} = \text{SOC}_{\text{start}} = 50\%$$
  This condition is strictly enforced for every local delivery day regardless of whether that day contains 23, 24, or 25 hours. It guarantees energy balance neutrality across daily runs, preventing the optimizer from creating artificial paper profits by systematically draining the battery at the end of the optimization window.
- **Ex-Post Perfect-Foresight Nature**: Optimization against realized day-ahead prices is explicitly documented as a theoretical upper-bound benchmark under perfect foresight, not a live algorithmic trading system.

### Mathematical Formulation

#### Objective Function
$$\max \sum_{t=1}^{T_d} \left( P_{\text{dis}, t} \cdot \lambda_t - P_{\text{ch}, t} \cdot \lambda_t - C_{\text{deg}} \cdot \left[ P_{\text{ch}, t} \cdot \eta_{\text{ch}} + \frac{P_{\text{dis}, t}}{\eta_{\text{dis}}} \right] \cdot \frac{1}{2} \right) \cdot \Delta t$$
where:
- $\lambda_t$: Day-ahead price at hour $t$ of delivery day $d$ (EUR/MWh)
- $P_{\text{ch}, t}, P_{\text{dis}, t}$: Charging and discharging power at grid interface (MW)
- $C_{\text{deg}}$: Assumed degradation cost per MWh of equivalent cycle energy (EUR/MWh)
- $\Delta t = 1.0\,\text{h}$
- $T_d \in \{23, 24, 25\}$: Delivery day horizon length

#### Constraints
1. **Dynamic State of Charge Balance**:
   $$\text{SOC}_t = \text{SOC}_{t-1} + \frac{P_{\text{ch}, t} \cdot \eta_{\text{ch}} \cdot \Delta t}{E_{\text{nom}}} - \frac{P_{\text{dis}, t} \cdot \Delta t}{\eta_{\text{dis}} \cdot E_{\text{nom}}} \quad \forall t \in \{1, \dots, T_d\}$$
2. **SOC Operational Range**:
   $$0.10 \le \text{SOC}_t \le 0.90 \quad \forall t \in \{1, \dots, T_d\}$$
3. **Power Limits with Binary Interlocking**:
   $$0 \le P_{\text{ch}, t} \le P_{\text{ch, max}} \cdot u_{\text{ch}, t} \quad \forall t$$
   $$0 \le P_{\text{dis}, t} \le P_{\text{dis, max}} \cdot u_{\text{dis}, t} \quad \forall t$$
   $$u_{\text{ch}, t} + u_{\text{dis}, t} \le 1, \quad u_{\text{ch}, t}, u_{\text{dis}, t} \in \{0, 1\} \quad \forall t$$
4. **Grid Interconnection Limit**:
   $$P_{\text{ch}, t} \le P_{\text{grid}}, \quad P_{\text{dis}, t} \le P_{\text{grid}} \quad \forall t$$
5. **Terminal SOC Equality**:
   $$\text{SOC}_{T_d} = \text{SOC}_{\text{start}} = 0.50$$

### Step 7 Implementation & Physical Replay Verification
- **Gross Benchmark Formulation ($C_{\text{deg}} = 0$)**: Step 7 calculates the upper-bound gross energy-arbitrage value before applying degradation costs. The objective function reduces purely to wholesale energy revenue minus charging cost:
  $$\max \sum_{t=1}^{T_d} \left( P_{\text{dis}, t} \cdot \lambda_t - P_{\text{ch}, t} \cdot \lambda_t \right) \cdot \Delta t$$
- **Solver Representation**: Solved via `scipy.optimize.milp` using decision vector $x = [p_{\text{ch}}, p_{\text{dis}}, e_{\text{after}}, u_{\text{ch}}, u_{\text{dis}}]^T \in \mathbb{R}^{5 T_d}$ with minimization vector $c = [+\lambda \Delta t, -\lambda \Delta t, \mathbf{0}, \mathbf{0}, \mathbf{0}]^T$ and $4 T_d + 1$ linear constraints.
- **Mandatory Physical Replay**: Every hourly power recommendation from the MILP solver is replayed continuously through a single `BatteryModel` across the full year starting at $\text{SOC}_0 = 0.50$. Replay verifies that no physical power or SOC boundaries are violated and that solver-predicted stored energy matches actual cell energy within numerical tolerance ($< 10^{-15}\,\text{MWh}$).

---

## 6. Degradation Modeling & Sensitivity Scenarios

### Degradation Metric & Accounting Definitions
The project adopts an unambiguous, cell-side throughput accounting model:
- **Cell-Side Energy Throughput**:
  $$\text{Throughput}_{\text{cell}} = \sum_{t=1}^T \left( P_{\text{ch}, t} \cdot \eta_{\text{ch}} \cdot \Delta t + \frac{P_{\text{dis}, t}}{\eta_{\text{dis}}} \cdot \Delta t \right)$$
  $$\text{cell\_throughput\_mwh} = \text{cell\_charge\_energy\_mwh} + \text{cell\_discharge\_energy\_mwh}$$
- **Equivalent-Cycle Energy**:
  $$\text{equivalent\_cycle\_energy\_mwh} = \frac{\text{cell\_throughput\_mwh}}{2}$$
  > [!IMPORTANT]
  > **Bookkeeping Distinction**: Equivalent-cycle energy is **NOT** a physical one-way energy flow. It is a normalized bookkeeping metric derived from total two-way cell throughput to represent the full-cycle equivalent volume.
- **Equivalent Full Cycles (EFC)**:
  $$\text{EFC} = \frac{\text{equivalent\_cycle\_energy\_mwh}}{E_{\text{nom}}} = \frac{\text{cell\_throughput\_mwh}}{2 \times E_{\text{nom}}}$$
  *Example*: For a complete $0\% \to 100\% \to 0\%$ cycle of a $2.0\,\text{MWh}$ nominal battery:
  - Cell throughput = $4.0\,\text{MWh}$ ($2.0\,\text{MWh}$ charge $+ 2.0\,\text{MWh}$ discharge)
  - Equivalent-cycle energy = $2.0\,\text{MWh}$
  - $\text{EFC} = 2.0 / 2.0 = 1.0\,\text{EFC}$

### Degradation Cost Definition & Objective Function
Degradation wear is penalized directly within the MILP objective using a linear cost rate $c_{\text{deg}}$ expressed in **EUR per MWh of equivalent-cycle energy**:
- For each interval $t$:
  $$\text{equivalent\_cycle\_energy\_mwh}_t = 0.5 \times \left( P_{\text{ch}, t} \cdot \eta_{\text{ch}} \cdot \Delta t + \frac{P_{\text{dis}, t}}{\eta_{\text{dis}}} \cdot \Delta t \right)$$
  $$\text{degradation\_cost\_eur}_t = c_{\text{deg}} \times \text{equivalent\_cycle\_energy\_mwh}_t$$
- **Net Optimization Objective**:
  $$\max \sum_{t=1}^{T_d} \left( P_{\text{dis}, t} \cdot \lambda_t \cdot \Delta t - P_{\text{ch}, t} \cdot \lambda_t \cdot \Delta t - c_{\text{deg}} \cdot 0.5 \cdot \left[ P_{\text{ch}, t} \cdot \eta_{\text{ch}} + \frac{P_{\text{dis}, t}}{\eta_{\text{dis}}} \right] \cdot \Delta t \right)$$

### Degradation Cost Sensitivity Scenarios
The project evaluates four discrete sensitivity scenarios across all 366 German delivery dates:
- **Scenario A (0 EUR/MWh-equivalent-cycle-energy)**: Zero degradation penalty (pure gross energy arbitrage, identical to Step 7).
- **Scenario B (10 EUR/MWh-equivalent-cycle-energy)**: Low degradation penalty scenario.
- **Scenario C (20 EUR/MWh-equivalent-cycle-energy)**: **Nominal portfolio scenario** (representative commercial benchmark).
- **Scenario D (30 EUR/MWh-equivalent-cycle-energy)**: High degradation penalty scenario.

> [!CAUTION]
> **Modeling Assumption Disclaimer**: This economic degradation cost is an operational modeling assumption used to filter out low-margin, high-wear cycle opportunities. It is **NOT** a measured battery degradation model, electrochemical State of Health (SOH) prediction, calendar aging model, temperature-dependent model, warranty contract, or replacement-cost forecast.

---

## 7. Key Output KPIs

For both baseline and optimized dispatches across all degradation scenarios, the simulation calculates:

### Financial KPIs (Wholesale Day-Ahead Arbitrage Only)
- **Gross Charging Cost (EUR)**: $\sum (P_{\text{ch}, t} \cdot \lambda_t \cdot \Delta t)$
- **Gross Discharge Revenue (EUR)**: $\sum (P_{\text{dis}, t} \cdot \lambda_t \cdot \Delta t)$
- **Gross Arbitrage Margin (EUR)**: Discharge Revenue minus Charging Cost
- **Assumed Degradation Cost (EUR)**: $C_{\text{deg}} \times \frac{\text{Throughput}_{\text{cell}}}{2}$
- **Net Margin after Assumed Degradation (EUR)**: Gross Arbitrage Margin minus Assumed Degradation Cost
- **Specific Profitability**: EUR/MW-rated/year and EUR/MWh-nominal/year
- **Optimization Uplift**: Absolute gain (EUR) and relative gain (%) compared to the baseline

### Technical & Operational KPIs
- **Total Energy Charged at Grid Interface (MWh)**
- **Total Energy Discharged at Grid Interface (MWh)**
- **Total Cell-Side Energy Throughput (MWh)**
- **Realized Round-Trip Efficiency (%)**: $\frac{\sum P_{\text{dis}, t} \Delta t}{\sum P_{\text{ch}, t} \Delta t}$
- **Cumulative Equivalent Full Cycles (EFC)**
- **Average, Minimum, and Maximum Operating SOC (%)**
- **Operating Hours Breakdown**: Hours charging, hours discharging, hours idle
- **Asset Utilization Factor (%)**: Active operating hours / total annual hours (8,784 h)

---

## 8. Validation Requirements & Quality Checks

The implementation must include an automated validation suite (`pytest` and runtime pipeline checks) covering:

1. **Hourly Coverage**: Exactly 8,784 hourly intervals covering the German delivery year 2024.
2. **Timestamp Uniqueness & Ordering**: Monotonically increasing UTC timestamps with zero duplicates or gaps.
3. **UTC Boundaries**: First UTC timestamp is `2023-12-31T23:00:00Z` and last UTC timestamp is `2024-12-31T22:00:00Z`.
4. **Local Delivery Day Alignment**: Exactly 366 local delivery dates in `Europe/Berlin` (`2024-01-01` through `2024-12-31`).
5. **DST Transition Day Structure**:
   - `2024-03-31` contains exactly 23 hourly intervals.
   - `2024-10-27` contains exactly 25 hourly intervals.
   - All other 364 delivery dates contain exactly 24 hourly intervals.
   - Sum of delivery-day intervals equals 8,784.
6. **Preservation of Negative Prices**: Explicit check verifying that negative price occurrences are preserved without clipping or alteration.
7. **SOC Bounds Adherence**: $0.10 \le \text{SOC}_t \le 0.90$ for every single hour $t$.
8. **Terminal SOC Equality**: $\text{SOC}_{\text{end}} = \text{SOC}_{\text{start}}$ within numerical tolerance ($10^{-5}$) across each delivery day horizon.
9. **Mutual Exclusivity (No Simultaneous Operation)**: $P_{\text{ch}, t} \cdot P_{\text{dis}, t} = 0$ for all $t$.
10. **Power Limit Adherence**: $0 \le P_{\text{ch}, t} \le 1.0\,\text{MW}$ and $0 \le P_{\text{dis}, t} \le 1.0\,\text{MW}$.
11. **Grid Limit Adherence**: System interchange does not exceed 1.0 MW.
12. **Energy Balance & Conservation**: Cell energy inventory strictly satisfies:
    $$\Delta E_{\text{cell}, t} = P_{\text{ch}, t} \cdot \eta_{\text{ch}} \cdot \Delta t - \frac{P_{\text{dis}, t}}{\eta_{\text{dis}}} \cdot \Delta t$$
13. **Efficiency Accounting**: Round-trip efficiency losses applied consistently across charging and discharging stages.
14. **EFC Calculation Consistency**: Verified against cumulative cell throughput and nominal capacity.
15. **Financial Unit Consistency**: Rigorous checking that prices (EUR/MWh), powers (MW), energies (MWh), and monetary sums (EUR) align without scalar discrepancies.

---

## 9. Project Positioning

- **Portfolio Demonstration**: Designed to showcase rigorous energy systems modeling, mathematical optimization, market analytics, and clean Python software architecture.
- **Not Investment Advice**: Results are for demonstration and educational purposes; they do not constitute commercial investment advice or bankable yield projections.
- **Not a Production EMS**: Focuses on retrospective analysis and benchmarking rather than real-time telemetry or industrial automation.
- **Ex-Post Perfect Foresight**: Realized historical price optimization represents a theoretical upper-bound benchmark.

---

## 10. Planned Final Deliverables

1. **Modular Python Pipeline**: Structured codebase (`src/` architecture) separating configuration, SMARD data acquisition, simulation, optimization, and analytics.
2. **Validated Battery Simulation Engine**: Pure Python/NumPy simulation module with automated constraint validation.
3. **Baseline Heuristic Dispatch Module**: Reproducible rule-based benchmark.
4. **Optimized Dispatch Module**: SciPy HiGHS MILP daily optimization engine operating on German market delivery days.
5. **Degradation Sensitivity Analysis**: Automated sweep across 0, 10, 20, and 30 EUR/MWh scenarios.
6. **KPI Tables**: Formatted markdown and CSV summary reports.
7. **Professional Visualizations**: High-quality plots (dispatch time-series, price-duration curves, monthly capture spreads, SOC heatmaps).
8. **Automated Test Suite**: Full `pytest` coverage of validation rules and physical constraints.
9. **Project README**: Professional documentation covering methodology, mathematical formulation, and findings.
10. **Streamlit Portfolio Dashboard**: Interactive web application enabling user scenario exploration.
11. **Public GitHub Repository**: Clean repository with reproducible environment configuration.

---

## 11. Locked Implementation Decisions

All preliminary implementation ambiguities are formally locked as follows:

| Decision Area | Locked Specification |
| :--- | :--- |
| **Historical Year & Market Time** | **German Delivery Year 2024** (`2024-01-01 00:00:00` to `2025-01-01 00:00:00` in `Europe/Berlin`). Canonical UTC range: `2023-12-31T23:00:00Z` through `2024-12-31T23:00:00Z` exclusive (8,784 hours, 366 delivery days). |
| **SMARD Price Series** | **Filter 4169**, Series *Marktpreis Deutschland/Luxemburg*, Region *DE*, Resolution *hour*, Currency *EUR/MWh*. Canonical storage in UTC, local delivery days in `Europe/Berlin`. |
| **Battery Capacity** | **Nominal Energy Capacity**: 2.0 MWh ($E_{\text{nom}}$, denominator for SOC). **Rated Power**: 1.0 MW. **Operational Energy Window**: $2.0 \times (0.90 - 0.10) = 1.6\,\text{MWh}$. |
| **Negative Price Policy** | **Preserved unclipped**. Negative prices represent valid market signals where charging generates negative cost (revenue). |
| **Optimization Method** | **`scipy.optimize.milp`** with the **HiGHS** solver backend and binary operational indicators. |
| **Optimization Horizon** | **One optimization horizon per Europe/Berlin delivery date** ($T_d \in \{23, 24, 25\}$ hours) with strictly enforced terminal equality condition: $\text{SOC}_{\text{end}} = \text{SOC}_{\text{start}} = 50\%$. |
| **Degradation Modeling** | Cell-side throughput proxy: $\text{EFC} = \text{Throughput}_{\text{cell}} / (2 \times E_{\text{nom}})$. Scenarios: **0, 10, 20 (nominal), and 30 EUR/MWh**. Labeled as modeling assumptions. |
| **Market Cost Scope** | Excludes grid tariffs, levies, taxes, exchange fees, imbalance costs, ancillary service revenues, and capacity market payments. Captures wholesale day-ahead energy arbitrage value only. |
