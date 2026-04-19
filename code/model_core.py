"""
=============================================================================
  Base-and-Patrol Spatio-Temporal Protection Model
  Etosha National Park — IMMC 2026
=============================================================================
  model_core.py
  Core constants, park geometry, vulnerability scoring, and data structures.
=============================================================================
"""

from __future__ import annotations
import numpy as np
import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from enum import Enum

# ---------------------------------------------------------------------------
# ENUMS
# ---------------------------------------------------------------------------

class Season(Enum):
    DRY = "dry"      # May – October:  animals cluster at waterholes
    WET = "wet"      # November – April: animals disperse across savanna

class ThreatType(Enum):
    POACHING  = "poaching"
    WILDFIRE  = "wildfire"
    COMBINED  = "combined"

class AssetType(Enum):
    AI_CAMERA = "ai_camera"
    DRONE     = "drone"
    RANGER    = "ranger"
    FOB       = "forward_operating_base"

# ---------------------------------------------------------------------------
# PARK CONSTANTS  (Etosha NP, Namibia — Ministry of Environment, 2023)
# ---------------------------------------------------------------------------

PARK_AREA_KM2      = 22_935.0
N_WATERHOLES       = 86
ROAD_NETWORK_KM    = 3_551.0
HIGH_RISK_SAVANNA  = 4_800.0    # km² of highest-risk savanna/salt-pan interface
TOTAL_PERSONNEL    = 295

# Operational logistics
N_SHIFTS           = 3          # 8-hour shifts for 24/7 coverage
LEAVE_RATE         = 0.10       # 10% staff unavailable at any time
SHIFT_HOURS        = 8.0        # hours per shift

# Detection parameters (literature-calibrated)
ALPHA              = 0.85       # AI camera reliability  (Mulero-Pázmány et al., 2014)
BETA               = 0.60       # Drone sweep rate [prob / flight-hr] (Koopman, 1956)
GAMMA              = 0.12       # Ranger search efficiency [prob / ranger]

# Interception parameters
V_VEHICLE_KMH      = 45.0       # 4x4 vehicle speed on gravel roads
V_BOAT_KMH         = 15.0       # Boat speed (Kaziranga monsoon scenario)
V_HELI_KMH         = 180.0      # Helicopter (Yellowstone scenario)
DELTA_POACH        = 0.04       # Poacher escape rate [hr⁻¹]
DELTA_FIRE         = 0.15       # Fire spread rate [hr⁻¹] — crown fire
T_PREP_HR          = 0.25       # 15-min response preparation time

# Budget
ANNUAL_BUDGET_USD  = 4_500_000  # Conservative annual operations budget (USD)
COST_AI_CAMERA_USD = 12_000     # Installation + 1-yr maintenance per unit
COST_DRONE_HR_USD  = 85         # Operational cost per drone flight-hour
COST_RANGER_HR_USD = 4          # Fully-loaded hourly cost per ranger

# Vulnerability weights — Poaching V_x,t
W1_HISTORICAL = 0.40
W2_SEASONAL   = 0.45
W3_INTEL      = 0.15

# Vulnerability weights — Wildfire F_x,t
F1_NDVI       = 0.60
F2_TEMP       = 0.25
F3_WIND       = 0.15

# Budget allocation strategy (Section 2.3)
BUDGET_CAMERA_FRACTION = 0.35   # 35% of budget for AI camera installation
BUDGET_DRONE_FRACTION  = 0.25   # 25% of budget for drone operations
FOB_STAFF_FRACTION     = 0.70   # 70% of remaining staff to FOB rapid-response
PATROL_STAFF_FRACTION  = 0.30   # 30% of remaining staff to active patrols

# ---------------------------------------------------------------------------
# DATA STRUCTURES
# ---------------------------------------------------------------------------

@dataclass
class Waterhole:
    """Represents one of the 86 critical waterholes."""
    id:              int
    name:            str
    lat:             float
    lon:             float
    historical_risk: float          # H_x  ∈ [0,1]: normalised 5-yr poaching density
    rhino_density:   float          # Approximate Black Rhino density near this hole
    has_camera:      bool = False   # Decision variable x_i
    camera_alpha:    float = ALPHA  # Effective sensor reliability at this site

    def detection_prob(self) -> float:
        """P_d,w,i = 1 - (1-alpha)^x_i"""
        return 1.0 - (1.0 - self.camera_alpha) ** int(self.has_camera)

    def vulnerability(self, season: Season, intel: float = 0.0) -> float:
        """V_x,t = w1*H_x + w2*S_x,t + w3*I_x,t"""
        s_xt = 0.90 if season == Season.DRY else 0.30
        return (W1_HISTORICAL * self.historical_risk +
                W2_SEASONAL   * s_xt +
                W3_INTEL      * intel)


