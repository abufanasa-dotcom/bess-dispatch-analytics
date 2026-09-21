"""Comprehensive unit and physics validation tests for physical BatteryModel."""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from src.battery_model import BESSConfig, BatteryModel, BatteryStepResult


# ---------------------------------------------------------------------------
# Basic Configuration & Initialization Tests
# ---------------------------------------------------------------------------


def test_01_default_initialization():
    """1. Verify default configuration and battery model initialization."""
    config = BESSConfig()
    model = BatteryModel(config)

    assert model.config.nominal_energy_capacity_mwh == 2.0
    assert model.config.rated_charge_power_mw == 1.0
    assert model.config.rated_discharge_power_mw == 1.0
    assert model.config.soc_min == 0.10
    assert model.config.soc_max == 0.90
    assert model.config.initial_soc == 0.50
    assert model.config.charge_efficiency == 0.95
    assert model.config.discharge_efficiency == 0.95
    assert model.config.grid_connection_limit_mw == 1.0
    assert model.config.timestep_hours == 1.0

    # Also test default instantiation without passing config explicitly
    model_default = BatteryModel()
    assert model_default.soc == pytest.approx(0.50)


def test_02_initial_stored_energy_is_one_mwh():
    """2. Verify initial stored energy is exactly 1.0 MWh (50% of 2.0 MWh)."""
    model = BatteryModel()
    assert model.energy_mwh == pytest.approx(1.0)
    assert model.soc == pytest.approx(0.50)


def test_03_minimum_energy_is_point_two_mwh():
    """3. Verify minimum energy is 0.20 MWh (10% of 2.0 MWh)."""
    model = BatteryModel()
    assert model.energy_min_mwh == pytest.approx(0.20)


def test_04_maximum_energy_is_one_point_eight_mwh():
    """4. Verify maximum energy is 1.80 MWh (90% of 2.0 MWh)."""
    model = BatteryModel()
    assert model.energy_max_mwh == pytest.approx(1.80)


def test_05_operational_energy_window_is_one_point_six_mwh():
    """5. Verify operational energy window is exactly 1.60 MWh (1.80 - 0.20)."""
    model = BatteryModel()
    assert model.operational_energy_window_mwh == pytest.approx(1.60)


def test_06_round_trip_efficiency_is_point_9025():
    """6. Verify round-trip efficiency is 90.25% (0.95 * 0.95)."""
    model = BatteryModel()
    assert model.round_trip_efficiency == pytest.approx(0.9025)


# ---------------------------------------------------------------------------
# Boundary & Throttling Tests
# ---------------------------------------------------------------------------


def test_07_one_hour_one_mw_charge_boundary_limited():
    """7. One-hour 1 MW charge from initial state (1.0 MWh).

    Cell headroom: 1.8 - 1.0 = 0.8 MWh
    Max grid charge energy: 0.8 / 0.95 ~= 0.8421052632 MWh
    Actual charge power: ~= 0.8421052632 MW
    Final energy: 1.8 MWh (SOC 0.90)
    was_soc_limited: True
    """
    model = BatteryModel()
    result = model.step(charge_power_mw=1.0, discharge_power_mw=0.0)

    expected_grid_energy = 0.8 / 0.95
    assert result.requested_charge_power_mw == pytest.approx(1.0)
    assert result.actual_charge_power_mw == pytest.approx(expected_grid_energy)
    assert result.grid_charge_energy_mwh == pytest.approx(expected_grid_energy)
    assert result.cell_charge_energy_mwh == pytest.approx(0.8)
    assert result.energy_before_mwh == pytest.approx(1.0)
    assert result.energy_after_mwh == pytest.approx(1.8)
    assert result.soc_before == pytest.approx(0.50)
    assert result.soc_after == pytest.approx(0.90)
    assert result.was_soc_limited is True
    assert model.energy_mwh == pytest.approx(1.8)
    assert model.soc == pytest.approx(0.90)
    assert result.conversion_loss_mwh == pytest.approx(expected_grid_energy - 0.8)


