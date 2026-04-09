# Option Finder

Scans the entire US options market via Polygon.io, compares activity against a 20-day statistical baseline, and emails high-conviction alerts when anomalous activity is detected. Not an auto-trading system -- alerts are for human review only.

## Project Structure

```
src/
  config/           Settings (from .env) and constants (weights, thresholds)
  database/         SQLAlchemy 2.0 models, Alembic migrations, repository layer
  ingestion/        Polygon REST client, stock/option snapshot fetchers, news, flat-file loader
  scoring/          Z-score baseline, 11 factor calculators, composite scorer, priced-in gate
  alerts/           Email formatter (HTML + plaintext), SMTP sender, deduplication
  scheduler/        Main scan loop, single-cycle pipeline orchestration
  dashboard/        Streamlit app (alert feed, ticker lookup, system status)
  backtest/         (Stub) TP500 backtesting framework
scripts/            Backfill script, diagnostic probes
tests/              pytest suite (38 tests covering config, ingestion, scoring, alerts)
alembic/            Database migration scripts
```

Module dependency order: `config` -> `database` -> `ingestion` -> `scoring` -> `alerts` -> `scheduler` -> `dashboard`.

## How the Scanner Works

### Single Scan Cycle

1. **Market check** -- Queries Polygon `/v1/marketstatus/now`. If closed (weekends, holidays), the cycle returns immediately and sleeps 5 minutes before checking again.
2. **Stock snapshot** -- Fetches all ~8,000 US equities via `/v2/snapshot/locale/us/markets/stocks/tickers`. Captures today's change % for each ticker (used by the priced-in gate).
3. **Option chain fetch** -- For every stock with trading volume, fetches the full option chain via `/v3/snapshot/options/{ticker}` with cursor-based pagination (250 contracts/page). Includes greeks, IV, OI, volume, bid/ask, underlying price.
4. **DB upsert** -- All snapshot data is bulk-upserted into PostgreSQL. Each contract gets one row per day in `options_snapshots`.
5. **Scoring** -- Every contract with volume >= 100 and dollar premium >= $10K is scored:
   - Load the contract's prior 20 trading days from the database
   - Compute z-scores for 11 factors (see below)
   - Apply weighted sum, dampen by baseline confidence, normalize to 0-10 scale
   - Check the "already priced in" gate