@dataclass
class RoadSegment:
    """Represents a discrete road segment in the 3,551 km network."""
    id:           int
    length_km:    float
    risk_class:   int           # 1=low, 2=medium, 3=high (border proximity)
    drone_hours:  float = 0.0   # Decision variable y_j,t

    @property
    def historical_risk(self) -> float:
        return {1: 0.20, 2: 0.50, 3: 0.80}[self.risk_class]

    def detection_prob(self) -> float:
        """P_d,r,j,t = 1 - exp(-beta * y_j,t)"""
        return 1.0 - math.exp(-BETA * self.drone_hours)

    def vulnerability(self, season: Season, intel: float = 0.0) -> float:
        s_xt = 0.45 if season == Season.DRY else 0.60
        return (W1_HISTORICAL * self.historical_risk +
                W2_SEASONAL   * s_xt +
                W3_INTEL      * intel)


@dataclass
class SavannaZone:
    """Represents a high-priority savanna patrol zone."""
    id:             int
    area_km2:       float
    historical_risk: float
    ndvi_score:     float           # Vegetation dryness [0,1]
    rangers:        int = 0         # Decision variable s_k,t

    def detection_prob(self) -> float:
        """P_d,z,k,t = 1 - exp(-gamma * s_k,t)"""
        return 1.0 - math.exp(-GAMMA * self.rangers)

    def vulnerability(self, season: Season, intel: float = 0.0) -> float:
        s_xt = 0.40 if season == Season.DRY else 0.65
        return (W1_HISTORICAL * self.historical_risk +
                W2_SEASONAL   * s_xt +
                W3_INTEL      * intel)

    def wildfire_score(self, temp_norm: float, wind_norm: float) -> float:
        """F_x,t = f1*A_x,t + f2*Temp_t + f3*Wind_t"""
        return (F1_NDVI * self.ndvi_score +
                F2_TEMP * temp_norm +
                F3_WIND * wind_norm)


@dataclass
class ForwardOperatingBase:
    """A rapid-response base staffed by interceptor teams."""
    id:           int
    lat:          float
    lon:          float
    staff_count:  int = 0          # Decision variable b_k

    def interception_prob(self, distance_km: float,
                          v_kmh: float = V_VEHICLE_KMH,
                          delta: float = DELTA_POACH) -> float:
        """P_int,k = exp(-delta * (t_prep + d_k/v))"""
        t_arrival = T_PREP_HR + (distance_km / v_kmh)
        return math.exp(-delta * t_arrival)