def test_08_one_hour_one_mw_discharge_boundary_limited():
    """8. One-hour 1 MW discharge from initial state (1.0 MWh).

    Cell available energy: 1.0 - 0.2 = 0.8 MWh
    Max grid discharge energy: 0.8 * 0.95 = 0.76 MWh
    Actual discharge power: 0.76 MW
    Final energy: 0.2 MWh (SOC 0.10)
    was_soc_limited: True
    """
    model = BatteryModel()
    result = model.step(charge_power_mw=0.0, discharge_power_mw=1.0)

    assert result.requested_discharge_power_mw == pytest.approx(1.0)
    assert result.actual_discharge_power_mw == pytest.approx(0.76)
    assert result.grid_discharge_energy_mwh == pytest.approx(0.76)
    assert result.cell_discharge_energy_mwh == pytest.approx(0.8)
    assert result.energy_before_mwh == pytest.approx(1.0)
    assert result.energy_after_mwh == pytest.approx(0.2)
    assert result.soc_before == pytest.approx(0.50)
    assert result.soc_after == pytest.approx(0.10)
    assert result.was_soc_limited is True
    assert model.energy_mwh == pytest.approx(0.2)
    assert model.soc == pytest.approx(0.10)
    assert result.conversion_loss_mwh == pytest.approx(0.8 - 0.76)


def test_09_partial_charge_not_hitting_soc_bound():
    """9. Partial charge of 0.5 MW from 1.0 MWh (does not hit SOC_max).

    Grid charge energy: 0.5 MWh
    Cell charge energy: 0.5 * 0.95 = 0.475 MWh
    Final energy: 1.475 MWh (< 1.8 MWh)
    was_soc_limited: False
    """
    model = BatteryModel()
    result = model.step(charge_power_mw=0.5, discharge_power_mw=0.0)

    assert result.actual_charge_power_mw == pytest.approx(0.5)
    assert result.cell_charge_energy_mwh == pytest.approx(0.475)
    assert result.energy_after_mwh == pytest.approx(1.475)
    assert result.soc_after == pytest.approx(1.475 / 2.0)
    assert result.was_soc_limited is False


def test_10_partial_discharge_not_hitting_soc_bound():
    """10. Partial discharge of 0.4 MW from 1.0 MWh (does not hit SOC_min).

    Grid discharge energy: 0.4 MWh
    Cell discharge energy: 0.4 / 0.95 = 0.4210526316 MWh
    Final energy: 1.0 - 0.4210526316 = 0.5789473684 MWh (> 0.2 MWh)
    was_soc_limited: False
    """
    model = BatteryModel()
    result = model.step(charge_power_mw=0.0, discharge_power_mw=0.4)

    expected_cell_discharge = 0.4 / 0.95
    assert result.actual_discharge_power_mw == pytest.approx(0.4)
    assert result.cell_discharge_energy_mwh == pytest.approx(expected_cell_discharge)
    assert result.energy_after_mwh == pytest.approx(1.0 - expected_cell_discharge)
    assert result.was_soc_limited is False


def test_11_idle_step_changes_nothing():
    """11. An idle step (0 MW charge, 0 MW discharge) preserves exact state."""
    model = BatteryModel()
    result = model.step(charge_power_mw=0.0, discharge_power_mw=0.0)

    assert result.actual_charge_power_mw == 0.0
    assert result.actual_discharge_power_mw == 0.0
    assert result.grid_charge_energy_mwh == 0.0
    assert result.grid_discharge_energy_mwh == 0.0
    assert result.conversion_loss_mwh == 0.0
    assert result.energy_after_mwh == pytest.approx(1.0)
    assert result.soc_after == pytest.approx(0.50)
    assert result.was_soc_limited is False


# ---------------------------------------------------------------------------
# Error Handling & Validation Tests
# ---------------------------------------------------------------------------


