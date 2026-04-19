"""
=============================================================================
  Base-and-Patrol Spatio-Temporal Protection Model
  Etosha National Park — IMMC 2026
=============================================================================
  optimizer.py
  Heuristic + greedy allocation engine.
  Allocates cameras, drones, FOBs, and active patrollers within all
  hard constraints (budget, shift limit, drone battery).
=============================================================================
"""

from __future__ import annotations
import numpy as np
import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from model_core import (
    Waterhole, RoadSegment, SavannaZone, ForwardOperatingBase, ParkModel,
    Season, get_active_staff, budget_remaining,
    TOTAL_PERSONNEL, N_SHIFTS, LEAVE_RATE,
    ALPHA, BETA, GAMMA,
    V_VEHICLE_KMH, DELTA_POACH, T_PREP_HR,
    COST_AI_CAMERA_USD, COST_DRONE_HR_USD,
    ANNUAL_BUDGET_USD,
    W1_HISTORICAL, W2_SEASONAL, W3_INTEL,
    BUDGET_CAMERA_FRACTION, BUDGET_DRONE_FRACTION,
    FOB_STAFF_FRACTION, PATROL_STAFF_FRACTION,
    _haversine,
)


# ---------------------------------------------------------------------------
# ALLOCATION RESULT
# ---------------------------------------------------------------------------

@dataclass
class AllocationResult:
    """Stores the complete deployment plan for one shift."""
    total_staff:        int
    active_staff:       int
    fob_staff:          int
    fob_count:          int
    drone_pilots:       int
    active_patrollers:  int
    maintenance_staff:  int
    cameras_installed:  int
    drone_hours_total:  float
    budget_spent_usd:   float
    budget_remaining_usd: float
    epi_result:         Dict = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "  DEPLOYMENT PLAN SUMMARY",
            "=" * 60,
            f"  Total personnel:       {self.total_staff}",
            f"  Active per shift:      {self.active_staff}",
            f"  FOB rapid-response:    {self.fob_staff} ({self.fob_count} bases)",
            f"  Drone pilots:          {self.drone_pilots}",
            f"  Active patrollers:     {self.active_patrollers}",
            f"  Maintenance staff:     {self.maintenance_staff}",
            f"  AI cameras deployed:   {self.cameras_installed}",
            f"  Total drone hrs/shift: {self.drone_hours_total:.1f}",
            f"  Budget spent (USD):    ${self.budget_spent_usd:,.0f}",
            f"  Budget remaining:      ${self.budget_remaining_usd:,.0f}",
            "-" * 60,
            f"  Global EPI:            {self.epi_result.get('epi_percent', '?')}%",
            "=" * 60,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# STEP 1: CAMERA ALLOCATION
# ---------------------------------------------------------------------------

def allocate_cameras(waterholes: List[Waterhole],
                     budget_usd: float,
                     season: Season,
                     intel: float = 0.0) -> Tuple[List[Waterhole], float]:
    """
    Greedy allocation: install AI cameras at waterholes sorted by
    descending vulnerability until budget is exhausted.

    Returns updated waterhole list and remaining budget.

    Parameters
    ----------
    waterholes : List[Waterhole]
        List of all waterholes in the park
    budget_usd : float
        Available budget for camera installation (must be >= 0)
    season : Season
        Current season (affects vulnerability scoring)
    intel : float
        Intelligence level [0,1]

    Returns
    -------
    Tuple[List[Waterhole], float]
        Updated waterhole list and remaining budget
    """
    if budget_usd < 0:
        raise ValueError(f"Budget must be non-negative, got {budget_usd}")
    if not waterholes:
        return [], budget_usd

    # Sort by vulnerability descending
    ranked = sorted(
        waterholes,
        key=lambda wh: wh.vulnerability(season, intel),
        reverse=True
    )

    budget_left = budget_usd
    for wh in ranked:
        if budget_left >= COST_AI_CAMERA_USD:
            wh.has_camera = True
            budget_left -= COST_AI_CAMERA_USD
        else:
            wh.has_camera = False

    # Return list in original ID order
    result = sorted(ranked, key=lambda wh: wh.id)
    return result, budget_left


# ---------------------------------------------------------------------------
# STEP 2: FORWARD OPERATING BASE PLACEMENT (K-Means inspired)
# ---------------------------------------------------------------------------

