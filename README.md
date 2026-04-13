# Option Finder

Scans the entire US options market via [Polygon.io](https://polygon.io), compares activity against a 20-day statistical baseline, and emails high-conviction alerts when anomalous activity is detected. Not an auto-trading system -- alerts are for human review only.

## Prerequisites

- **Python 3.11+**
- **PostgreSQL** (local or remote)
- **Polygon.io** Stocks Basic + Options Basic subscription (paid -- unlimited API calls, 15-min delayed data)
- **Gmail app password** for SMTP alerts (optional -- alerts can be disabled)

## Quick Start

```bash
# Clone and install
git clone https://github.com/Karchensky/option_finder.git
cd option_finder
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -e ".[dev]"

# Configure
cp env.template.txt .env
# Edit .env with your credentials (see Configuration below)

# Create database tables
alembic upgrade head

# Start the scanner
python -m src.main
```

The scanner runs continuously during market hours (9:30 AM -- 4:00 PM ET). Outside market hours it checks Polygon's market status every 5 minutes and idles until the next open. Ctrl+C for graceful shutdown.

### Start the Dashboard

```bash
streamlit run src/dashboard/app.py
```

Three pages:
- **Alert Feed** -- Sent alerts, top scoring contracts, daily scoring volume chart
- **Ticker Lookup** -- Search any underlying, view candlestick chart, options chain with scores, volume/OI history
- **System Status** -- Data freshness, row counts, table sizes, top underlyings by volume

### Run Tests

```bash
python -m pytest tests/ -v
```

### Historical Backfill (optional)

Load bulk historical data from Polygon flat files to seed baselines before your first live session:

```bash
python scripts/backfill_flatfiles.py --start 2026-01-01 --end 2026-04-01
```

This populates `options_snapshots` so the scoring engine has 20-day baselines from day one. Without a backfill, baselines build up naturally from live scans (~4 weeks to full depth).

## Project Structure

```
src/
  config/           Settings (from .env) and constants (weights, thresholds)
  database/         SQLAlchemy 2.0 async models, Alembic migrations, repository layer
  ingestion/        Polygon REST client, stock/option snapshot fetchers, news, flat-file loader
  scoring/          Z-score baseline, 12 factor calculators, composite scorer, priced-in gate
  alerts/           Email formatter (HTML + plaintext), SMTP sender, deduplication
  scheduler/        Main scan loop, single-cycle pipeline orchestration
  dashboard/        Streamlit app (alert feed, ticker lookup, system status)
  backtest/         (Stub) TP500 backtesting framework
scripts/            Backfill script, diagnostic probes
tests/              pytest suite (47+ tests covering config, ingestion, scoring, alerts)
alembic/            Database migration scripts (5 revisions)
```

Module dependency order: `config` -> `database` -> `ingestion` -> `scoring` -> `alerts` -> `scheduler` -> `dashboard`.

## How the Scanner Works

### Single Scan Cycle

1. **Market check** -- Queries Polygon `/v1/marketstatus/now`. Skips if closed/holiday.
2. **Stock snapshot** -- Fetches all ~8,000 US equities via `/v2/snapshot/locale/us/markets/stocks/tickers`. Captures today's change % (for the priced-in gate) and historical daily returns (for realized volatility normalization).
3. **Option chain fetch** -- For every stock with trading volume, fetches the full option chain via `/v3/snapshot/options/{ticker}` with cursor-based pagination (250 contracts/page). Includes greeks, IV, OI, volume, bid/ask, underlying price.
4. **DB upsert** -- All snapshot data is bulk-upserted into PostgreSQL (`options_snapshots` is range-partitioned by month).
5. **Scoring** -- Every contract with volume >= 100 and dollar premium >= $10K is scored:
   - Load the contract's prior 20 trading days from the database
   - Compute z-scores for 12 weighted factors (see Scoring Algorithm below)
   - Apply weighted sum, dampen by baseline confidence, normalize to 0-10 scale
   - Check the "already priced in" gate
6. **Trigger persistence** -- Contracts must trigger in 2+ consecutive scan cycles before an alert fires. Candidates that disappear from one scan get a configurable grace period (`TRIGGER_EXPIRE_GRACE_SCANS`, default 1) before being expired, so illiquid options that temporarily gap between snapshots aren't immediately reset.
7. **Deduplication** -- Same-day dedup prevents re-alerting on the same contract unless the score increases by >= 1.0. Cross-day dedup checks whether the same contract triggered an alert within the last 3 trading days with a similar score (delta < 1.5), suppressing repeated alerts on multi-day activity.
8. **Alerting** -- If all conditions pass: fetch relevant news and earnings context, format HTML digest email, send via Gmail SMTP.
9. **Alert retry** -- Failed alerts (SMTP errors, transient failures) are retried at the end of each scan cycle (up to 3 attempts per alert).

### Data Delay

All Polygon data is 15 minutes delayed. This is the defining constraint. The scanner runs continuously during market hours to catch anomalies as early as possible within the delay window.

## Scoring Algorithm

### Factors

Each factor computes a z-score: `(observed - mean) / std` against a 20-day rolling baseline for that specific contract.

| Factor | Key | Weight | What It Measures |
|--------|-----|--------|------------------|
| Volume Spike | `vol_z` | 0.16 | Contract volume vs 20-day average |
| IV Spike | `iv_z` | 0.13 | Implied volatility vs its own 20-day baseline |
| Premium Surge | `prem_z` | 0.11 | Dollar premium (price x volume x 100) vs baseline |
| Volume/OI Ratio | `vol_oi_z` | 0.11 | Today's volume / prior-day OI vs baseline; ratio > 1.0 suggests new position opening |
| Sweep Proxy | `sweep_z` | 0.09 | Volume-extremity proxy (contributes only when volume exceeds 2 sigma above mean) |
| Chain Volume | `chain_vol_z` | 0.07 | Total chain volume vs 20-day avg; contextualizes isolated contract spikes |
| Delta Concentration | `delta_conc_z` | 0.07 | Fraction of chain volume in deep-OTM contracts (\|delta\| < 0.20) |
| OI Change | `oi_z` | 0.07 | Day-over-day OI delta vs baseline (lagging: prior-day settlement) |
| Earnings Proximity | `earnings_z` | 0.07 | Dampener near earnings (expected volume spike gets negative z) |
| Time-to-Expiry | `tte_z` | 0.05 | Shorter DTE = stronger signal (< 14 DTE contributes positively) |
| Bid-Ask Spread | `spread_z` | 0.04 | Tighter-than-normal spread on unusual volume (inverted z-score) |
| Underlying Move | `underlying_z` | 0.03 | Stock move correlated with bet direction, normalized by 20-day realized volatility |

**Thin-baseline fallback**: Contracts with 1-4 data points (newly listed, illiquid) use a conservative heuristic baseline instead of returning zero. This captures sudden activity in normally-quiet options where insider trading often first appears. Applies to `vol_z`, `prem_z`, and `iv_z`.

**Realized volatility normalization**: The `underlying_z` factor divides the stock's directional move by its 20-day realized volatility (daily return std dev). A 1% move on a low-vol utility scores higher than a 1% move on a high-vol tech stock, preventing noisy stocks from dominating this factor.

**OI zero-day filtering**: Days where a contract reports zero open interest (common for newly listed or illiquid options) are excluded from baseline calculations to prevent artificial deflation of the baseline mean.

### Composite Score

```
raw_composite = sum(z_score * weight for each factor)
raw_composite *= confidence   # baseline depth: 0.625 at 5 days .. 1.0 at 20 days
normalized = clamp(raw_composite * 2.0, 0, 10)
```

### Gates (binary filters, not weighted)

| Gate | Behavior |
|------|----------|
| Already Priced In | Suppresses if underlying moved > 2% in bet direction |
| Min Premium | Skips contracts with < $10K total dollar premium |

## Alert Triggers

An alert fires when ALL of these are true:
- Composite score >= `ANOMALY_ALERT_MIN_SCORE` (default 6.0)
- Dollar premium >= $10K
- Underlying has NOT already moved > 2% in the direction of the bet
- Contract has triggered in >= 2 consecutive scan cycles
- Not deduplicated (same-day: score delta >= 1.0; cross-day: 3-day lookback, score delta >= 1.5)
- `ANOMALY_EMAIL_ENABLED` is `true`

Alerts include: ticker, contract details, full factor breakdown with raw values/z-scores/weights, underlying price, volume, OI, recent news headlines, earnings proximity, and timestamps.

## Configuration

All config lives in `.env`. Copy `env.template.txt` and fill in your values.

| Variable | Purpose | Default |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | (required) |
| `POLYGON_API_KEY` | Polygon.io REST API key | (required) |
| `ANOMALY_ALERT_MIN_SCORE` | Composite score threshold for alerts | 6.0 |
| `ANOMALY_EMAIL_ENABLED` | Kill switch for email delivery | false |
| `SENDER_EMAIL` | Gmail address for sending alerts | (required for alerts) |
| `EMAIL_PASSWORD` | Gmail app password | (required for alerts) |
| `RECIPIENT_EMAIL` | Where alerts are delivered | (required for alerts) |
| `POLYGON_S3_ACCESS_KEY` | Flat-file access (for backfill) | (optional) |
| `POLYGON_S3_SECRET_KEY` | Flat-file secret (for backfill) | (optional) |

See `env.template.txt` for the full list.

## Database

PostgreSQL with 6 tables managed by Alembic migrations:

| Table | Purpose |
|-------|---------|
| `options_snapshots` | Per-contract daily snapshot (OHLCV, greeks, OI, bid/ask). Monthly range-partitioned by `snap_date`. |
| `stock_snapshots` | Per-ticker daily stock data |
| `scoring_results` | Composite score + factor JSONB per scored contract. Monthly range-partitioned by `snap_date`. |
| `trigger_candidates` | Intra-day trigger persistence tracker with grace period for missed scans |
| `alerts_sent` | Log of every alert sent/failed/suppressed, with retry tracking |
| `backtest_runs` | Backtest metadata and results |

### Migrations

```bash
alembic upgrade head    # Apply all migrations
alembic downgrade -1    # Roll back one migration
alembic history         # View migration history
```

Migrations 001-002 create the base schema. Migration 003 adds the trigger grace period (`missed_scans` column). Migration 004 adds a composite index on `alerts_sent` for dedup/retry queries. Migration 005 converts `options_snapshots` and `scoring_results` to monthly range-partitioned tables with automatic partition creation.

## Tuning for Your Use Case

### First week
- Set `ANOMALY_ALERT_MIN_SCORE=4.0` temporarily to see what the scorer flags. Review factor breakdowns in the dashboard to verify signals make intuitive sense. Raise the threshold once satisfied.

### After 1-2 weeks
- Check score distributions in the dashboard. If most scores cluster near 0-2 and nothing reaches threshold, increase the scaling factor in `src/scoring/composite.py`.
- Verify that contracts with 20-day baselines produce meaningfully different z-scores than those with 5-day baselines.

### After 2-4 weeks
- Analyze which factors best predict subsequent underlying moves. Update weights in `src/config/constants.py` (`FACTOR_WEIGHT_MAP`).
- Monitor whether the earnings date projection (from quarterly filing dates) is accurate for your watchlist.

### Future improvements
- **Sweep detection**: True sweep detection requires trade-level condition codes. The current `sweep_z` is a volume-extremity proxy.
- **Backtester**: The `src/backtest/` module is stubbed for a TP500 strategy (entry at signal, exit at 5x or expiration).
- **Dual baseline windows**: Add a 60-day secondary baseline alongside the 20-day primary.
- **WebSocket streaming**: Replace polling with real-time trade/quote streaming.
- **Narrowed universe**: After backtesting reveals where anomalies concentrate, focus the scan.

## License

[MIT](LICENSE)

## Setup

### Automatic start
  Open an admin terminal (right-click cmd -> Run as administrator) and run:
  schtasks /create /tn "OptionFinder" /tr "D:\Scripts\option_finder\scripts\run_all.bat" /sc onlogon /rl highest
 -- to end: schtasks /delete /tn "OptionFinder" /f

### Manual start
  Double-click:
  D:\Scripts\option_finder\scripts\run_all.bat
