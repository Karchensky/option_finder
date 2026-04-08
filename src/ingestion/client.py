"""Shared async HTTP client for the Polygon.io API."""

import asyncio
import logging

import httpx

from src.config.constants import POLYGON_BASE_URL, POLYGON_PAGE_DELAY_S, POLYGON_PAGE_LIMIT
from src.config.settings import get_settings
from src.exceptions import PolygonAPIError

logger = logging.getLogger(__name__)

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

    Raises PolygonAPIError on non-2xx responses.
    """
    client = get_client()
    try:
        resp = await client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise PolygonAPIError(
            message=f"Polygon API {exc.response.status_code}: {exc.response.text[:300]}",
            status_code=exc.response.status_code,
            endpoint=path,
        ) from exc
    except httpx.RequestError as exc:
        raise PolygonAPIError(
            message=f"Polygon request failed: {exc}",
            endpoint=path,
        ) from exc


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
        try:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PolygonAPIError(
                message=f"Pagination error {exc.response.status_code}: {exc.response.text[:300]}",
                status_code=exc.response.status_code,
                endpoint=path,
            ) from exc

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
