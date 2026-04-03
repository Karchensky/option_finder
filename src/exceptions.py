"""Custom exception hierarchy for Option Finder."""


class OptionFinderError(Exception):
    """Base exception for all Option Finder errors."""


class PolygonAPIError(OptionFinderError):
    """Raised when a Polygon.io API call fails."""

    def __init__(self, message: str, status_code: int | None = None, endpoint: str | None = None) -> None:
        self.status_code = status_code
        self.endpoint = endpoint
        super().__init__(message)


class DatabaseError(OptionFinderError):
    """Raised on database connection or query failures."""


class ScoringError(OptionFinderError):
    """Raised when the scoring engine encounters an unrecoverable issue."""


class AlertError(OptionFinderError):
    """Raised when alert formatting or delivery fails."""


class InsufficientDataError(ScoringError):
    """Raised when there are not enough baseline data points to compute a z-score."""

    def __init__(self, ticker: str, available: int, required: int = 5) -> None:
        self.ticker = ticker
        self.available = available
        self.required = required
        super().__init__(f"{ticker}: only {available}/{required} baseline data points")
