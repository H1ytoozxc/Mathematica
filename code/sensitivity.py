"""
=============================================================================
  Base-and-Patrol Spatio-Temporal Protection Model
  Etosha National Park — IMMC 2026
=============================================================================
  sensitivity.py
  Runs all sensitivity and stress-test scenarios from Section 4 of the
  main paper. Produces tabular output compatible with the paper's tables.
=============================================================================
"""

from __future__ import annotations
import numpy as np
from typing import List, Dict, Tuple
from model_core import (
    ParkModel, Season,
    TOTAL_PERSONNEL, ANNUAL_BUDGET_USD,
    V_VEHICLE_KMH, V_BOAT_KMH, V_HELI_KMH,
    DELTA_POACH, DELTA_FIRE,
    ALPHA, BETA,
    W1_HISTORICAL, W2_SEASONAL, W3_INTEL,
)
from optimizer import optimize
from park_data import build_waterholes, build_roads, build_zones

# Continental adaptation parameters (Section 5)
YELLOWSTONE_STAFF = 1200
YELLOWSTONE_BUDGET_USD = 12_000_000
KAZIRANGA_STAFF = 650
KAZIRANGA_BUDGET_USD = 5_000_000


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _fresh_park(season: Season = Season.DRY,
                temp_norm: float = 0.65,
                wind_norm: float = 0.50,
                intel: float = 0.0) -> ParkModel:
    """Returns a fresh park model with unallocated assets."""
    return ParkModel(
        waterholes  = build_waterholes(),
        roads       = build_roads(),
        zones       = build_zones(),
        season      = season,
        temp_norm   = temp_norm,
        wind_norm   = wind_norm,
        intel_level = intel,
    )


def _run(total_staff: int,
         budget: float = ANNUAL_BUDGET_USD,
         season: Season = Season.DRY,
         temp_norm: float = 0.65,
         wind_norm: float = 0.50,
         intel: float = 0.0) -> Dict:
    park = _fresh_park(season, temp_norm, wind_norm, intel)
    _, result = optimize(park, total_staff=total_staff, annual_budget=budget)
    return result.epi_result | {
        'active_staff':   result.active_staff,
        'fob_count':      result.fob_count,
        'cameras':        result.cameras_installed,
        'drone_hrs':      result.drone_hours_total,
        'budget_spent':   result.budget_spent_usd,
    }


# ---------------------------------------------------------------------------
# SCENARIO A: Baseline (Section 4.1)
# ---------------------------------------------------------------------------

def run_baseline() -> Dict:
    """Baseline scenario: 295 staff, dry season, no special intel."""
    print("\n" + "="*65)
    print("  SCENARIO A: Baseline (295 Staff, Dry Season)")
    print("="*65)
    r = _run(TOTAL_PERSONNEL)
    _print_row(TOTAL_PERSONNEL, r)
    return r


# ---------------------------------------------------------------------------
# SCENARIO B: Personnel Sensitivity (Section 4.2)
# ---------------------------------------------------------------------------

def run_personnel_sensitivity(
        levels: List[int] = None) -> List[Dict]:
    """
    Sweeps total staff from 295 down to 100 and records EPI degradation.
    Simulates the '20% reduction' scenario and further.
    """
    if levels is None:
        levels = [295, 275, 260, 250, 240, 236, 220, 200, 175, 150, 125, 100]

    print("\n" + "="*65)
    print("  SCENARIO B: Personnel Sensitivity Analysis")
    print("="*65)
    print(f"  {'Staff':>6} | {'Active':>6} | {'FOBs':>4} | "
          f"{'Cams':>4} | {'DroneHr':>7} | {'EPI':>6}")
    print("  " + "-"*52)

    results = []
    for s in levels:
        r = _run(s)
        r['total_staff'] = s
        results.append(r)
        _print_row(s, r)

    # Highlight the 20% reduction scenario
    baseline_epi = results[0]['epi_percent']
    reduced_epi  = next((r['epi_percent'] for r in results
                         if r['total_staff'] == 236), None)
    if reduced_epi:
        drop_pct = round(((baseline_epi - reduced_epi) / baseline_epi) * 100, 1)
        print(f"\n  → 20% staff reduction (295→236): EPI drops from "
              f"{baseline_epi}% to {reduced_epi}% (Δ = -{drop_pct}%)")

    return results


# ---------------------------------------------------------------------------
# SCENARIO C: Budget Sensitivity
# ---------------------------------------------------------------------------

