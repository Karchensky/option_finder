"""Data structures for score breakdowns and factor results."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FactorScore:
    """Individual scoring factor result — raw value, z-score, and weighted contribution."""

    raw: float
    z_score: float
    weight: float
    contribution: float  # z_score * weight

    def to_dict(self) -> dict:
        return {
            "raw": round(self.raw, 4),
            "z_score": round(self.z_score, 4),
            "weight": round(self.weight, 4),
            "contribution": round(self.contribution, 4),
        }


@dataclass
class ScoreBreakdown:
    """Full scoring result for a single option contract."""

    ticker: str
    contract: str
    composite_score: float
    factors: dict[str, FactorScore]
    underlying_move_pct: float
    already_priced_in: bool
    timestamp: datetime
    triggered: bool

    # Enrichment fields populated during alert formatting
    underlying_price: float | None = None
    option_price: float | None = None
    option_volume: int | None = None
    open_interest: int | None = None
    contract_type: str = ""
    expiration_date: str = ""
    strike_price: float | None = None

    def factors_to_dict(self) -> dict[str, dict]:
        """Serialize all factors to a JSON-safe dict."""
        return {k: v.to_dict() for k, v in self.factors.items()}
