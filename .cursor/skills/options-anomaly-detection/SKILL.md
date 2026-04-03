---
name: options-anomaly-detection
description: Domain knowledge for detecting anomalous options activity indicative of insider trading. Use when building or modifying the scoring engine, defining signal factors, tuning alert thresholds, implementing backtesting logic, or working on any code in scoring/ or signals/ directories.
---

# Options Anomaly Detection

## What We Are Detecting

Unusual options activity that deviates significantly from historical norms, particularly patterns consistent with informed trading ahead of material non-public information (MNPI) events such as:

- M&A announcements
- Earnings surprises (beat/miss beyond consensus)
- FDA approvals/rejections
- SEC enforcement actions
- Major contract wins/losses
- Management changes

## Signal Taxonomy

### Tier 1 — High Signal Value

**Volume Spike**: Single-day contract volume exceeding 3+ standard deviations above the 20-day rolling mean. Most reliable when concentrated in specific strikes/expirations rather than spread across the chain.

**Premium Surge**: Total dollar premium (price x volume x 100) for a contract or underlying's chain far exceeding baseline. Captures both volume and price conviction simultaneously.

**Sweep Orders**: Options bought simultaneously across multiple exchanges at the ask price, indicating urgency. Detected via trade condition codes (Polygon condition code analysis) and multi-exchange fill clustering within short time windows.

### Tier 2 — Medium Signal Value

**Open Interest Change**: Large day-over-day OI increase paired with volume spike suggests new position opening (not closing). A volume spike without OI change may indicate day-trading, which is less informative.

**OTM Clustering**: Disproportionate volume in out-of-the-money options (delta < 0.30 for calls, delta > -0.30 for puts). Informed traders often buy cheap OTM options for leverage on expected moves.

**Time-to-Expiry Bias**: Unusually heavy volume in near-term expirations (< 14 DTE) suggests a trader expects a catalyst soon. Short-dated options provide maximum leverage for informed bets.

### Tier 3 — Supporting Signals

**Bid-Ask Spread Compression**: When unusual volume coincides with tighter-than-normal spreads, it suggests market makers are accommodating informed flow (or that the order size is large enough to attract liquidity).

**Underlying Price Correlation**: Stock price moving in the direction of the options bet on the same day. Adds conviction when present but absence does not invalidate — informed traders often act before the stock moves.

**Call/Put Skew Shift**: Sudden change in the put-call ratio or implied volatility skew for a specific expiration.

### Gate — Already Priced In

All our data is 15 minutes delayed. By the time we observe an options anomaly, the underlying stock may have already moved in the direction of the bet. This filter is a hard gate (not a weighted factor):

- Compute the underlying stock's % move since the options activity was recorded
- If calls are the anomaly and the stock is already up >2%, suppress
- If puts are the anomaly and the stock is already down >2%, suppress
- This prevents alerting on opportunities that have already passed
- The 2% threshold is configurable and should be tuned via backtesting

## Distinguishing Insider Trading from Legitimate Flow

### Likely Informed (Higher Score)

- Activity concentrated in 1-2 specific strikes/expirations (not spread across chain)
- OTM options with short time to expiry
- New positions (volume > prior OI)
- Occurs in liquid names with normally low options volume for that strike
- No corresponding news, analyst upgrades, or known catalysts
- Timing: 1-10 days before catalyst materializes

### Likely Institutional/Hedging (Lower Score)

- Activity spread across many strikes (roll, spread, or hedge)
- ATM or ITM options (delta hedging)
- Volume roughly matches prior OI (position closing/rolling)
- Correlated with index or sector-wide flows
- Follows known catalyst (earnings date is public, FDA date is known)
- Large block trades at mid-price (negotiated, not urgent)

## Statistical Methodology

### Rolling Baseline

For each contract (or underlying aggregate), maintain a 20-trading-day rolling window of:
- Daily volume
- Daily OI
- Daily dollar premium
- Daily implied volatility

Exclude current observation from baseline. Require minimum 5 data points.

### Z-Score Computation

```
z = (observed - mean_baseline) / max(std_baseline, floor)
```

Use `floor = 0.01` to prevent division by zero on low-activity contracts. For contracts with zero baseline volume, use the underlying's aggregate baseline instead.

### Multi-Factor Composite Score

```python
composite = sum(factor.z_score * factor.weight for factor in factors)
normalized = min(10.0, max(0.0, composite * scale_factor))
```

Starting weights (tunable):

| Factor | Weight |
|--------|--------|
| vol_z (volume spike) | 0.25 |
| prem_z (premium surge) | 0.20 |
| sweep_z (sweep detection) | 0.15 |
| oi_z (OI change) | 0.15 |
| otm_z (OTM clustering) | 0.10 |
| tte_z (time-to-expiry) | 0.08 |
| spread_z (bid-ask) | 0.05 |
| underlying_z (stock move) | 0.02 |

Total = 1.00. Adjust based on backtesting performance.

### Alert Threshold

Fire alert when `composite_score >= ANOMALY_ALERT_MIN_SCORE` (default 7.5 on 0-10 scale) AND the already-priced-in gate has not suppressed the signal. Target: 1-5 alerts per trading day. Do not re-alert on the same contract within the same trading day unless the score increases by 1.0+.

## Backtesting Framework

### Default Strategy: TP500

1. **Entry**: Option price at time of signal trigger on signal day
2. **Exit**: First subsequent session close >= 5x entry price (TP500), OR hold to expiration
3. **Outcome**: Win (hit TP500) or loss (expired worthless or below 5x)

### Metrics to Track

- **Hit Rate**: % of signals that reach TP500
- **Average Return**: Mean return across all signals (including full losses)
- **Profit Factor**: Gross wins / gross losses
- **Time to Exit**: Average days from signal to TP500 (for winners)
- **Score Calibration**: Hit rate bucketed by score range (7.5-8.0, 8.0-8.5, etc.)

### Baseline Comparison

Compare signal performance against:
- Random option selection (same strike/expiry profile, random entry day)
- All options with similar volume characteristics
- Market-wide option returns for the same period

### Future Extensions

- Variable TP levels: 2x, 3x, 10x
- Time-limited exits: max hold N days
- Factor ablation: test removing each factor to measure marginal contribution
- Walk-forward optimization: re-fit weights on rolling historical windows

## Key Academic & Industry References

- Augustin, Brenner, Hu, Subrahmanyam (2019): "Informed Options Trading Prior to M&A" — documents systematic options activity 1-5 days before M&A announcements
- Cremers, Fodor, Weinbaum (2021): "Where Does Informed Trading Happen in Options Markets?" — sweep orders and aggressive limit orders carry the most signal
- CBOE / OCC daily volume reports — public baseline for market-wide options activity norms
- SEC enforcement actions database — historical cases of options-based insider trading provide labeled positive examples for validation