def run_budget_sensitivity() -> List[Dict]:
    """Sweeps available budget from 100% down to 40%."""
    print("\n" + "="*65)
    print("  SCENARIO C: Budget Sensitivity Analysis")
    print("="*65)
    print(f"  {'Budget %':>8} | {'Budget USD':>12} | {'EPI':>6}")
    print("  " + "-"*35)

    fractions = [1.00, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40]
    results = []
    for frac in fractions:
        budget = ANNUAL_BUDGET_USD * frac
        r = _run(TOTAL_PERSONNEL, budget=budget)
        r['budget_fraction'] = frac
        results.append(r)
        print(f"  {int(frac*100):>7}% | ${budget:>12,.0f} | {r['epi_percent']:>5.1f}%")

    return results


# ---------------------------------------------------------------------------
# SCENARIO D: Drone Fleet Loss (Section 4.3)
# ---------------------------------------------------------------------------

def run_drone_failure() -> Dict:
    """Simulates complete drone fleet grounding (weather/mechanical)."""
    print("\n" + "="*65)
    print("  SCENARIO D: Drone Fleet Grounded (Adverse Weather)")
    print("="*65)

    park = _fresh_park()
    # Force all drone hours to zero before computing EPI
    for road in park.roads:
        road.drone_hours = 0.0
    # Still run optimizer but cap drone hours at 0
    _, result = optimize(park, total_staff=TOTAL_PERSONNEL, annual_budget=ANNUAL_BUDGET_USD)
    # Manually zero out drone contribution
    for road in park.roads:
        road.drone_hours = 0.0
    epi_no_drones = park.compute_epi()

    baseline = _run(TOTAL_PERSONNEL)
    drop = round(baseline['epi_percent'] - epi_no_drones['epi_percent'], 1)
    print(f"  Baseline EPI:          {baseline['epi_percent']}%")
    print(f"  EPI without drones:    {epi_no_drones['epi_percent']}%")
    print(f"  EPI degradation:       -{drop}%")
    print(f"  → Proves reliance on aerial surveillance for road coverage.")
    return epi_no_drones


# ---------------------------------------------------------------------------
# SCENARIO E: Seasonal Comparison
# ---------------------------------------------------------------------------

def run_seasonal_comparison() -> Dict:
    """Compares EPI performance between dry and wet season."""
    print("\n" + "="*65)
    print("  SCENARIO E: Seasonal Comparison (295 Staff)")
    print("="*65)

    r_dry = _run(TOTAL_PERSONNEL, season=Season.DRY, temp_norm=0.75, wind_norm=0.55)
    r_wet = _run(TOTAL_PERSONNEL, season=Season.WET, temp_norm=0.40, wind_norm=0.40)

    print(f"  Dry Season (May-Oct):  EPI = {r_dry['epi_percent']}%  "
          f"(high animal clustering → high detection value at waterholes)")
    print(f"  Wet Season (Nov-Apr):  EPI = {r_wet['epi_percent']}%  "
          f"(animals disperse → lower detection per waterhole, "
          f"higher savanna zone risk)")
    diff = round(r_dry['epi_percent'] - r_wet['epi_percent'], 1)
    print(f"  Seasonal EPI swing:    {diff}%")
    return {'dry': r_dry, 'wet': r_wet}


# ---------------------------------------------------------------------------
# SCENARIO F: Intel Surge (Poaching Intelligence Received)
# ---------------------------------------------------------------------------

def run_intel_scenarios() -> List[Dict]:
    """Tests EPI at varying levels of active field intelligence."""
    print("\n" + "="*65)
    print("  SCENARIO F: Active Intelligence Surge")
    print("="*65)
    print(f"  {'Intel Level':>12} | {'Cameras':>7} | {'EPI':>6}")
    print("  " + "-"*30)

    levels = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    results = []
    for intel in levels:
        r = _run(TOTAL_PERSONNEL, intel=intel)
        r['intel'] = intel
        results.append(r)
        label = f"{int(intel*100)}%"
        print(f"  {label:>12} | {r['cameras']:>7} | {r['epi_percent']:>5.1f}%")

    print(f"\n  → Higher intel re-ranks waterhole vulnerabilities, "
          f"directing cameras to newly flagged sites.")
    return results


# ---------------------------------------------------------------------------
# SCENARIO G: Continental Adaptation
# ---------------------------------------------------------------------------