def test_12_simultaneous_charging_and_discharging_raises_value_error():
    """12. Simultaneous charging and discharging must raise ValueError."""
    model = BatteryModel()
    with pytest.raises(ValueError, match="Simultaneous charging.*and discharging"):
        model.step(charge_power_mw=0.5, discharge_power_mw=0.5)

    with pytest.raises(ValueError, match="Simultaneous charging.*and discharging"):
        model.step(charge_power_mw=0.01, discharge_power_mw=0.01)


def test_13_request_above_charge_rating_raises_value_error():
    """13. Requesting charge power above rated power must raise ValueError."""
    model = BatteryModel()
    with pytest.raises(ValueError, match="exceeds allowable rating"):
        model.step(charge_power_mw=1.05, discharge_power_mw=0.0)


def test_14_request_above_discharge_rating_raises_value_error():
    """14. Requesting discharge power above rated power must raise ValueError."""
    model = BatteryModel()
    with pytest.raises(ValueError, match="exceeds allowable rating"):
        model.step(charge_power_mw=0.0, discharge_power_mw=1.1)


def test_15_request_above_grid_limit_raises_value_error():
    """15. Requesting power above grid connection limit must raise ValueError."""
    custom_config = BESSConfig(
        rated_charge_power_mw=2.0,
        rated_discharge_power_mw=2.0,
        grid_connection_limit_mw=0.8,
    )
    model = BatteryModel(custom_config)

    with pytest.raises(ValueError, match="exceeds allowable rating"):
        model.step(charge_power_mw=1.0, discharge_power_mw=0.0)

    with pytest.raises(ValueError, match="exceeds allowable rating"):
        model.step(charge_power_mw=0.0, discharge_power_mw=1.0)


def test_16_negative_requested_power_raises_value_error():
    """16. Negative requested charge or discharge power must raise ValueError."""
    model = BatteryModel()
    with pytest.raises(ValueError, match="cannot be negative"):
        model.step(charge_power_mw=-0.1, discharge_power_mw=0.0)

    with pytest.raises(ValueError, match="cannot be negative"):
        model.step(charge_power_mw=0.0, discharge_power_mw=-0.5)


def test_17_repeated_charging_never_exceeds_soc_max():
    """17. Repeated aggressive charging requests never exceed SOC_max (0.90)."""
    model = BatteryModel()
    for _ in range(5):
        res = model.step(charge_power_mw=1.0, discharge_power_mw=0.0)
        assert model.soc <= 0.90 + 1e-12
        assert model.energy_mwh <= 1.80 + 1e-12

    assert model.soc == pytest.approx(0.90)
    assert model.energy_mwh == pytest.approx(1.80)
    # Once full, actual charge power must be 0
    full_step = model.step(charge_power_mw=1.0, discharge_power_mw=0.0)
    assert full_step.actual_charge_power_mw == pytest.approx(0.0)
    assert full_step.was_soc_limited is True


def test_18_repeated_discharging_never_falls_below_soc_min():
    """18. Repeated aggressive discharging requests never fall below SOC_min (0.10)."""
    model = BatteryModel()
    for _ in range(5):
        res = model.step(charge_power_mw=0.0, discharge_power_mw=1.0)
        assert model.soc >= 0.10 - 1e-12
        assert model.energy_mwh >= 0.20 - 1e-12

    assert model.soc == pytest.approx(0.10)
    assert model.energy_mwh == pytest.approx(0.20)
    # Once empty, actual discharge power must be 0
    empty_step = model.step(charge_power_mw=0.0, discharge_power_mw=1.0)
    assert empty_step.actual_discharge_power_mw == pytest.approx(0.0)
    assert empty_step.was_soc_limited is True


# ---------------------------------------------------------------------------
# Reset & Configuration Rejection Tests
# ---------------------------------------------------------------------------


