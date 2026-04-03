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

### Tier 1 -- High Signal Value

**Volume Spike** (`vol_z`, weight 0.18): Single-day contract volume exceeding 3+ standard deviations above the 20-day rolling mean. Most reliable when concentrated in specific strikes/expirations rather than spread across the chain.

**Premium Surge** (`prem_z`, weight 0.13): Total dollar premium (price x volume x 100) for a contract far exceeding baseline. Captures both volume and price conviction simultaneously.

**IV Spike** (`iv_z`, weight 0.13): Implied volatility surging relative to its own 20-day history. The market is pricing in an imminent event, independent of volume -- a strong signal that complements flow-based factors.

**Volume/OI Ratio** (`vol_oi_z`, weight 0.12): Today's volume divided by prior-day settled open interest, z-scored against its 20-day baseline. A ratio > 1.0 means more contracts traded today than exist in open positions -- strongly suggests new position opening rather than closing.

**Sweep Orders** (`sweep_z`, weight 0.10): Currently a volume-extremity proxy (only contributes when volume > 2 sigma above mean). True sweep detection requires trade-level condition codes and multi-exchange fill clustering.

### Tier 2 -- Medium Signal Value

**Delta Concentration** (`delta_conc_z`, weight 0.08): Fraction of chain volume in deep-OTM contracts, using |delta| < 0.20 from greeks. Falls back to strike/price comparison when greeks are unavailable. Informed traders often buy cheap OTM options for leverage.

**Open Interest Change** (`oi_z`, weight 0.07): Day-over-day OI delta vs baseline. Note: OI is always the prior-day settlement figure (OCC calculates after market close). This is a valid but lagging signal, complemented by the real-time Volume/OI ratio.

**Earnings Proximity** (`earnings_z`, weight 0.07): Dampener that applies a negative z-score when the underlying is within 14 days of an earnings report. Options volume naturally spikes before earnings -- this prevents flagging expected pre-earnings activity as anomalous. Earnings dates estimated from quarterly filing dates via Polygon `/vX/reference/financials`.

**Time-to-Expiry Bias** (`tte_z`, weight 0.06): Short-dated options (< 14 DTE) receive positive signal. Unusually heavy volume in near-term expirations suggests a trader expects a catalyst soon.

### Tier 3 -- Supporting Signals

**Bid-Ask Spread Compression** (`spread_z`, weight 0.04): Tighter-than-normal spreads on unusual volume suggest market makers are accommodating informed flow.

**Underlying Price Correlation** (`underlying_z`, weight 0.02): Stock price moving in the direction of the options bet. Adds conviction when present but absence does not invalidate.

### Gate -- Already Priced In

Binary suppression gate (not a weighted factor). If the underlying has already moved >2% in the direction of the bet:
- Calls anomaly + stock already up >2% -> suppress
- Puts anomaly + stock already down >2% -> suppress
This accounts for the 15-minute data delay. Threshold is configurable.

## Distinguishing Insider Trading from Legitimate Flow

### Likely Informed (Higher Score)

- Activity concentrated in 1-2 specific strikes/expirations (not spread across chain)
- OTM options with short time to expiry
- New positions (volume > prior OI, high vol/OI ratio)
- Occurs in liquid names with normally low options volume for that strike
- No corresponding news, analyst upgrades, or known catalysts
- Timing: 1-10 days before catalyst materializes
- IV spiking without a known catalyst

### Likely Institutional/Hedging (Lower Score)

- Activity spread across many strikes (roll, spread, or hedge)
- ATM or ITM options (delta hedging)
- Volume roughly matches prior OI (position closing/rolling)
- Correlated with index or sector-wide flows
- Near earnings date (expected volume increase, dampened by earnings_z)
- Large block trades at mid-price (negotiated, not urgent)

## Statistical Methodology

### Rolling Baseline

For each contract (or underlying aggregate), maintain a 20-trading-day rolling window of:
- Daily volume
- Daily OI
- Daily dollar premium
- Daily implied volatility
- Daily volume/OI ratio
- Daily bid-ask spread

Exclude current observation from baseline. Require minimum 5 data points.

### Z-Score Computation

```
z = (observed - mean_baseline) / max(std_baseline, floor)
```

Use `floor = 0.01` to prevent division by zero on low-activity contracts.

### Multi-Factor Composite Score

```python
composite = sum(factor.z_score * factor.weight for factor in factors)
normalized = min(10.0, max(0.0, composite * scale_factor))
```

Current weights (11 factors, sum = 1.00):

| Factor | Key | Weight |
|--------|-----|--------|
| Volume Spike | `vol_z` | 0.18 |
| Premium Surge | `prem_z` | 0.13 |
| IV Spike | `iv_z` | 0.13 |
| Volume/OI Ratio | `vol_oi_z` | 0.12 |
| Sweep Detection | `sweep_z` | 0.10 |
| Delta Concentration | `delta_conc_z` | 0.08 |
| OI Change | `oi_z` | 0.07 |
| Earnings Proximity | `earnings_z` | 0.07 |
| Time-to-Expiry | `tte_z` | 0.06 |
| Bid-Ask Spread | `spread_z` | 0.04 |
| Underlying Move | `underlying_z` | 0.02 |

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

- Augustin, Brenner, Hu, Subrahmanyam (2019): "Informed Options Trading Prior to M&A" -- documents systematic options activity 1-5 days before M&A announcements
- Cremers, Fodor, Weinbaum (2021): "Where Does Informed Trading Happen in Options Markets?" -- sweep orders and aggressive limit orders carry the most signal
- CBOE / OCC daily volume reports -- public baseline for market-wide options activity norms
- SEC enforcement actions database -- historical cases of options-based insider trading provide labeled positive examples for validation
