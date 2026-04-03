# Option Finder

Anomalous options activity detection system for the US equity options market. Scans the full options market at short intervals during trading hours, compares activity to a statistical baseline, and produces **low-frequency, high-conviction email alerts** for human review. This is NOT an auto-trading system.

## Architecture

```
src/
  ingestion/       # Polygon REST API scrapers, flat-file (S3) bulk loaders
  database/        # SQLAlchemy 2.0 models, Alembic migrations, connection pool
  scoring/         # Z-score anomaly engine, multi-factor signal generation
  alerts/          # Email alerting (SMTP/SSL), alert formatting
  dashboard/       # Streamlit app for lookup, analysis, backtesting
  scheduler/       # APScheduler pipeline orchestration
  backtest/        # Entry-on-signal / TP500-or-expiry backtesting framework
config/            # Pydantic-settings config, constants
tests/             # pytest, fixtures per module
scripts/           # One-off utilities, data backfills
```

Module dependency order: `database` -> `ingestion` -> `scoring` -> `alerts` -> `dashboard`.

## Tech Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.11 |
| Data source | Polygon.io REST API + S3 Flat Files |
| Database | PostgreSQL (local), SQLAlchemy 2.0, Alembic |
| HTTP client | `httpx` (async) |
| Config | `pydantic-settings` (env vars from `.env`) |
| Scheduling | APScheduler / system cron |
| Dashboard | Streamlit |
| Email | `smtplib` over SSL (Gmail SMTP) |
| Testing | pytest, pytest-asyncio |

## Data Delay & Scan Strategy

**All data is 15 minutes delayed.** This is the defining constraint of the system.

By the time we observe an options anomaly, the underlying stock or option price may have already moved. The "already priced in" filter addresses this directly: if the underlying has already moved significantly in the direction of the options bet, the opportunity is gone and the activity is explained by the move rather than predictive of it. Alerts should only fire when the anomaly has NOT yet been reflected in the underlying price.

### Scan Cadence

Scan as frequently as possible during market hours. We have unlimited API calls. The more scans per day, the better our chance of catching anomalies before the underlying moves. Target: continuous loop during 9:30 AM - 4:00 PM ET, with each full cycle taking however long the API round-trips require (likely 5-15 minutes for a full market pass).

### Pipeline Workflow (Single Scan Cycle)

```
1. Check market status (skip if closed/holiday)
2. Fetch full US stock market snapshot
   → Identify underlyings with notable price moves (for "already priced in" filter)
3. For each optionable underlying, fetch option chain snapshot
   → Paginate through all contracts (greeks, IV, OI, volume, last trade/quote)
4. Upsert snapshot data into PostgreSQL
5. For each contract with meaningful activity:
   a. Load 20-day rolling baseline from DB
   b. Compute z-scores for each scoring factor
   c. Compute composite score
   d. Apply "already priced in" filter — suppress if underlying has already moved >2% in direction of bet
6. For any composite_score >= threshold: format and send email alert
7. Log cycle stats (duration, contracts scanned, alerts fired)
8. Begin next cycle immediately
```

### Universe Approach

Start broad — scan everything. Do not pre-filter by market cap, liquidity, or sector initially. Once we have backtesting data, we can identify where anomalies concentrate and narrow the scan for efficiency. The unlimited API calls make a broad approach feasible.

## Polygon.io API Access

**Note**: Polygon.io recently rebranded to Massive. They are the same company and API. All env vars use the `POLYGON_` prefix.

**Tiers**: Stocks Basic + Options Basic (paid).

| Capability | Stocks Basic | Options Basic |
|---|---|---|
| Coverage | All US stock tickers | All US options tickers |
| API calls | Unlimited | Unlimited |
| History | 5 years | 2 years |
| Delay | 15-minute | 15-minute |
| Aggregates | Minute + Second | Minute + Second |
| Snapshot | Yes | Yes |
| WebSockets | Yes | Yes |
| Greeks / IV | -- | Real-time |
| Open Interest | -- | Daily |
| Flat Files | Yes | Yes |
| Technical Indicators | SMA, EMA, RSI, MACD | SMA, EMA, RSI, MACD |

### Key REST Endpoints

```
# Option chain snapshot (greeks, IV, OI, volume, last quote/trade)
GET /v3/snapshot/options/{underlyingAsset}

# OHLC aggregates for any ticker (stock or option)
GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}

# Options contract reference data
GET /v3/reference/options/contracts

# Full US stock market snapshot
GET /v2/snapshot/locale/us/markets/stocks/tickers

# Single stock snapshot
GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}

# Ticker news with sentiment
GET /v2/reference/news

# Earnings calendar (Benzinga partner endpoint)
GET /v1/meta/symbols/{symbol}/earnings

# Dividends, splits, corporate actions
GET /v3/reference/dividends
GET /v3/reference/splits

# SEC filings (10-K sections, 8-K text, risk factors)
GET /v1/reference/sec/filings
```