def test_19_reset_returns_to_initial_soc():
    """19. Reset restores the battery to the configured initial SOC."""
    model = BatteryModel()
    model.step(charge_power_mw=1.0, discharge_power_mw=0.0)
    assert model.soc == pytest.approx(0.90)

    model.reset()
    assert model.soc == pytest.approx(0.50)
    assert model.energy_mwh == pytest.approx(1.0)

    # Test reset with explicit valid SOC
    model.reset(soc=0.30)
    assert model.soc == pytest.approx(0.30)
    assert model.energy_mwh == pytest.approx(0.60)


def test_20_invalid_reset_soc_raises_value_error():
    """20. Reset to an SOC outside configured [soc_min, soc_max] raises ValueError."""
    model = BatteryModel()
    with pytest.raises(ValueError, match="Target reset SOC"):
        model.reset(soc=0.05)  # < 0.10

    with pytest.raises(ValueError, match="Target reset SOC"):
        model.reset(soc=0.95)  # > 0.90


def test_21_invalid_efficiencies_rejected():
    """21. Efficiencies outside (0.0, 1.0] must raise ValueError."""
    with pytest.raises(ValueError, match="Charge efficiency"):
        BESSConfig(charge_efficiency=0.0)
    with pytest.raises(ValueError, match="Charge efficiency"):
        BESSConfig(charge_efficiency=1.05)
    with pytest.raises(ValueError, match="Discharge efficiency"):
        BESSConfig(discharge_efficiency=-0.1)
    with pytest.raises(ValueError, match="Discharge efficiency"):
        BESSConfig(discharge_efficiency=1.2)


def test_22_invalid_soc_configuration_rejected():
    """22. Inconsistent SOC configurations must raise ValueError."""
    with pytest.raises(ValueError, match="Minimum SOC cannot be negative"):
        BESSConfig(soc_min=-0.1)
    with pytest.raises(ValueError, match="Maximum SOC cannot exceed"):
        BESSConfig(soc_max=1.1)
    with pytest.raises(ValueError, match="strictly less than soc_max"):
        BESSConfig(soc_min=0.8, soc_max=0.5)
    with pytest.raises(ValueError, match="strictly less than soc_max"):
        BESSConfig(soc_min=0.5, soc_max=0.5)
    with pytest.raises(ValueError, match="initial_soc.*must lie within"):
        BESSConfig(soc_min=0.2, soc_max=0.8, initial_soc=0.1)
    with pytest.raises(ValueError, match="initial_soc.*must lie within"):
        BESSConfig(soc_min=0.2, soc_max=0.8, initial_soc=0.9)


def test_23_invalid_capacity_power_timestep_rejected():
    """23. Zero or negative capacity, ratings, grid limit, or timestep must raise ValueError."""
    with pytest.raises(ValueError, match="Nominal capacity must be positive"):
        BESSConfig(nominal_energy_capacity_mwh=0.0)
    with pytest.raises(ValueError, match="Rated charge power must be positive"):
        BESSConfig(rated_charge_power_mw=-1.0)
    with pytest.raises(ValueError, match="Rated discharge power must be positive"):
        BESSConfig(rated_discharge_power_mw=0.0)
    with pytest.raises(ValueError, match="Grid connection limit must be positive"):
        BESSConfig(grid_connection_limit_mw=-0.5)
    with pytest.raises(ValueError, match="Timestep must be positive"):
        BESSConfig(timestep_hours=0.0)


def test_24_exact_cell_side_energy_balance_for_all_steps():
    """24. Verify exact conservation of energy on the cell side for every step."""
    model = BatteryModel()
    test_sequence = [
        (0.4, 0.0),
        (0.8, 0.0),  # Will hit upper limit
        (0.0, 0.5),
        (0.0, 1.0),  # Will hit lower limit
        (0.0, 0.0),  # Idle
        (0.2, 0.0),
    ]
    for ch_req, dis_req in test_sequence:
        res = model.step(charge_power_mw=ch_req, discharge_power_mw=dis_req)
        # Energy balance: E_after == E_before + E_cell_in - E_cell_out
        expected_energy_after = (
            res.energy_before_mwh + res.cell_charge_energy_mwh - res.cell_discharge_energy_mwh
        )
        assert res.energy_after_mwh == pytest.approx(expected_energy_after, abs=1e-12)
        assert model.energy_mwh == pytest.approx(res.energy_after_mwh, abs=1e-12)