def place_fobs(waterholes: List[Waterhole],
               zones: List[SavannaZone],
               n_fobs: int,
               fob_staff_total: int,
               season: Season,
               max_iterations: int = 30,
               convergence_threshold: float = 0.01) -> List[ForwardOperatingBase]:
    """
    Places n_fobs Forward Operating Bases using weighted K-Means clustering.

    High-vulnerability waterholes and zones attract FOBs disproportionately.
    Distributes fob_staff_total across FOBs proportional to cluster weight.

    Parameters
    ----------
    waterholes : List[Waterhole]
        All waterholes in the park
    zones : List[SavannaZone]
        All savanna zones in the park
    n_fobs : int
        Number of Forward Operating Bases to place (must be > 0)
    fob_staff_total : int
        Total staff to distribute across FOBs (must be >= n_fobs)
    season : Season
        Current season (affects vulnerability weighting)
    max_iterations : int
        Maximum K-Means iterations (default: 30)
    convergence_threshold : float
        Convergence threshold in km (default: 0.01)

    Returns
    -------
    List[ForwardOperatingBase]
        List of FOBs with assigned staff counts
    """
    if n_fobs <= 0:
        raise ValueError(f"n_fobs must be positive, got {n_fobs}")
    if fob_staff_total < n_fobs:
        raise ValueError(f"fob_staff_total ({fob_staff_total}) must be >= n_fobs ({n_fobs})")

    # Combine waterhole and zone positions into candidate coordinates.
    # We approximate zone coordinates from an evenly spaced grid.
    candidates: List[Tuple[float, float, float]] = []  # (lat, lon, weight)

    ETOSHA_LAT_MIN, ETOSHA_LAT_MAX = -19.5, -18.0
    ETOSHA_LON_MIN, ETOSHA_LON_MAX = 14.5, 17.0

    for wh in waterholes:
        w = wh.vulnerability(season)
        candidates.append((wh.lat, wh.lon, w))

    # Generate approximate zone positions on a grid
    n_zones = len(zones)
    if n_zones > 0:
        lat_range = np.linspace(ETOSHA_LAT_MIN, ETOSHA_LAT_MAX, max(1, int(math.sqrt(n_zones))))
        lon_range = np.linspace(ETOSHA_LON_MIN, ETOSHA_LON_MAX, max(1, int(math.sqrt(n_zones))))
        for idx, zone in enumerate(zones):
            lat = lat_range[idx % len(lat_range)]
            lon = lon_range[idx % len(lon_range)]
            w = zone.vulnerability(season)
            candidates.append((lat, lon, w))

    if not candidates:
        return []

    # Simple weighted K-Means: initialise centroids at highest-weight points
    cands_arr = np.array([[c[0], c[1]] for c in candidates])
    weights   = np.array([c[2] for c in candidates])

    # Initialise centroids: pick top-n_fobs weighted points spread apart
    chosen_idx: List[int] = []
    remaining = list(range(len(candidates)))
    # First centroid: maximum weight
    first = int(np.argmax(weights))
    chosen_idx.append(first)
    remaining.remove(first)

    # Subsequent centroids: maximise minimum distance to existing centroids
    for _ in range(min(n_fobs - 1, len(remaining))):
        if not remaining:
            break
        best_idx = None
        best_min_dist = -1.0
        for r in remaining:
            min_d = min(
                _haversine(cands_arr[r, 0], cands_arr[r, 1],
                           cands_arr[c, 0], cands_arr[c, 1])
                for c in chosen_idx
            )
            if min_d > best_min_dist:
                best_min_dist = min_d
                best_idx = r
        if best_idx is not None:
            chosen_idx.append(best_idx)
            remaining.remove(best_idx)

    # K-Means iterations with convergence check
    centroids = cands_arr[chosen_idx].copy()
    for iteration in range(max_iterations):
        # Assign each candidate to nearest centroid
        labels = np.zeros(len(candidates), dtype=int)
        for i in range(len(candidates)):
            dists = [_haversine(cands_arr[i,0], cands_arr[i,1],
                                centroids[k,0], centroids[k,1])
                     for k in range(len(centroids))]
            labels[i] = int(np.argmin(dists))

        # Update centroids (weighted mean)
        new_centroids = centroids.copy()
        for k in range(len(centroids)):
            mask = labels == k
            if mask.any():
                w_k = weights[mask]
                new_centroids[k, 0] = np.average(cands_arr[mask, 0], weights=w_k)
                new_centroids[k, 1] = np.average(cands_arr[mask, 1], weights=w_k)

        # Check convergence: max movement of any centroid
        max_movement = 0.0
        for k in range(len(centroids)):
            movement = _haversine(centroids[k, 0], centroids[k, 1],
                                 new_centroids[k, 0], new_centroids[k, 1])
            max_movement = max(max_movement, movement)

        centroids = new_centroids

        # Converged if all centroids moved less than threshold
        if max_movement < convergence_threshold:
            break

    # Compute cluster weights for staff distribution
    cluster_weights = np.zeros(len(centroids))
    for i, k in enumerate(labels):
        cluster_weights[k] += weights[i]
    total_cw = cluster_weights.sum()
    if total_cw == 0 or len(centroids) == 0:
        # Fallback: equal distribution
        cluster_weights = np.ones(len(centroids)) if len(centroids) > 0 else np.array([1.0])
        total_cw = float(len(centroids)) if len(centroids) > 0 else 1.0

    fobs = []
    for k, (lat, lon) in enumerate(centroids):
        staff_k = max(1, int(round(fob_staff_total * cluster_weights[k] / total_cw)))
        fobs.append(ForwardOperatingBase(id=k, lat=float(lat), lon=float(lon),
                                         staff_count=staff_k))

    return fobs