@dataclass
class ParkModel:
    """
    Full park model aggregating all assets and computing global EPI.
    """
    waterholes:    List[Waterhole]    = field(default_factory=list)
    roads:         List[RoadSegment]  = field(default_factory=list)
    zones:         List[SavannaZone]  = field(default_factory=list)
    fobs:          List[ForwardOperatingBase] = field(default_factory=list)
    season:        Season             = Season.DRY
    temp_norm:     float              = 0.65   # Normalised ambient temperature
    wind_norm:     float              = 0.50   # Normalised wind speed
    intel_level:   float              = 0.0    # Real-time intelligence signal

    def compute_epi(self) -> Dict:
        """
        Computes the global Effective Protection Index.

        EPI = Σ_t [ Σ_i (V_w + F_w)*Pd_w*Pint_i
                  + Σ_j (V_r + F_r)*Pd_r*Pint_j
                  + Σ_k (V_z + F_z)*Pd_z*Pint_k ]

        Returns a dictionary of per-zone EPIs and a normalised global score.
        """
        # Weighted zone areas (fractions of park)
        w_waterhole = 0.25
        w_road      = 0.35
        w_savanna   = 0.40

        epi_waterholes = []
        for wh in self.waterholes:
            v = wh.vulnerability(self.season, self.intel_level)
            f = 0.15 * self._avg_wildfire()       # Waterholes have minor fire risk
            pd = wh.detection_prob()
            nearest_fob_dist = self._nearest_fob_dist(wh.lat, wh.lon)
            pint = self._best_fob().interception_prob(nearest_fob_dist)
            epi_waterholes.append((v + f) * pd * pint)

        epi_roads = []
        for road in self.roads:
            v = road.vulnerability(self.season, self.intel_level)
            f = 0.30 * self._avg_wildfire()
            pd = road.detection_prob()
            nearest_fob_dist = self._avg_fob_dist()
            pint = self._best_fob().interception_prob(nearest_fob_dist)
            epi_roads.append((v + f) * pd * pint)

        epi_zones = []
        for zone in self.zones:
            v = zone.vulnerability(self.season, self.intel_level)
            f = zone.wildfire_score(self.temp_norm, self.wind_norm)
            pd = zone.detection_prob()
            nearest_fob_dist = self._avg_fob_dist()
            pint = self._best_fob().interception_prob(nearest_fob_dist)
            epi_zones.append((v + f) * pd * pint)

        avg_epi_w = np.mean(epi_waterholes) if epi_waterholes else 0.0
        avg_epi_r = np.mean(epi_roads)      if epi_roads      else 0.0
        avg_epi_z = np.mean(epi_zones)      if epi_zones      else 0.0

        global_epi_raw = (w_waterhole * avg_epi_w +
                          w_road      * avg_epi_r +
                          w_savanna   * avg_epi_z)

        # Normalise: theoretical max at Pd=1, Pint=1, max vulnerability ~1.55
        theoretical_max = (w_waterhole * 1.15 +
                           w_road      * 1.30 +
                           w_savanna   * 1.55)
        epi_normalised = min(1.0, global_epi_raw / theoretical_max)

        return {
            'epi_waterhole':  round(avg_epi_w, 4),
            'epi_road':       round(avg_epi_r, 4),
            'epi_zone':       round(avg_epi_z, 4),
            'epi_global_raw': round(global_epi_raw, 4),
            'epi_normalised': round(epi_normalised, 4),
            'epi_percent':    round(epi_normalised * 100, 1),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _avg_wildfire(self) -> float:
        if not self.zones:
            return 0.0
        return np.mean([z.wildfire_score(self.temp_norm, self.wind_norm)
                        for z in self.zones])

    def _nearest_fob_dist(self, lat: float, lon: float) -> float:
        if not self.fobs:
            return 50.0
        dists = [_haversine(lat, lon, f.lat, f.lon) for f in self.fobs]
        return min(dists)

    def _avg_fob_dist(self) -> float:
        if not self.fobs:
            return 50.0
        area_per_fob = PARK_AREA_KM2 / len(self.fobs)
        return math.sqrt(area_per_fob / math.pi)

    def _best_fob(self) -> ForwardOperatingBase:
        if not self.fobs:
            return ForwardOperatingBase(id=0, lat=0, lon=0, staff_count=20)
        return max(self.fobs, key=lambda f: f.staff_count)


# ---------------------------------------------------------------------------
# UTILITY
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Returns great-circle distance in km between two GPS coordinates."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi  = math.radians(lat2 - lat1)
    dlam  = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_active_staff(total: int = TOTAL_PERSONNEL,
                     shifts: int = N_SHIFTS,
                     leave: float = LEAVE_RATE) -> int:
    """Returns deployable staff for a single shift."""
    return int(math.floor((total / shifts) * (1.0 - leave)))


def budget_remaining(waterholes_with_camera: int,
                     total_drone_hours_per_shift: float) -> float:
    """
    Returns remaining annual budget in USD after camera and drone costs.

    Parameters
    ----------
    waterholes_with_camera : int
        Number of AI cameras installed
    total_drone_hours_per_shift : float
        Total drone flight hours allocated per single shift

    Returns
    -------
    float
        Remaining budget in USD
    """
    camera_cost = waterholes_with_camera * COST_AI_CAMERA_USD
    # Annual drone cost: hours_per_shift × shifts_per_day × days_per_year × cost_per_hour
    drone_cost_annual = total_drone_hours_per_shift * N_SHIFTS * 365 * COST_DRONE_HR_USD
    return ANNUAL_BUDGET_USD - camera_cost - drone_cost_annual
