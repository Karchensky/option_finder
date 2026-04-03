"""Probe Polygon flat files — check S3 connectivity and inspect CSV structure."""

import csv
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)


def main() -> None:
    from src.ingestion.flatfiles import stream_day_aggs

    test_date = "2026-03-31"
    logger.info("Probing flat file for %s ...", test_date)

    try:
        buf = stream_day_aggs(test_date)
    except Exception as exc:
        logger.error("Failed to fetch flat file: %s", exc)
        logger.info("Trying a recent date that may exist...")
        for fallback in ["2026-03-28", "2026-03-27", "2026-03-26", "2026-03-21"]:
            try:
                buf = stream_day_aggs(fallback)
                test_date = fallback
                logger.info("Success with %s", fallback)
                break
            except Exception:
                logger.info("  %s — not available", fallback)
                continue
        else:
            logger.error("Could not find any available flat file")
            return

    reader = csv.reader(buf)
    header = next(reader)
    logger.info("\n--- CSV Headers (%d columns) ---", len(header))
    for i, col in enumerate(header):
        logger.info("  [%d] %s", i, col)

    logger.info("\n--- Sample rows (first 5) ---")
    for i, row in enumerate(reader):
        if i >= 5:
            break
        logger.info("  %s", dict(zip(header, row)))

    logger.info("\n--- Row count estimate ---")
    count = 5
    for _ in reader:
        count += 1
    logger.info("  Total rows: %d", count)


if __name__ == "__main__":
    main()