# ---------------------------------------------------------------------------
# STEP 3: DRONE ROUTING (Marginal EPI Greedy)
# ---------------------------------------------------------------------------

def allocate_drones(roads: List[RoadSegment],
                    max_flight_hours: float,
                    season: Season,
                    intel: float = 0.0,
                    step: float = 0.5) -> List[RoadSegment]:
    """
    Iterative greedy drone allocation.

    At each iteration, we allocate `step` flight-hours to the road segment
    that yields the maximum marginal increase in detection probability
    (i.e., d(Pd)/d(y_j) is largest where y_j is currently lowest).

    This implements the greedy heuristic from Section 2.3.1.
    """
    # Reset allocations
    for road in roads:
        road.drone_hours = 0.0

    total_allocated = 0.0

    while total_allocated + step <= max_flight_hours:
        best_road = None
        best_marginal = -1.0

        for road in roads:
            # Marginal gain in Pd from adding `step` hours
            pd_before = 1.0 - math.exp(-BETA * road.drone_hours)
            pd_after  = 1.0 - math.exp(-BETA * (road.drone_hours + step))
            marginal_pd = pd_after - pd_before

            # Weight by vulnerability to prioritise high-risk roads
            v = road.vulnerability(season, intel)
            marginal_epi = marginal_pd * v * road.length_km

            if marginal_epi > best_marginal:
                best_marginal = marginal_epi
                best_road = road

        if best_road is None:
            break
        best_road.drone_hours += step
        total_allocated += step

    return roads


# ---------------------------------------------------------------------------
# STEP 4: RANGER PATROL ASSIGNMENT
# ---------------------------------------------------------------------------

def allocate_rangers(zones: List[SavannaZone],
                     n_rangers: int,
                     season: Season) -> List[SavannaZone]:
    """
    Assigns n_rangers across savanna zones proportional to their
    vulnerability score × zone area.
    """
    # Reset
    for z in zones:
        z.rangers = 0

    if n_rangers == 0 or not zones:
        return zones

    # Compute priority weights
    weights = np.array([z.vulnerability(season) * z.area_km2 for z in zones])
    total_w = weights.sum()
    if total_w == 0:
        weights = np.ones(len(zones))
        total_w = float(len(zones))

    allocated = 0
    for i, zone in enumerate(zones):
        share = int(math.floor(n_rangers * weights[i] / total_w))
        zone.rangers = share
        allocated += share

    # Distribute remainder to highest-weight zones
    remainder = n_rangers - allocated
    ranked_idx = np.argsort(-weights)
    for i in range(remainder):
        zones[ranked_idx[i % len(zones)]].rangers += 1

    return zones


# ---------------------------------------------------------------------------
# MASTER OPTIMIZER
# ---------------------------------------------------------------------------

