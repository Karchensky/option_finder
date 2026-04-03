"""Probe Polygon stock flat files — check if available and inspect structure."""

import csv
import gzip
import sys
import logging

import boto3

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)


def main() -> None:
    from src.config.settings import get_settings
    settings = get_settings()

    s3 = boto3.client(
        "s3",
        endpoint_url=settings.polygon_flatfiles_endpoint,
        aws_access_key_id=settings.polygon_s3_access_key,
        aws_secret_access_key=settings.polygon_s3_secret_key,
    )

    # List available prefixes to find stock data
    logger.info("Listing top-level prefixes in flatfiles bucket...")
    try:
        resp = s3.list_objects_v2(
            Bucket=settings.polygon_flatfiles_bucket,
            Prefix="us_stocks_sip/day_aggs_v1/2026/03/",
            MaxKeys=5,
        )
        contents = resp.get("Contents", [])
        if contents:
            logger.info("Stock flat files found:")
            for obj in contents:
                logger.info("  %s  (%d bytes)", obj["Key"], obj["Size"])

            # Download and inspect first file
            key = contents[0]["Key"]
            logger.info("\nInspecting %s ...", key)
            obj_data = s3.get_object(Bucket=settings.polygon_flatfiles_bucket, Key=key)
            decompressed = gzip.decompress(obj_data["Body"].read()).decode("utf-8")
            reader = csv.reader(decompressed.splitlines())
            header = next(reader)
            logger.info("Headers (%d cols): %s", len(header), header)
            for i, row in enumerate(reader):
                if i >= 3:
                    break
                logger.info("  %s", dict(zip(header, row)))
        else:
            logger.info("No stock flat files found at us_stocks_sip/day_aggs_v1/2026/03/")
    except Exception as exc:
        logger.error("Error: %s", exc)


if __name__ == "__main__":
    main()