### Option Ticker Format

`O:AAPL251219C00150000` = O : TICKER YYMMDD C/P STRIKE×1000

### Pagination

Polygon uses cursor-based pagination. Check for `next_url` in every response and follow it to get subsequent pages.

### Flat Files (S3)

Bulk historical data via S3-compatible endpoint:
- Endpoint: `https://files.polygon.io`
- Bucket: `flatfiles`
- Options day aggs: `us_options_opra/day_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz`
- Options minute aggs: `us_options_opra/minute_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz`

## Scoring Philosophy

### Goal
Identify options activity that is statistically anomalous relative to a rolling baseline, suggesting informed (potentially insider) trading ahead of catalysts.

### Approach
Multi-factor composite score using z-scores. Each factor compares the current observation to a rolling 20-day baseline for that specific contract or underlying.

### Scoring Factors

| Factor | What It Measures | Weight Range |
|--------|-----------------|--------------|
| Volume Spike | Contract volume vs 20-day avg | High |
| OI Change | Day-over-day open interest delta | Medium |
| Premium Surge | Dollar premium (price × volume × 100) vs baseline | High |
| OTM Clustering | Concentration of activity in out-of-the-money strikes | Medium |
| Time-to-Expiry | Proximity to expiration (short-dated = higher signal) | Medium |
| Bid-Ask Spread | Tight spreads on unusual volume suggest informed flow | Low-Medium |
| Underlying Move | Stock price movement correlated with options activity | Low |
| Sweep Detection | Simultaneous fills across exchanges at the ask | High |
| Already Priced In | Underlying has NOT yet moved in direction of bet (suppress if >2%) | Gate |

The "Already Priced In" factor is a gate, not a weighted contributor. If the underlying has already moved >2% in the direction implied by the options activity (calls + stock up, puts + stock down), the alert is suppressed entirely regardless of composite score. This accounts for our 15-minute data delay.

### Composite Score
Weighted sum of factor z-scores normalized to 0-10 scale. Alert threshold: configurable via `ANOMALY_ALERT_MIN_SCORE` (default 7.5).

### Transparency
Every alert includes the full factor breakdown so a human reviewer can evaluate conviction.

## Alert System

- Trigger: composite score >= threshold AND not already priced in
- Channel: Email via Gmail SMTP/SSL
- Content: ticker, contract, score breakdown, current price, volume context, relevant news, upcoming catalysts (earnings, FDA dates), time since activity detected, underlying move since activity
- Frequency: Low — aim for 1-5 alerts per trading day maximum
- Dedup: Do not re-alert on the same contract within the same trading day unless the score increases by 1.0+

## Backtesting

### Default Strategy (TP500)
1. **Entry**: Signal-day option price at time of trigger
2. **Exit**: First later session where close >= 5x entry price, OR hold to expiration (typically full loss)
3. **Metric**: Hit rate, average return, profit factor

### Future Extensions
- Variable take-profit levels (2x, 3x, 10x)
- Time-based exits (hold N days max)
- Comparison against random baseline

## Database Conventions

- All table/column names: `snake_case`
- Every table has `id` (bigint PK), `created_at`, `updated_at`
- Composite indexes on `(ticker, date)` for all market data tables
- Partition large tables (options snapshots, minute aggs) by date
- Use `NUMERIC` for prices, never `FLOAT`
- Store timestamps as `TIMESTAMPTZ` (UTC)

## Environment Variables

See `env.template.txt` for the full list. Key groups:
- `DATABASE_URL` — PostgreSQL connection string
- `POLYGON_API_KEY` — REST API authentication
- `POLYGON_S3_*` — Flat file access credentials
- `SENDER_EMAIL`, `EMAIL_PASSWORD`, `RECIPIENT_EMAIL` — Alert delivery
- `ANOMALY_ALERT_MIN_SCORE` — Score threshold for triggering alerts
- `ANOMALY_EMAIL_ENABLED` — Kill switch for email alerts

## Coding Conventions

- **Type hints** on all function signatures and return types
- **Docstrings** on all public functions (Google style)
- **Logging** via `logging` module with structured context (ticker, score, etc.) — never `print()`
- **Config** via `pydantic-settings` `BaseSettings` classes, loaded from `.env`
- **Async** where possible for I/O-bound work (API calls, DB queries)
- **Error handling**: custom exception hierarchy rooted at `OptionFinderError`; never bare `except:`
- **Testing**: pytest with fixtures per module; mock external APIs in tests