def optimize(park: ParkModel,
             total_staff: int = TOTAL_PERSONNEL,
             annual_budget: float = ANNUAL_BUDGET_USD,
             drone_step_hr: float = 0.5) -> Tuple[ParkModel, AllocationResult]:
    """
    Full Base-and-Patrol optimization pipeline.

    Steps:
        1. Compute active staff from shift constraint.
        2. Allocate AI cameras by vulnerability ranking.
        3. Place Forward Operating Bases using weighted K-Means.
        4. Route drones using marginal-EPI greedy algorithm.
        5. Assign remaining rangers to active patrol.
        6. Compute global EPI.

    Parameters
    ----------
    park          : ParkModel with waterholes, roads, zones pre-populated.
    total_staff   : Hard personnel limit.
    annual_budget : Annual operations budget in USD.
    drone_step_hr : Granularity of drone hour allocation (hours).

    Returns
    -------
    Updated ParkModel and an AllocationResult summary.
    """

    season = park.season

    # ── Step 0: Shift Constraint ─────────────────────────────────────────
    active = get_active_staff(total_staff)
    maintenance = 4  # irreducible minimum for camera/drone tech support

    # ── Step 1: Camera Allocation ─────────────────────────────────────────
    # Cameras are a one-time installation cost; amortise over 1 year.
    camera_budget = min(annual_budget * BUDGET_CAMERA_FRACTION, active * COST_AI_CAMERA_USD)
    park.waterholes, budget_after_cameras = allocate_cameras(
        park.waterholes, camera_budget, season, park.intel_level
    )
    cameras_installed = sum(1 for wh in park.waterholes if wh.has_camera)

    # ── Step 2: FOB Placement ─────────────────────────────────────────────
    # Determine drone pilot headcount (2 pilots per drone, max 3 drones baseline)
    if active >= 80:
        n_drones     = 3
        drone_pilots = 6
    elif active >= 60:
        n_drones     = 2
        drone_pilots = 4
    else:
        n_drones     = 1
        drone_pilots = 2

    remaining_after_ops = active - maintenance - drone_pilots

    # FOB gets 70% of remaining headcount; patrollers get 30%
    fob_staff     = int(math.floor(remaining_after_ops * FOB_STAFF_FRACTION))
    n_ranger_patrol = max(0, remaining_after_ops - fob_staff)

    # Number of FOBs: approximately 1 per 15 FOB staff
    n_fobs = max(1, fob_staff // 15)

    park.fobs = place_fobs(
        park.waterholes, park.zones, n_fobs, fob_staff, season
    )

    # ── Step 3: Drone Routing ─────────────────────────────────────────────
    # Max drone hours per shift = n_drones × shift_hours × utilisation
    drone_utilisation = 0.85    # 85% effective flight time
    max_flight_hours  = n_drones * 8.0 * drone_utilisation

    drone_budget = annual_budget * BUDGET_DRONE_FRACTION
    # Budget limit: annual budget / (cost per hour × shifts per day × days per year)
    drone_hrs_budget_limit = drone_budget / (COST_DRONE_HR_USD * N_SHIFTS * 365)
    effective_limit = min(max_flight_hours, drone_hrs_budget_limit)

    park.roads = allocate_drones(
        park.roads, effective_limit, season, park.intel_level, drone_step_hr
    )
    total_drone_hours = sum(r.drone_hours for r in park.roads)

    # ── Step 4: Ranger Patrol Assignment ─────────────────────────────────
    park.zones = allocate_rangers(park.zones, n_ranger_patrol, season)

    # ── Step 5: Compute Global EPI ────────────────────────────────────────
    epi_result = park.compute_epi()

    # ── Build Result ──────────────────────────────────────────────────────
    # Budget calculation: camera installation + annual drone operations
    camera_cost_total = cameras_installed * COST_AI_CAMERA_USD
    # Annual drone cost: hours_per_shift × shifts_per_day × days_per_year × cost_per_hour
    drone_cost_annual = total_drone_hours * N_SHIFTS * 365 * COST_DRONE_HR_USD
    budget_spent = camera_cost_total + drone_cost_annual

    result = AllocationResult(
        total_staff          = total_staff,
        active_staff         = active,
        fob_staff            = fob_staff,
        fob_count            = n_fobs,
        drone_pilots         = drone_pilots,
        active_patrollers    = n_ranger_patrol,
        maintenance_staff    = maintenance,
        cameras_installed    = cameras_installed,
        drone_hours_total    = round(total_drone_hours, 2),
        budget_spent_usd     = round(budget_spent, 0),
        budget_remaining_usd = round(annual_budget - budget_spent, 0),
        epi_result           = epi_result,
    )

    return park, result
