---
name: polygon-api
description: Polygon.io REST API patterns, endpoint reference, and data access conventions for the Option Finder project. Use when writing or modifying data ingestion code, building API client functions, working with option chain snapshots, or accessing Polygon flat files.
---

# Polygon.io API Reference

## Authentication

All requests require `apiKey` query parameter or `Authorization: Bearer <key>` header. We use `httpx.AsyncClient` with a base URL and auth injected once.

```python
client = httpx.AsyncClient(
    base_url="https://api.polygon.io",
    params={"apiKey": settings.polygon_api_key},
    timeout=httpx.Timeout(30.0),
)
```

## Option Ticker Format

`O:AAPL251219C00150000`

- `O:` prefix = options
- `AAPL` = underlying ticker
- `251219` = expiration YYMMDD
- `C` = call (`P` = put)
- `00150000` = strike price × 1000 (i.e., $150.00)

## Core Endpoints We Use

### Option Chain Snapshot

```
GET /v3/snapshot/options/{underlyingAsset}
```

Returns all contracts for an underlying with: last trade, last quote, greeks, IV, open interest, volume, day OHLC. This is the primary endpoint for live scanning.

Query params: `strike_price`, `expiration_date`, `contract_type`, `order`, `limit`, `sort`.

Response shape:

```json
{
  "results": [
    {
      "break_even_price": 155.50,
      "day": {"open": 5.10, "high": 5.80, "low": 4.90, "close": 5.50, "volume": 1234, "vwap": 5.35},
      "details": {"contract_type": "call", "exercise_style": "american", "expiration_date": "2025-12-19", "shares_per_contract": 100, "strike_price": 150, "ticker": "O:AAPL251219C00150000"},
      "greeks": {"delta": 0.65, "gamma": 0.03, "theta": -0.05, "vega": 0.15},
      "implied_volatility": 0.32,
      "open_interest": 5000,
      "underlying_asset": {"ticker": "AAPL", "price": 152.30, "change_to_break_even": 3.20}
    }
  ],
  "next_url": "https://api.polygon.io/v3/snapshot/options/AAPL?cursor=..."
}
```

### Stock/Option Aggregates (OHLC Bars)

```
GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}
```

- `timespan`: `second`, `minute`, `hour`, `day`, `week`, `month`, `quarter`, `year`
- `from`/`to`: YYYY-MM-DD or Unix ms timestamp
- Works for both stock tickers (`AAPL`) and option tickers (`O:AAPL251219C00150000`)

Response shape:

```json
{
  "results": [
    {"o": 150.0, "h": 152.0, "l": 149.5, "c": 151.0, "v": 50000, "vw": 150.8, "t": 1700000000000, "n": 1200}
  ],
  "resultsCount": 1,
  "next_url": "..."
}
```

### Options Contract Reference

```
GET /v3/reference/options/contracts
```

Query params: `underlying_ticker`, `contract_type`, `expiration_date`, `strike_price`, `expired`.

### Full Stock Market Snapshot

```
GET /v2/snapshot/locale/us/markets/stocks/tickers
```

Returns snapshot for every US stock. Use for screening underlyings with unusual moves.

### Ticker News

```
GET /v2/reference/news?ticker={ticker}&limit=10
```

Returns articles with `title`, `description`, `published_utc`, `tickers`, `keywords`.

## Pagination Pattern

Polygon uses cursor-based pagination. Always check for `next_url`:

```python
async def fetch_all_pages(client: httpx.AsyncClient, url: str) -> list[dict]:
    results = []
    while url:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        url = data.get("next_url")
    return results
```

## Flat Files (S3 Bulk Data)

For historical backfills, use S3-compatible access:

```python
import boto3

s3 = boto3.client(
    "s3",
    endpoint_url=settings.polygon_flatfiles_endpoint,  # https://files.polygon.io
    aws_access_key_id=settings.polygon_s3_access_key,
    aws_secret_access_key=settings.polygon_s3_secret_key,
)

s3.download_file(
    Bucket="flatfiles",
    Key="us_options_opra/day_aggs_v1/2025/01/2025-01-15.csv.gz",
    Filename="local_file.csv.gz",
)
```

File paths follow: `{prefix}/YYYY/MM/YYYY-MM-DD.csv.gz`

## Rate Limits & Best Practices

- Our tier has unlimited API calls, but use reasonable batch sizes
- Add 100ms delay between paginated requests to be respectful
- Use `limit=250` (max) on paginated endpoints to minimize round-trips
- Cache reference data (contract details, ticker info) — it changes infrequently
- For full-market scans, prefer the snapshot endpoint over individual ticker queries

## Additional Resources

- For the complete Polygon API index, see [reference.md](reference.md)
- Full docs: https://polygon.io/docs
- LLM-friendly docs index: https://polygon.io/docs/llms.txt
