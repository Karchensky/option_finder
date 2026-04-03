"""Entry point for the Option Finder scan pipeline."""

import asyncio
import logging
import sys

from src.config.settings import get_settings


def configure_logging() -> None:
    """Set up structured logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def main() -> None:
    """Initialise settings, verify connections, and start the scan loop."""
    configure_logging()
    logger = logging.getLogger(__name__)

    settings = get_settings()
    logger.info("Option Finder starting — alert threshold=%.1f email_enabled=%s",
                settings.anomaly_alert_min_score, settings.anomaly_email_enabled)

    from src.scheduler.loop import run_loop
    await run_loop()


if __name__ == "__main__":
    asyncio.run(main())
