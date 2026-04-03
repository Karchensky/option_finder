"""Tests for the Polygon HTTP client helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.exceptions import PolygonAPIError
from src.ingestion.client import polygon_get


@pytest.mark.asyncio
async def test_polygon_get_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": [{"ticker": "AAPL"}]}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.is_closed = False

    with patch("src.ingestion.client._client", mock_client):
        data = await polygon_get("/v2/test")

    assert data["results"][0]["ticker"] == "AAPL"


@pytest.mark.asyncio
async def test_polygon_get_http_error():
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = "Forbidden"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "forbidden", request=MagicMock(), response=mock_response
    )

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.is_closed = False

    with patch("src.ingestion.client._client", mock_client):
        with pytest.raises(PolygonAPIError) as exc_info:
            await polygon_get("/v2/test")
        assert exc_info.value.status_code == 403