def test_25_conversion_losses_are_non_negative():
    """25. Verify that conversion loss is strictly non-negative for every mode."""
    model = BatteryModel()
    for ch, dis in [(0.3, 0.0), (0.0, 0.3), (0.0, 0.0)]:
        res = model.step(charge_power_mw=ch, discharge_power_mw=dis)
        assert res.conversion_loss_mwh >= 0.0


def test_26_config_is_immutable():
    """26. Verify BESSConfig is immutable (frozen dataclass)."""
    config = BESSConfig()
    with pytest.raises(FrozenInstanceError):
        config.nominal_energy_capacity_mwh = 5.0  # type: ignore


# ---------------------------------------------------------------------------
# Dedicated Round-Trip Physics Test
# ---------------------------------------------------------------------------


def test_27_round_trip_physics_exact_efficiency():
    """Verify that a round-trip cycle avoiding SOC limits exhibits exact efficiency:

        grid_energy_returned / grid_energy_consumed == eta_ch * eta_dis == 0.9025

    Starting from initial state (1.0 MWh, 50% SOC):
    1. Charge at grid with 0.20 MW for 1.0 h -> Grid charge energy = 0.20 MWh.
       Cell energy added = 0.20 * 0.95 = 0.19 MWh.
       Energy before = 1.0 MWh -> Energy after = 1.19 MWh (headroom is 0.8 MWh, unconstrained).
    2. Discharge exactly the 0.19 MWh of stored cell energy:
       Required grid discharge power = 0.19 * 0.95 = 0.1805 MW.
       Cell energy removed = 0.1805 / 0.95 = 0.19 MWh.
       Energy after = 1.19 - 0.19 = 1.00 MWh (unconstrained).
    3. Ratio = 0.1805 / 0.20 = 0.9025 == 0.95 * 0.95.
    """
    model = BatteryModel()
    assert model.energy_mwh == pytest.approx(1.0)

    # 1. Charge 0.20 MW grid power
    charge_result = model.step(charge_power_mw=0.20, discharge_power_mw=0.0)
    assert charge_result.was_soc_limited is False
    assert charge_result.grid_charge_energy_mwh == pytest.approx(0.20)
    assert charge_result.cell_charge_energy_mwh == pytest.approx(0.19)
    assert charge_result.energy_after_mwh == pytest.approx(1.19)

    # 2. Discharge to extract exactly 0.19 MWh from cells
    # Grid discharge = 0.19 * 0.95 = 0.1805 MW
    discharge_power = 0.19 * 0.95
    discharge_result = model.step(charge_power_mw=0.0, discharge_power_mw=discharge_power)
    assert discharge_result.was_soc_limited is False
    assert discharge_result.grid_discharge_energy_mwh == pytest.approx(0.1805)
    assert discharge_result.cell_discharge_energy_mwh == pytest.approx(0.19)
    assert discharge_result.energy_after_mwh == pytest.approx(1.0)
    assert model.energy_mwh == pytest.approx(1.0)

    # 3. Verify exact round-trip efficiency
    grid_consumed = charge_result.grid_charge_energy_mwh
    grid_returned = discharge_result.grid_discharge_energy_mwh
    realized_rte = grid_returned / grid_consumed
    expected_rte = model.config.charge_efficiency * model.config.discharge_efficiency

    assert math.isclose(realized_rte, expected_rte, rel_tol=1e-9)
    assert realized_rte == pytest.approx(0.9025)
