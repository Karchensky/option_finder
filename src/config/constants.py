"""Application-wide constants."""

from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------
EASTERN = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Market hours (US equities)
# ---------------------------------------------------------------------------
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
BASELINE_LOOKBACK_DAYS: int = 20
BASELINE_MIN_DATAPOINTS: int = 5
STD_FLOOR: float = 0.01
COMPOSITE_SCORE_MAX: float = 10.0


@dataclass(frozen=True)
class FactorWeight:
    key: str
    weight: float


FACTOR_WEIGHTS: tuple[FactorWeight, ...] = (
    # Tier 1 -- primary volume/flow signals
    FactorWeight("vol_z", 0.18),
    FactorWeight("prem_z", 0.13),
    FactorWeight("iv_z", 0.13),
    FactorWeight("vol_oi_z", 0.12),
    FactorWeight("sweep_z", 0.10),
    # Tier 2 -- structural positioning
    FactorWeight("delta_conc_z", 0.08),
    FactorWeight("oi_z", 0.07),       # lagging indicator (prior-day settlement)
    FactorWeight("earnings_z", 0.07),  # negative z-score near earnings = dampener
    FactorWeight("tte_z", 0.06),
    # Tier 3 -- supporting context
    FactorWeight("spread_z", 0.04),
    FactorWeight("underlying_z", 0.02),
)

FACTOR_WEIGHT_MAP: dict[str, float] = {fw.key: fw.weight for fw in FACTOR_WEIGHTS}

# ---------------------------------------------------------------------------
# Already-priced-in gate
# ---------------------------------------------------------------------------
ALREADY_PRICED_IN_THRESHOLD: float = 0.02  # 2 %

# ---------------------------------------------------------------------------
# Alert deduplication
# ---------------------------------------------------------------------------
DEDUP_SCORE_DELTA: float = 1.0

# ---------------------------------------------------------------------------
# Polygon API
# ---------------------------------------------------------------------------
POLYGON_BASE_URL: str = "https://api.polygon.io"
POLYGON_PAGE_LIMIT: int = 250
POLYGON_PAGE_DELAY_S: float = 0.1  # 100 ms between paginated requests

# ---------------------------------------------------------------------------
# Pipeline resilience
# ---------------------------------------------------------------------------
SCAN_CYCLE_INTERVAL_S: int = 900  # 15 minutes between scan cycles
CYCLE_RETRY_DELAY_S: int = 60
MAX_CONSECUTIVE_FAILURES: int = 5
ALERT_RETRY_MAX: int = 3
