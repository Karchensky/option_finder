"""Shared async HTTP client for the Polygon.io API."""

import asyncio
import logging

import httpx

from src.config.constants import POLYGON_BASE_URL, POLYGON_PAGE_DELAY_S, POLYGON_PAGE_LIMIT
from src.config.settings import get_settings
from src.exceptions import PolygonAPIError

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRY_BASE_DELAY_S = 1.0

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Return a module-level singleton httpx.AsyncClient."""
    global _client  # noqa: PLW0603
    if _client is None or _client.is_closed:
        settings = get_settings()
        _client = httpx.AsyncClient(
            base_url=POLYGON_BASE_URL,
            params={"apiKey": settings.polygon_api_key},
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=20),
        )
    return _client


async def close_client() -> None:
    """Close the HTTP client (call on shutdown)."""
    global _client  # noqa: PLW0603
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


async def polygon_get(path: str, params: dict | None = None) -> dict:
    """Issue a GET request against the Polygon API and return the JSON body.

    Retries transient failures (429, 5xx) with exponential backoff.
    Raises PolygonAPIError on persistent non-2xx responses.
    """
    client = get_client()
    last_exc: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY_S * (2 ** attempt)
                logger.warning(
                    "transient %d on %s — retry %d/%d in %.1fs",
                    exc.response.status_code, path, attempt + 1, MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
                last_exc = exc
                continue
            raise PolygonAPIError(
                message=f"Polygon API {exc.response.status_code}: {exc.response.text[:300]}",
                status_code=exc.response.status_code,
                endpoint=path,
            ) from exc
        except httpx.RequestError as exc:
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY_S * (2 ** attempt)
                logger.warning(
                    "request error on %s — retry %d/%d in %.1fs: %s",
                    path, attempt + 1, MAX_RETRIES, delay, exc,
                )
                await asyncio.sleep(delay)
                last_exc = exc
                continue
            raise PolygonAPIError(
                message=f"Polygon request failed: {exc}",
                endpoint=path,
            ) from exc

    raise PolygonAPIError(
        message=f"Polygon request failed after {MAX_RETRIES} retries: {last_exc}",
        endpoint=path,
    )


async def fetch_all_pages(path: str, *, limit: int = POLYGON_PAGE_LIMIT) -> list[dict]:
    """Follow cursor-based pagination until exhausted.

    *path* must be a relative API path (e.g. /v3/snapshot/options/AAPL).
    Polygon's next_url is a full URL; we extract the cursor from it
    and issue all requests via the base-URL client with proper params.
    """
    from urllib.parse import urlparse, parse_qs

    client = get_client()
    results: list[dict] = []
    params: dict[str, str] = {"limit": str(limit)}

    while True:
        last_exc: Exception | None = None
        resp: httpx.Response | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await client.get(path, params=params)
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY_S * (2 ** attempt)
                    logger.warning(
                        "transient %d paginating %s — retry %d/%d in %.1fs",
                        exc.response.status_code, path, attempt + 1, MAX_RETRIES, delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = exc
                    continue
                raise PolygonAPIError(
                    message=f"Pagination error {exc.response.status_code}: {exc.response.text[:300]}",
                    status_code=exc.response.status_code,
                    endpoint=path,
                ) from exc
            except httpx.RequestError as exc:
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY_S * (2 ** attempt)
                    logger.warning(
                        "request error paginating %s — retry %d/%d in %.1fs: %s",
                        path, attempt + 1, MAX_RETRIES, delay, exc,
                    )
                    await asyncio.sleep(delay)
                    last_exc = exc
                    continue
                raise PolygonAPIError(
                    message=f"Pagination request failed: {exc}",
                    endpoint=path,
                ) from exc
        else:
            raise PolygonAPIError(
                message=f"Pagination failed after {MAX_RETRIES} retries: {last_exc}",
                endpoint=path,
            )

        data = resp.json()
        page_results = data.get("results") or []
        results.extend(page_results)

        next_url = data.get("next_url", "")
        if not next_url:
            break

        parsed = urlparse(next_url)
        qs = parse_qs(parsed.query)
        cursor = qs.get("cursor", [None])[0]
        if not cursor:
            break

        params = {"limit": str(limit), "cursor": cursor}
        await asyncio.sleep(POLYGON_PAGE_DELAY_S)

    return results
