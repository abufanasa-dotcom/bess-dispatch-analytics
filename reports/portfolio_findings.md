# BESS Dispatch Analytics — Key Findings

## 1. Dataset & Market
- **Market Series**: Bundesnetzagentur / SMARD Day-Ahead Wholesale Electricity Prices (Filter 4169, Region DE/LU).
- **Delivery Period**: Calendar year 2024 (2024-01-01 00:00 Europe/Berlin inclusive to 2025-01-01 00:00 exclusive).
- **Total Delivery Intervals**: 8,784 hourly intervals across 366 delivery days (leap year).
- **Negative-Price Intervals**: 457 hours with negative day-ahead settlement prices (minimum recorded price: -130.90 EUR/MWh on 2024-05-12).
- **Market Timing & DST**: Strictly evaluated on German delivery-day schedule in Europe/Berlin local time, including the 23-hour spring daylight saving transition (2024-03-31) and the 25-hour autumn transition (2024-10-27).

## 2. Battery Model
- **Rated Power**: 1.0 MW (charge and discharge limits).
- **Nominal Energy Capacity**: 2.0 MWh.
- **Operating SOC Range**: 10.0% to 90.0% State of Charge (operational energy window: 1.6 MWh).
- **Initial & Terminal SOC**: 50.0% (1.0 MWh internal energy), strictly enforced at midnight boundary for every delivery day.
- **Conversion Efficiency**: 95.0% one-way charge efficiency, 95.0% one-way discharge efficiency (ac-to-cell-to-ac round-trip efficiency: 90.25%).
- **Grid Limit**: 1.0 MW maximum simultaneous grid import/export.

## 3. Fixed Baseline
The fixed local-time baseline schedule operates on a predetermined, price-blind daily timetable (charge at 03:00 Europe/Berlin, discharge at 18:00 Europe/Berlin, discharge at 19:00 Europe/Berlin, charge at 23:00 Europe/Berlin to return to the 50% terminal SOC target, all other hours idle):
- **Gross Arbitrage Margin**: €19,588.28
- **Annual Equivalent Full Cycles (EFC)**: 292.80 EFC
- **Grid Energy Throughput**: 616.42 MWh charged, 556.32 MWh discharged
- **System Utilization**: 16.67% (1,464 active dispatch hours)
- **Methodological Role**: Serves as a transparent engineering reference. Because action hours are fixed regardless of realized spreads, the baseline incurs negative daily margins on days with adverse morning/evening spreads.

## 4. Gross Perfect-Foresight Optimization
- **Gross Arbitrage Margin**: €64,831.06
- **Gross Improvement vs Baseline**: +€45,242.77 (+230.97%)
- **Annual Cycling**: 619.12 EFC
- **System Utilization**: 35.44% (3,113 active hours)
- **Benchmark Nature**: *This is an ex-post upper benchmark using realized historical prices, not a deployable trading forecast.* It isolates the theoretical maximum value recoverable by an ideal price-taking BESS under perfect price knowledge.

## 5. Degradation-Aware Sensitivity
To penalize marginal battery usage, an economic degradation proxy is applied across four sensitivity levels: 0, 10, 20, and 30 EUR per MWh of equivalent-cycle energy (cell throughput / 2).

| Degradation Cost Rate (EUR/MWh-eq-cycle) | Gross Margin (EUR) | Assumed Degradation Cost (EUR) | Optimized Net Margin (EUR) | Annual EFC | Gross Value / EFC (EUR/EFC) | Baseline Net Margin (EUR) | Net Improvement vs Baseline (EUR) |
|---|---|---|---|---|---|---|---|
| 0.0 | €64,831.06 | €0.00 | €64,831.06 | 619.12 | €104.72 | €19,588.28 | +€45,242.77 |
| 10.0 | €63,941.67 | €10,061.87 | €53,879.80 | 503.09 | €127.10 | €13,732.28 | +€40,147.52 |
| 20.0 (Nominal) | €61,417.49 | €16,732.05 | €44,685.44 | 418.30 | €146.83 | €7,876.28 | +€36,809.16 |
| 30.0 | €57,620.95 | €20,569.34 | €37,051.61 | 342.82 | €168.08 | €2,020.28 | +€35,031.32 |

### Nominal 20 EUR Assumption Highlights:
- **Gross Margin**: €61,417.49
- **Assumed Degradation Cost**: €16,732.05
- **Net Margin**: €44,685.44
- **Annual Cycling**: 418.30 EFC
- **EFC Reduction**: 32.44% EFC reduction vs zero-cost optimization (reduced from 619.12 to 418.30 EFC)
- **Gross Margin Sacrificed**: €3,413.56 (only 5.27% of gross revenue sacrificed)
- **Gross Arbitrage Value per EFC**: Increased from €104.72/EFC (at 0 EUR) to €146.83/EFC (at 20 EUR), demonstrating that the optimizer filters out low-margin, high-cycling shallow arbitrage spreads.
- **Net Outperformance vs Fixed Baseline**: +€36,809.16 (+467.34%)