6. **Trigger persistence** -- Contracts must trigger in 2+ consecutive scan cycles before an alert fires. This filters out ephemeral volume spikes that disappear between delayed snapshots.
7. **Alerting** -- If composite score >= threshold and not priced in: dedup check, fetch relevant news and earnings context, format HTML digest email, send via Gmail SMTP.
8. **Sleep** -- Wait 15 minutes (matching Polygon's data delay), then repeat.

### Data Delay

All Polygon data is 15 minutes delayed. This is the defining constraint. The scanner runs continuously during market hours (9:30 AM - 4:00 PM ET) to catch anomalies as early as possible within the delay window.

## Scoring Algorithm

### Factors

Each factor computes a z-score: `(observed - mean) / std` against a 20-day rolling baseline for that specific contract.

| Factor | Key | Weight | What It Measures |
|--------|-----|--------|------------------|
| Volume Spike | `vol_z` | 0.17 | Contract volume vs 20-day average |
| IV Spike | `iv_z` | 0.14 | Implied volatility vs its own 20-day baseline; captures the market pricing in an event independent of volume |
| Premium Surge | `prem_z` | 0.12 | Dollar premium (price x volume x 100) vs baseline |
| Volume/OI Ratio | `vol_oi_z` | 0.12 | Today's volume / prior-day OI vs baseline; ratio > 1.0 = more contracts traded than currently exist, strongly suggests new position opening |
| Chain Volume | `chain_vol_z` | 0.09 | Total chain volume vs 20-day avg; dampens isolated contract spikes |
| Delta Concentration | `delta_conc_z` | 0.08 | Fraction of chain volume in deep-OTM contracts (\|delta\| < 0.20); uses greeks directly, falls back to strike/price for contracts without delta |
| OI Change | `oi_z` | 0.08 | Day-over-day open interest delta vs baseline. Note: OI is always the prior-day settlement figure (OCC calculates after close), so this is a lagging indicator |
| Earnings Proximity | `earnings_z` | 0.07 | Dampener: applies a negative z-score when the underlying is within 14 days of an earnings report, since pre-earnings volume spikes are expected behaviour |
| Time-to-Expiry | `tte_z` | 0.06 | Shorter DTE = stronger signal (< 14 DTE contributes positively) |
| Bid-Ask Spread | `spread_z` | 0.04 | Tighter-than-normal spread on unusual volume (inverted z-score) |
| Underlying Move | `underlying_z` | 0.03 | Stock move correlated with bet direction |

**Important data semantics**: Open interest from Polygon's snapshot API is always "the quantity of this contract held at the end of the last trading day" (prior-day settlement). It is NOT an intraday figure. The Volume/OI ratio compensates by comparing today's real-time volume against yesterday's OI -- the standard method for detecting aggressive new positioning. Earnings dates are estimated by fetching quarterly filing dates from Polygon's `/vX/reference/financials` endpoint and projecting the next date from the observed cadence.

### Composite Score

```
raw_composite = sum(z_score * weight for each factor)
normalized = clamp(raw_composite * 2.0, 0, 10)
```

The `* 2.0` scaling factor is an initial heuristic. It should be recalibrated once backtesting data is available (see Next Steps).

### "Already Priced In" Gate

A binary suppression filter, not a weighted factor. If the underlying stock has already moved > 2% in the direction implied by the options bet (calls + stock up, puts + stock down), the alert is killed regardless of score. This accounts for the 15-minute data delay -- if the stock already moved, the options activity was likely reactive, not predictive.

### Baseline Confidence Dampener

The composite score is multiplied by a confidence factor based on baseline depth. With the minimum 5 data points, scores are dampened to ~62.5% of their raw value; with a full 20-day baseline, no dampening occurs. This prevents unreliable z-scores from thin histories driving false triggers.

### Baseline Requirements

A contract needs at least 5 days of historical data to compute a baseline. With fewer, the z-score defaults to 0 for that factor (contributes nothing). The backfilled data from Polygon flat files means most active contracts have robust baselines from day one.

## Alert Triggers

An alert fires when ALL of these are true:
- Composite score >= `ANOMALY_ALERT_MIN_SCORE` (default 6.0, configurable in `.env`)
- Dollar premium >= $10K (the min premium gate)
- The contract is NOT already priced in (underlying move < 2% in bet direction)
- The contract has triggered in >= 2 consecutive scan cycles (trigger persistence)
- No prior "sent" alert exists for this contract today (or the score has increased by >= 1.0 since the last alert)
- `ANOMALY_EMAIL_ENABLED` is `true`

Alerts include: ticker, contract, full factor breakdown with raw values/z-scores/weights, underlying price, volume, OI, recent news headlines, and a timestamp.

## Running the System

### Prerequisites

- Python 3.11+
- PostgreSQL running locally
- Polygon.io Stocks Basic + Options Basic subscription
- Gmail app password for SMTP

### Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
cp env.template.txt .env      # Fill in credentials
alembic upgrade head          # Create database tables
```

### Start the Scanner

```bash
python -m src.main
```

Runs continuously. During market hours: fetches data, scores, alerts, sleeps 15 min, repeats. Outside market hours: checks Polygon market status every 5 min, does nothing until market opens. Ctrl+C for graceful shutdown.

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

## Configuration

All config lives in `.env`. Key settings:

| Variable | Purpose | Default |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | (required) |
| `POLYGON_API_KEY` | Polygon.io REST API key | (required) |
| `ANOMALY_ALERT_MIN_SCORE` | Composite score threshold for alerts | 6.0 |
| `ANOMALY_EMAIL_ENABLED` | Kill switch for email delivery | false |
| `SENDER_EMAIL` | Gmail address for sending alerts | (required for alerts) |
| `EMAIL_PASSWORD` | Gmail app password | (required for alerts) |
| `RECIPIENT_EMAIL` | Where alerts are delivered | (required for alerts) |

See `env.template.txt` for the full list including S3 flat-file credentials.

## Database

PostgreSQL with 6 tables:

| Table | Purpose |
|-------|---------|
| `options_snapshots` | Per-contract daily snapshot (OHLCV, greeks, OI, bid/ask) |
| `stock_snapshots` | Per-ticker daily stock data |
| `scoring_results` | Composite score + factor JSONB for scored contracts |
| `trigger_candidates` | Intra-day trigger persistence tracker (consecutive scan confirmation) |
| `alerts_sent` | Log of every alert sent/failed/suppressed |
| `backtest_runs` | Backtest metadata and results |

Historical backfill covers ~60 trading days (2026-01-05 through 2026-04-02) from Polygon flat files. This provides immediate baselines for volume and premium factors. OI, greeks, and bid/ask baselines will build up from live scans.

## Next Steps to Full Operation

### Immediate (ready now)

- [x] Scanner pipeline works end-to-end
- [x] Email delivery verified
- [x] Dashboard operational
- [x] 60-day historical backfill loaded
- [ ] **Run the scanner during a live market session**. Watch the logs, verify scoring results populate in the dashboard, confirm alert emails arrive if anything scores >= threshold.

### Short-term (1-2 weeks of live data)

- [ ] **Lower the alert threshold temporarily** to `4.0` in `.env` to see what the scorer is flagging. Review the factor breakdowns to check whether the signals make intuitive sense. Raise it back once you're satisfied.
- [ ] **Calibrate the composite score scaling factor** (currently `* 2.0` in `composite.py`). After a week of data, look at the distribution of scores in the dashboard. If most scores cluster near 0-2 and nothing reaches threshold, the scaling factor needs to increase.
- [ ] **Verify baseline quality** -- Check that contracts with 20 days of history produce meaningfully different z-scores than contracts with only 5 days. The more history, the more reliable the baseline.

### Medium-term (2-4 weeks of live data)

- [ ] **Recalibrate factor weights** -- The current 11-factor weights are literature-informed priors. Once you have a few hundred scored contracts, analyze which factors best predict subsequent underlying moves. Update weights in `src/config/constants.py` `FACTOR_WEIGHTS`.
- [ ] **Calibrate earnings proximity** -- The `earnings_z` factor estimates next earnings from quarterly filing dates (`/vX/reference/financials`). Monitor whether the projected dates are accurate and adjust the estimation logic if needed.
- [ ] **Implement sweep detection** -- True sweep detection requires trade-level condition codes and multi-exchange fill analysis, which Polygon provides via websockets or trade endpoints. This is the highest-value improvement to signal quality.
- [ ] **Build the backtester** -- The `src/backtest/` module is stubbed. The TP500 strategy (entry at signal, exit at 5x or expiration) needs implementation once there are enough scored contracts to test against.
- [ ] **Dual baseline windows** -- Add a 60-day secondary baseline alongside the 20-day primary. Require anomaly against both windows to trigger. This eliminates false positives from contracts that have been running hot for 2-3 weeks. Requires 60 days of accumulated data.

### Long-term

- [ ] **Narrow the scan universe** -- After backtesting reveals where anomalies concentrate (by sector, market cap, options liquidity), focus the scan for faster cycles.
- [ ] **Add websocket streaming** -- Replace the 15-minute polling loop with real-time trade/quote streaming for faster anomaly detection.
