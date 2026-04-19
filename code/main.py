"""
=============================================================================
  Base-and-Patrol Spatio-Temporal Protection Model
  Etosha National Park — IMMC 2026
=============================================================================
  main.py
  Entry point. Runs the full simulation pipeline and prints a complete
  report to stdout. Execute: python main.py
=============================================================================
"""

from __future__ import annotations
import time
from model_core import Season, TOTAL_PERSONNEL, ANNUAL_BUDGET_USD
from park_data import build_waterholes, build_roads, build_zones
from optimizer import optimize
from model_core import ParkModel
from sensitivity import (
    run_baseline,
    run_personnel_sensitivity,
    run_budget_sensitivity,
    run_drone_failure,
    run_seasonal_comparison,
    run_intel_scenarios,
    run_yellowstone_scenario,
    run_kaziranga_scenario,
)


def print_header():
    print("\n" + "=" * 65)
    print("  IMMC 2026 — Base-and-Patrol Protection Model")
    print("  Etosha National Park, Namibia")
    print("  Spatio-Temporal Constrained Optimization Simulation")
    print("=" * 65)
    print(f"  Park area:          22,935 km²")
    print(f"  Critical waterholes: 86")
    print(f"  Road network:       3,551 km")
    print(f"  Total personnel:    {TOTAL_PERSONNEL}")
    print(f"  Annual budget:      ${ANNUAL_BUDGET_USD:,.0f} USD")
    print("=" * 65)


def print_footer(elapsed: float):
    print("\n" + "=" * 65)
    print(f"  Simulation complete. Elapsed: {elapsed:.2f}s")
    print("=" * 65 + "\n")


def run_full_simulation():
    print_header()
    t_start = time.time()

    # ── 1. Baseline optimized deployment ─────────────────────────────────
    park = ParkModel(
        waterholes  = build_waterholes(),
        roads       = build_roads(),
        zones       = build_zones(),
        season      = Season.DRY,
        temp_norm   = 0.65,
        wind_norm   = 0.50,
        intel_level = 0.0,
    )

    park, result = optimize(park, total_staff=TOTAL_PERSONNEL,
                            annual_budget=ANNUAL_BUDGET_USD)

    print("\n" + result.summary())

    # Detailed breakdown of FOB placement
    print("\n  FORWARD OPERATING BASE LOCATIONS:")
    print(f"  {'FOB ID':>6} | {'Lat':>9} | {'Lon':>9} | {'Staff':>5}")
    print("  " + "-"*38)
    for fob in park.fobs:
        print(f"  {fob.id:>6} | {fob.lat:>9.4f} | {fob.lon:>9.4f} | {fob.staff_count:>5}")

    # Camera allocation summary
    cams_installed = [wh for wh in park.waterholes if wh.has_camera]
    print(f"\n  TOP 5 HIGHEST-PRIORITY WATERHOLES (cameras installed first):")
    print(f"  {'WH':>4} | {'Name':<22} | {'Hist.Risk':>9} | {'Camera':>6}")
    print("  " + "-"*50)
    top5 = sorted(cams_installed,
                  key=lambda w: w.historical_risk, reverse=True)[:5]
    for wh in top5:
        print(f"  {wh.id:>4} | {wh.name:<22} | {wh.historical_risk:>9.2f} | {'Yes':>6}")

    # Drone allocation summary
    print(f"\n  TOP 5 HIGHEST DRONE-HOUR ROAD SEGMENTS:")
    print(f"  {'Seg':>4} | {'Length(km)':>10} | {'Risk':>5} | {'DroneHrs':>8}")
    print("  " + "-"*38)
    top_roads = sorted(park.roads, key=lambda r: r.drone_hours, reverse=True)[:5]
    for rd in top_roads:
        print(f"  {rd.id:>4} | {rd.length_km:>10.1f} | "
              f"{'H' if rd.risk_class==3 else 'M' if rd.risk_class==2 else 'L':>5} | "
              f"{rd.drone_hours:>8.1f}")

    # ── 2. All sensitivity scenarios ──────────────────────────────────────
    run_baseline()
    run_personnel_sensitivity()
    run_budget_sensitivity()
    run_drone_failure()
    run_seasonal_comparison()
    run_intel_scenarios()
    run_yellowstone_scenario()
    run_kaziranga_scenario()

    print_footer(time.time() - t_start)


if __name__ == '__main__':
    run_full_simulation()
