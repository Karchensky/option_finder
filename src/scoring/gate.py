"""Already-priced-in gate — suppress alerts when the underlying has moved."""

import logging

from src.config.constants import ALREADY_PRICED_IN_THRESHOLD

logger = logging.getLogger(__name__)


def check_already_priced_in(
    contract_type: str,
    underlying_move_pct: float,
    threshold: float = ALREADY_PRICED_IN_THRESHOLD,
) -> bool:
    """Return True if the alert should be **suppressed** (already priced in).

    Calls are suppressed when the stock is already up > threshold.
    Puts are suppressed when the stock is already down > threshold.
    """
    is_call = contract_type.lower() == "call"

    if is_call and underlying_move_pct > threshold * 100:
        logger.debug(
            "priced-in gate: CALL suppressed, underlying up %.2f%%",
            underlying_move_pct,
        )
        return True

    if not is_call and underlying_move_pct < -(threshold * 100):
        logger.debug(
            "priced-in gate: PUT suppressed, underlying down %.2f%%",
            underlying_move_pct,
        )
        return True

    return False