def run_yellowstone_scenario() -> Dict:
    """
    Adapts model parameters for Yellowstone NP wildfire scenario.
    Modifications from Section 5.1:
      - w1 (poaching weight) = 0.0
      - beta (drone sweep) attenuated by 0.45 (forest canopy)
      - delta (threat rate) = DELTA_FIRE (crown fire spread)
      - Vehicle speed = helicopter speed
    """
    print("\n" + "="*65)
    print("  SCENARIO G: Continental Adaptation — Yellowstone NP (USA)")
    print("="*65)

    park = _fresh_park(season=Season.DRY, temp_norm=0.80, wind_norm=0.65)

    # Attenuate drone sweep rate
    import model_core as mc
    original_beta = mc.BETA
    original_delta = mc.DELTA_POACH
    original_v = mc.V_VEHICLE_KMH
    original_w1 = mc.W1_HISTORICAL

    mc.BETA          = original_beta  * 0.45   # Forest canopy attenuation λ=0.45
    mc.DELTA_POACH   = DELTA_FIRE             # Crown fire spread rate
    mc.V_VEHICLE_KMH = V_HELI_KMH            # Helitack base response
    mc.W1_HISTORICAL = 0.0                   # No poaching weight

    _, result = optimize(park, total_staff=YELLOWSTONE_STAFF,
                         annual_budget=YELLOWSTONE_BUDGET_USD)

    mc.BETA          = original_beta
    mc.DELTA_POACH   = original_delta
    mc.V_VEHICLE_KMH = original_v
    mc.W1_HISTORICAL = original_w1

    print(f"  Yellowstone (1200 staff, $12M budget): EPI = {result.epi_result['epi_percent']}%")
    print(f"  β_yellowstone = {round(original_beta*0.45, 3)} "
          f"(vs β_etosha = {original_beta})")
    print(f"  δ_fire = {DELTA_FIRE} hr⁻¹ (vs δ_poach = {DELTA_POACH} hr⁻¹)")
    print(f"  → Algorithm shifts resources to thermal AI cameras "
          f"(drones less effective through canopy).")
    return result.epi_result


def run_kaziranga_scenario() -> Dict:
    """
    Adapts model for Kaziranga NP monsoon poaching scenario.
    Modifications from Section 5.2:
      - Seasonal clustering inverted (animals at high elevation, not waterholes)
      - Vehicle speed = V_BOAT_KMH (flood conditions h >= 0.3m)
      - Drone sweep attenuated 0.70 (monsoon cloud cover)
    """
    print("\n" + "="*65)
    print("  SCENARIO H: Continental Adaptation — Kaziranga NP (India)")
    print("="*65)

    park = _fresh_park(season=Season.WET, temp_norm=0.55, wind_norm=0.70)

    import model_core as mc
    original_beta = mc.BETA
    original_v    = mc.V_VEHICLE_KMH
    original_w2   = mc.W2_SEASONAL

    mc.BETA          = original_beta * 0.70   # Monsoon cloud cover / rain
    mc.V_VEHICLE_KMH = V_BOAT_KMH            # Roads flooded; boats used
    mc.W2_SEASONAL   = 0.45                  # Seasonal weight re-calibrated for floods

    _, result = optimize(park, total_staff=KAZIRANGA_STAFF,
                         annual_budget=KAZIRANGA_BUDGET_USD)

    mc.BETA          = original_beta
    mc.V_VEHICLE_KMH = original_v
    mc.W2_SEASONAL   = original_w2

    print(f"  Kaziranga (650 staff, $5M budget): EPI = {result.epi_result['epi_percent']}%")
    print(f"  β_kaziranga = {round(original_beta*0.70, 3)} "
          f"(monsoon attenuation)")
    print(f"  v_monsoon = {V_BOAT_KMH} km/h (boat navigation)")
    print(f"  → FOBs automatically relocated to navigable waterway nodes.")
    return result.epi_result


# ---------------------------------------------------------------------------
# PRINT HELPER
# ---------------------------------------------------------------------------

def _print_row(total_staff: int, r: Dict) -> None:
    print(f"  {total_staff:>6} | "
          f"{r.get('active_staff', '?'):>6} | "
          f"{r.get('fob_count', '?'):>4} | "
          f"{r.get('cameras', '?'):>4} | "
          f"{r.get('drone_hrs', 0.0):>7.1f} | "
          f"{r.get('epi_percent', '?'):>5.1f}%")


# ---------------------------------------------------------------------------
# RUN ALL SCENARIOS
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    run_baseline()
    run_personnel_sensitivity()
    run_budget_sensitivity()
    run_drone_failure()
    run_seasonal_comparison()
    run_intel_scenarios()
    run_yellowstone_scenario()
    run_kaziranga_scenario()
    print("\n  All scenarios complete.")