### Daily & Monthly Distribution:
- **Daily Net Outperformance**: The nominal 20 EUR optimizer beat the baseline on 364 of 366 delivery days, matched the baseline on 2 days, and never underperformed the baseline (0 days).
- **Median Daily Net Improvement**: €79.43/day.
- **Maximum Daily Net Improvement**: €672.22 (on 2024-12-12).
- **Seasonal Spread Dynamics**:
  - Highest monthly net margin: 2024-08 (€5,908.61, 41.8 EFC) driven by late summer renewable volatility.
  - Lowest monthly net margin: 2024-02 (€806.32, 22.5 EFC) during narrow winter baseline spreads.
  - Highest cycling month: 2024-10 (44.36 EFC).
  - Lowest cycling month: 2024-01 (21.51 EFC).

## 6. Negative Prices
- **Total Negative-Price Hours in 2024**: 457 hours.
- **Charging Hours During Negative Prices**:
  - Unconstrained Zero-Cost MILP (Step 7): 186 hours
  - Nominal 20 EUR Degradation-Aware MILP (Step 8): 158 hours
- **Discharge Hours During Negative Prices**:
  - Unconstrained Zero-Cost MILP (Step 7): 24 hours
  - Nominal 20 EUR Degradation-Aware MILP (Step 8): 1 hour (2024-07-07 06:00 local time, price -0.01 EUR/MWh)
- **Economic Mechanics**: Under perfect foresight, discharging into a mildly negative price can be mathematically optimal if it enables draining the battery to absorb significantly deeper negative prices in subsequent hours, provided the net spread exceeds round-trip conversion losses and assumed cycling costs. This is an artifact of deterministic optimization across multi-hour lookaheads, not a recommended live trading practice.

## 7. Engineering Validation
- **Physical Simulation Replay Consistency**: Every hourly dispatch schedule was independently replayed through BatteryModel to verify mathematical and physical consistency within numerical tolerance (< 1e-10 EUR difference).
- **SOC Bounds Compliance**: State of charge remained strictly within [0.10, 0.90] for every step.
- **Terminal SOC Equality**: The terminal SOC at 24:00 / midnight local time equaled 0.50 (1.0 MWh) exactly for all 366 delivery days.
- **DST Handling**: Seamlessly handled 23-hour spring and 25-hour autumn delivery days with zero indexing or time-alignment errors.
- **Automated Testing**: All current tests passing in pytest.

## 8. Limitations
- **perfect foresight**: The ex-post MILP solves dispatch with complete advance knowledge of all hourly settlement prices across each delivery day. Live commercial operation requires forecasting models and bidding strategies that face substantial price uncertainty.
- **wholesale energy-only economics**: The analysis evaluates only the day-ahead wholesale spot market (EPEX Spot / SMARD DE/LU).
- **no taxes / grid tariffs / market fees**: Analysis reflects gross wholesale arbitrage. Grid connection fees, transmission/distribution tariffs, levies, market platform fees, and corporate taxes are excluded.
- **no imbalance costs**: No schedule deviation penalties or balancing group settlement mechanisms are modeled.
- **no ancillary-service revenue**: It does not include intraday continuous trading, frequency containment reserves (FCR), automatic frequency restoration reserves (aFRR), or other ancillary services.
- **simplified economic degradation proxy**: An economic cycling-cost proxy is modeled as a linear cost heuristic per MWh-equivalent-cycle-energy for dispatch dampening; it does not represent physical battery wear, capacity fade, or lifetime extension.
- **no electrochemical SOH model**: The model does not simulate SEI layer growth, lithium plating, impedance rise, or capacity fade.
- **no calendar ageing**: Resting calendar degradation is not accounted for.
- **no thermal model**: Ambient temperature and cell thermal dynamics are omitted.
- **no forecast uncertainty**: Historical realized prices are known ex-post rather than predicted under uncertainty.
- **no battery CAPEX / full project economics**: Capital expenditure, financing, insurance, land lease, and balance-of-plant maintenance costs are omitted; figures represent operational arbitrage margins, not project internal rate of return (IRR).

## 9. Portfolio Takeaway
This project demonstrates end-to-end technical and quantitative engineering capabilities:
- **German Energy Market Data**: Robust, automated ingestion and validation of official SMARD/Bundesnetzagentur day-ahead price feeds.
- **Rigorous BESS Physics**: Object-oriented physical battery engine with asymmetric charge/discharge efficiencies, SOC bounds, and energy conservation.
- **Mathematical Optimization**: Scalable MILP formulation implemented in SciPy/HiGHS with simultaneous charge/discharge avoidance and terminal condition enforcement.
- **Techno-Economic Modeling**: Multi-scenario sensitivity analysis capturing the trade-off between cycling intensity and economic margin.
- **DST-Safe Time-Series Engineering**: Clean handling of UTC/local market delivery horizons and daylight saving transitions.
- **Reproducible Analytics & Visualizations**: High-fidelity engineering reporting and deterministic visualization pipelines supported by comprehensive automated unit testing.
