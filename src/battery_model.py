"""Physical Battery Energy Storage System (BESS) Simulation Engine.

Provides an immutable configuration dataclass and a stateful battery simulator
tracking cell-side vs grid-side power, energy balances, conversion losses, and
SOC boundaries according to PROJECT_SPEC.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

TOLERANCE = 1e-9


@dataclass(frozen=True)
class BESSConfig:
    """Immutable configuration specification for a Battery Energy Storage System.

    Units:
        nominal_energy_capacity_mwh: MWh (nominal nameplate capacity, SOC denominator)
        rated_charge_power_mw: MW (maximum continuous charging rate at grid interface)
        rated_discharge_power_mw: MW (maximum continuous discharging rate at grid interface)
        soc_min: dimensionless fraction in [0.0, 1.0] (lower operational SOC buffer)
        soc_max: dimensionless fraction in [0.0, 1.0] (upper operational SOC buffer)
        initial_soc: dimensionless fraction in [soc_min, soc_max] (starting SOC)
        charge_efficiency: dimensionless fraction in (0.0, 1.0] (grid-to-cell efficiency)
        discharge_efficiency: dimensionless fraction in (0.0, 1.0] (cell-to-grid efficiency)
        grid_connection_limit_mw: MW (maximum active power exchange at point of common coupling)
        timestep_hours: hours (duration of each discrete simulation interval dt)
    """

    nominal_energy_capacity_mwh: float = 2.0
    rated_charge_power_mw: float = 1.0
    rated_discharge_power_mw: float = 1.0
    soc_min: float = 0.10
    soc_max: float = 0.90
    initial_soc: float = 0.50
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    grid_connection_limit_mw: float = 1.0
    timestep_hours: float = 1.0

    def __post_init__(self) -> None:
        """Validate technical feasibility and boundary consistency on instantiation."""
        if self.nominal_energy_capacity_mwh <= 0:
            raise ValueError(
                f"Nominal capacity must be positive, got {self.nominal_energy_capacity_mwh} MWh."
            )
        if self.rated_charge_power_mw <= 0:
            raise ValueError(
                f"Rated charge power must be positive, got {self.rated_charge_power_mw} MW."
            )
        if self.rated_discharge_power_mw <= 0:
            raise ValueError(
                f"Rated discharge power must be positive, got {self.rated_discharge_power_mw} MW."
            )
        if self.grid_connection_limit_mw <= 0:
            raise ValueError(
                f"Grid connection limit must be positive, got {self.grid_connection_limit_mw} MW."
            )
        if self.timestep_hours <= 0:
            raise ValueError(
                f"Timestep must be positive, got {self.timestep_hours} hours."
            )
        if not (0.0 < self.charge_efficiency <= 1.0):
            raise ValueError(
                f"Charge efficiency must be in (0, 1], got {self.charge_efficiency}."
            )
        if not (0.0 < self.discharge_efficiency <= 1.0):
            raise ValueError(
                f"Discharge efficiency must be in (0, 1], got {self.discharge_efficiency}."
            )
        if self.soc_min < 0.0:
            raise ValueError(f"Minimum SOC cannot be negative, got {self.soc_min}.")
        if self.soc_max > 1.0:
            raise ValueError(f"Maximum SOC cannot exceed 1.0, got {self.soc_max}.")
        if self.soc_min >= self.soc_max:
            raise ValueError(
                f"soc_min ({self.soc_min}) must be strictly less than soc_max ({self.soc_max})."
            )
        if not (self.soc_min <= self.initial_soc <= self.soc_max):
            raise ValueError(
                f"initial_soc ({self.initial_soc}) must lie within [{self.soc_min}, {self.soc_max}]."
            )


@dataclass(frozen=True)
class BatteryStepResult:
    """Detailed telemetry and accounting results from a single simulation timestep.

    Conventions:
        - Grid-side energy is measured at the grid connection point / meter.
        - Cell-side energy is measured at the internal battery cell chemistry interface.
        - During charging: cell_charge_energy = grid_charge_energy * charge_efficiency.
        - During discharging: cell_discharge_energy = grid_discharge_energy / discharge_efficiency.
        - Conversion loss is non-negative and reflects energy dissipated as heat.
        - was_soc_limited is True if the battery had to throttle requested power to respect SOC boundaries.
    """

    requested_charge_power_mw: float
    requested_discharge_power_mw: float
    actual_charge_power_mw: float
    actual_discharge_power_mw: float
    grid_charge_energy_mwh: float
    grid_discharge_energy_mwh: float
    cell_charge_energy_mwh: float
    cell_discharge_energy_mwh: float
    energy_before_mwh: float
    energy_after_mwh: float
    soc_before: float
    soc_after: float
    conversion_loss_mwh: float
    was_soc_limited: bool


class BatteryModel:
    """Stateful physical Battery Energy Storage System (BESS) simulation model.

    Tracks energy storage dynamics, enforces physical power ratings, prevents
    simultaneous charge/discharge, and dynamically throttles requests at SOC limits.
    """

    def __init__(self, config: BESSConfig | None = None) -> None:
        self._config = config if config is not None else BESSConfig()
        self._energy_mwh: float = (
            self._config.initial_soc * self._config.nominal_energy_capacity_mwh
        )

    @property
    def config(self) -> BESSConfig:
        """The underlying immutable BESS configuration."""
        return self._config

    @property
    def energy_mwh(self) -> float:
        """Current stored energy in the battery cells (MWh)."""
        return self._energy_mwh

    @property
    def soc(self) -> float:
        """Current State of Charge relative to nominal capacity (dimensionless fraction)."""
        return self._energy_mwh / self._config.nominal_energy_capacity_mwh

    @property
    def energy_min_mwh(self) -> float:
        """Minimum allowable stored cell energy (MWh)."""
        return self._config.soc_min * self._config.nominal_energy_capacity_mwh

    @property
    def energy_max_mwh(self) -> float:
        """Maximum allowable stored cell energy (MWh)."""
        return self._config.soc_max * self._config.nominal_energy_capacity_mwh

    @property
    def operational_energy_window_mwh(self) -> float:
        """Total usable operational energy window between soc_min and soc_max (MWh)."""
        return self.energy_max_mwh - self.energy_min_mwh

    @property
    def round_trip_efficiency(self) -> float:
        """Nominal round-trip energy efficiency (RTE = eta_ch * eta_dis)."""
        return self._config.charge_efficiency * self._config.discharge_efficiency

    def reset(self, soc: float | None = None) -> None:
        """Reset the battery state of charge.

        Args:
            soc: Optional target SOC fraction. If None, resets to config.initial_soc.

        Raises:
            ValueError: If soc is outside [config.soc_min, config.soc_max].
        """
        target_soc = self._config.initial_soc if soc is None else soc
        if not (self._config.soc_min - TOLERANCE <= target_soc <= self._config.soc_max + TOLERANCE):
            raise ValueError(
                f"Target reset SOC ({target_soc}) must be within [{self._config.soc_min}, {self._config.soc_max}]."
            )
        self._energy_mwh = target_soc * self._config.nominal_energy_capacity_mwh

    def step(
        self,
        charge_power_mw: float = 0.0,
        discharge_power_mw: float = 0.0,
        target_soc: float | None = None,
    ) -> BatteryStepResult:
        """Simulate battery performance over a single discrete time interval dt.

        Args:
            charge_power_mw: Requested grid charging power (MW >= 0).
            discharge_power_mw: Requested grid discharge power (MW >= 0).
            target_soc: Optional target SOC boundary (e.g. 0.50 for terminal day recovery).
                        If None, defaults to config.soc_max when charging and config.soc_min
                        when discharging.

        Returns:
            BatteryStepResult detailing power flows, energy balances, losses, and SOC.

        Raises:
            ValueError: If requested power is negative, exceeds hardware/grid ratings,
                        or requests simultaneous charging and discharging.
        """
        # 1. Reject negative power requests
        if charge_power_mw < -TOLERANCE:
            raise ValueError(
                f"Requested charge power cannot be negative, got {charge_power_mw} MW."
            )
        if discharge_power_mw < -TOLERANCE:
            raise ValueError(
                f"Requested discharge power cannot be negative, got {discharge_power_mw} MW."
            )

        # Numerical clean-up of tiny negative floating point artifacts
        req_charge = max(0.0, charge_power_mw)
        req_discharge = max(0.0, discharge_power_mw)

        # 2. Strict mutual exclusivity: No simultaneous charging and discharging
        if req_charge > TOLERANCE and req_discharge > TOLERANCE:
            raise ValueError(
                f"Simultaneous charging ({req_charge:.4f} MW) and discharging "
                f"({req_discharge:.4f} MW) is physically prohibited."
            )

        # 3. Explicit power rating & grid interconnection violations MUST raise ValueError
        max_allowed_charge = min(
            self._config.rated_charge_power_mw, self._config.grid_connection_limit_mw
        )
        if req_charge > max_allowed_charge + TOLERANCE:
            raise ValueError(
                f"Requested charge power ({req_charge:.4f} MW) exceeds allowable rating "
                f"({max_allowed_charge:.4f} MW)."
            )

        max_allowed_discharge = min(
            self._config.rated_discharge_power_mw, self._config.grid_connection_limit_mw
        )
        if req_discharge > max_allowed_discharge + TOLERANCE:
            raise ValueError(
                f"Requested discharge power ({req_discharge:.4f} MW) exceeds allowable rating "
                f"({max_allowed_discharge:.4f} MW)."
            )

        energy_before = self._energy_mwh
        soc_before = self.soc
        dt = self._config.timestep_hours

        actual_charge_power = 0.0
        actual_discharge_power = 0.0
        grid_charge_energy = 0.0
        cell_charge_energy = 0.0
        grid_discharge_energy = 0.0
        cell_discharge_energy = 0.0
        conversion_loss = 0.0
        was_soc_limited = False

        if req_charge > TOLERANCE:
            # Storage room remaining inside cells up to soc_max or target_soc
            effective_energy_max = (
                min(self.energy_max_mwh, target_soc * self._config.nominal_energy_capacity_mwh)
                if target_soc is not None
                else self.energy_max_mwh
            )
            room_cell_mwh = max(0.0, effective_energy_max - energy_before)
            # Maximum grid energy that can be converted into room_cell_mwh:
            max_grid_energy = room_cell_mwh / self._config.charge_efficiency
            max_feasible_power = max_grid_energy / dt

            if req_charge > max_feasible_power + TOLERANCE:
                actual_charge_power = max_feasible_power
                was_soc_limited = True
            else:
                actual_charge_power = req_charge

            grid_charge_energy = actual_charge_power * dt
            cell_charge_energy = grid_charge_energy * self._config.charge_efficiency
            conversion_loss = grid_charge_energy - cell_charge_energy
            energy_after = energy_before + cell_charge_energy

        elif req_discharge > TOLERANCE:
            # Available cell energy above soc_min or target_soc
            effective_energy_min = (
                max(self.energy_min_mwh, target_soc * self._config.nominal_energy_capacity_mwh)
                if target_soc is not None
                else self.energy_min_mwh
            )
            available_cell_mwh = max(0.0, energy_before - effective_energy_min)
            # Maximum grid energy delivered from available_cell_mwh:
            max_grid_energy = available_cell_mwh * self._config.discharge_efficiency
            max_feasible_power = max_grid_energy / dt

            if req_discharge > max_feasible_power + TOLERANCE:
                actual_discharge_power = max_feasible_power
                was_soc_limited = True
            else:
                actual_discharge_power = req_discharge

            grid_discharge_energy = actual_discharge_power * dt
            cell_discharge_energy = grid_discharge_energy / self._config.discharge_efficiency
            conversion_loss = cell_discharge_energy - grid_discharge_energy
            energy_after = energy_before - cell_discharge_energy

        else:
            # Idle step
            energy_after = energy_before

        # Ensure small floating point imprecisions stay strictly within [energy_min, energy_max]
        if math.isclose(energy_after, self.energy_min_mwh, abs_tol=1e-12):
            energy_after = self.energy_min_mwh
        elif math.isclose(energy_after, self.energy_max_mwh, abs_tol=1e-12):
            energy_after = self.energy_max_mwh
        else:
            energy_after = min(max(energy_after, self.energy_min_mwh), self.energy_max_mwh)

        self._energy_mwh = energy_after
        soc_after = self.soc

        return BatteryStepResult(
            requested_charge_power_mw=req_charge,
            requested_discharge_power_mw=req_discharge,
            actual_charge_power_mw=actual_charge_power,
            actual_discharge_power_mw=actual_discharge_power,
            grid_charge_energy_mwh=grid_charge_energy,
            grid_discharge_energy_mwh=grid_discharge_energy,
            cell_charge_energy_mwh=cell_charge_energy,
            cell_discharge_energy_mwh=cell_discharge_energy,
            energy_before_mwh=energy_before,
            energy_after_mwh=energy_after,
            soc_before=soc_before,
            soc_after=soc_after,
            conversion_loss_mwh=max(0.0, conversion_loss),
            was_soc_limited=was_soc_limited,
        )
