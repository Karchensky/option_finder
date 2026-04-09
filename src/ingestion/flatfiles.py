"""S3-compatible bulk loader for Polygon flat files (historical backfills)."""

import gzip
import io
import logging
from pathlib import Path

import boto3

from src.config.settings import get_settings

logger = logging.getLogger(__name__)


def _get_s3_client() -> "boto3.client":
    """Return a configured S3 client for Polygon flat files."""
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.polygon_flatfiles_endpoint,
        aws_access_key_id=settings.polygon_s3_access_key,
        aws_secret_access_key=settings.polygon_s3_secret_key,
    )


def download_day_aggs(date_str: str, dest: Path | str) -> Path:
    """Download a daily options agg CSV for *date_str* (YYYY-MM-DD).

    Returns the path to the decompressed CSV.
    """
    settings = get_settings()
    year, month, _ = date_str.split("-")
    key = f"{settings.polygon_flatfiles_prefix}/{year}/{month}/{date_str}.csv.gz"

    dest = Path(dest)
    gz_path = dest / f"{date_str}.csv.gz"
    csv_path = dest / f"{date_str}.csv"

    s3 = _get_s3_client()
    logger.info("downloading s3://%s/%s", settings.polygon_flatfiles_bucket, key)
    s3.download_file(Bucket=settings.polygon_flatfiles_bucket, Key=key, Filename=str(gz_path))

    with gzip.open(gz_path, "rb") as f_in, open(csv_path, "wb") as f_out:
        f_out.write(f_in.read())

    gz_path.unlink()
    logger.info("saved %s", csv_path)
    return csv_path


def stream_day_aggs(date_str: str) -> io.StringIO:
    """Load a daily options agg CSV from S3 into an in-memory text buffer."""
    settings = get_settings()
    year, month, _ = date_str.split("-")
    key = f"{settings.polygon_flatfiles_prefix}/{year}/{month}/{date_str}.csv.gz"

    s3 = _get_s3_client()
    obj = s3.get_object(Bucket=settings.polygon_flatfiles_bucket, Key=key)
    compressed = obj["Body"].read()

    decompressed = gzip.decompress(compressed)
    return io.StringIO(decompressed.decode("utf-8"))
