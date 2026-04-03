# Polygon.io Full API Reference Index

Full documentation: https://polygon.io/docs
LLM-friendly index: https://polygon.io/docs/llms.txt

## Flat Files

- [Options Day Aggregates](https://polygon.io/docs/flat-files/options/day-aggregates): OHLCV at daily granularity for all US options
- [Options Minute Aggregates](https://polygon.io/docs/flat-files/options/minute-aggregates): OHLCV at minute granularity for all US options
- [Options Quotes](https://polygon.io/docs/flat-files/options/quotes): Top of book quotes with nanosecond timestamps
- [Options Trades](https://polygon.io/docs/flat-files/options/trades): Tick-level trades with nanosecond timestamps
- [Stocks Day Aggregates](https://polygon.io/docs/flat-files/stocks/day-aggregates): Daily OHLCV for all US stocks
- [Stocks Minute Aggregates](https://polygon.io/docs/flat-files/stocks/minute-aggregates): Minute OHLCV for all US stocks
- [Stocks Quotes](https://polygon.io/docs/flat-files/stocks/quotes): Top of book quotes
- [Stocks Trades](https://polygon.io/docs/flat-files/stocks/trades): Tick level trades

## REST — Options

- [Custom Bars (OHLC)](https://polygon.io/docs/rest/options/aggregates/custom-bars): Aggregated OHLC for a specific options contract
- [Daily Ticker Summary](https://polygon.io/docs/rest/options/aggregates/daily-ticker-summary): Open/close for a contract on a date
- [Previous Day Bar](https://polygon.io/docs/rest/options/aggregates/previous-day-bar): Previous day OHLC
- [All Contracts](https://polygon.io/docs/rest/options/contracts/all-contracts): Index of all options contracts (active + expired)
- [Contract Overview](https://polygon.io/docs/rest/options/contracts/contract-overview): Details for a specific contract
- [Option Chain Snapshot](https://polygon.io/docs/rest/options/snapshots/option-chain-snapshot): Full snapshot of all contracts for an underlying
- [Option Contract Snapshot](https://polygon.io/docs/rest/options/snapshots/option-contract-snapshot): Snapshot for a single contract
- [Last Trade](https://polygon.io/docs/rest/options/trades-quotes/last-trade): Latest trade for an options contract
- [Quotes](https://polygon.io/docs/rest/options/trades-quotes/quotes): Historical quotes for a contract
- [Trades](https://polygon.io/docs/rest/options/trades-quotes/trades): Tick-level trade data for a contract
- [EMA](https://polygon.io/docs/rest/options/technical-indicators/exponential-moving-average)
- [MACD](https://polygon.io/docs/rest/options/technical-indicators/moving-average-convergence-divergence)
- [RSI](https://polygon.io/docs/rest/options/technical-indicators/relative-strength-index)
- [SMA](https://polygon.io/docs/rest/options/technical-indicators/simple-moving-average)

## REST — Stocks

- [Custom Bars (OHLC)](https://polygon.io/docs/rest/stocks/aggregates/custom-bars): Aggregated OHLC for a stock
- [Daily Market Summary](https://polygon.io/docs/rest/stocks/aggregates/daily-market-summary): OHLCV for all US stocks on a date
- [Daily Ticker Summary](https://polygon.io/docs/rest/stocks/aggregates/daily-ticker-summary): Open/close for a stock on a date
- [Previous Day Bar](https://polygon.io/docs/rest/stocks/aggregates/previous-day-bar): Previous day OHLC
- [Full Market Snapshot](https://polygon.io/docs/rest/stocks/snapshots/full-market-snapshot): Snapshot of entire US stock market
- [Single Ticker Snapshot](https://polygon.io/docs/rest/stocks/snapshots/single-ticker-snapshot): Snapshot for one ticker
- [Top Market Movers](https://polygon.io/docs/rest/stocks/snapshots/top-market-movers): Top 20 gainers/losers
- [Last Quote](https://polygon.io/docs/rest/stocks/trades-quotes/last-quote): Latest NBBO quote
- [Last Trade](https://polygon.io/docs/rest/stocks/trades-quotes/last-trade): Latest trade
- [Quotes](https://polygon.io/docs/rest/stocks/trades-quotes/quotes): Historical NBBO quotes
- [Trades](https://polygon.io/docs/rest/stocks/trades-quotes/trades): Tick-level trades
- [EMA](https://polygon.io/docs/rest/stocks/technical-indicators/exponential-moving-average)
- [MACD](https://polygon.io/docs/rest/stocks/technical-indicators/moving-average-convergence-divergence)
- [RSI](https://polygon.io/docs/rest/stocks/technical-indicators/relative-strength-index)
- [SMA](https://polygon.io/docs/rest/stocks/technical-indicators/simple-moving-average)

## REST — Stocks Reference & Fundamentals

- [All Tickers](https://polygon.io/docs/rest/stocks/tickers/all-tickers): List all supported tickers
- [Ticker Overview](https://polygon.io/docs/rest/stocks/tickers/ticker-overview): Details for a ticker
- [Related Tickers](https://polygon.io/docs/rest/stocks/tickers/related-tickers): Tickers related by news/returns
- [Ticker Types](https://polygon.io/docs/rest/stocks/tickers/ticker-types): Supported ticker type codes
- [News](https://polygon.io/docs/rest/stocks/news): Recent news with sentiment
- [Dividends](https://polygon.io/docs/rest/stocks/corporate-actions/dividends): Dividend history
- [Splits](https://polygon.io/docs/rest/stocks/corporate-actions/splits): Stock split history
- [Ticker Events](https://polygon.io/docs/rest/stocks/corporate-actions/ticker-events): Key corporate events timeline
- [Balance Sheets](https://polygon.io/docs/rest/stocks/fundamentals/balance-sheets)
- [Cash Flow Statements](https://polygon.io/docs/rest/stocks/fundamentals/cash-flow-statements)
- [Income Statements](https://polygon.io/docs/rest/stocks/fundamentals/income-statements)
- [Ratios](https://polygon.io/docs/rest/stocks/fundamentals/ratios): Valuation, profitability, leverage
- [Float](https://polygon.io/docs/rest/stocks/fundamentals/float): Free float data
- [Short Interest](https://polygon.io/docs/rest/stocks/fundamentals/short-interest): Bi-monthly FINRA data
- [Short Volume](https://polygon.io/docs/rest/stocks/fundamentals/short-volume): Daily off-exchange short volume

## REST — SEC Filings

- [SEC EDGAR Index](https://polygon.io/docs/rest/stocks/filings/index): Master filing index
- [10-K Sections](https://polygon.io/docs/rest/stocks/filings/10-k-sections): Plain-text 10-K content
- [8-K Text](https://polygon.io/docs/rest/stocks/filings/8-k-text): Parsed 8-K content
- [Risk Factors](https://polygon.io/docs/rest/stocks/filings/risk-factors): Classified risk disclosures
- [Risk Categories](https://polygon.io/docs/rest/stocks/filings/risk-categories): Taxonomy for risk classification

## REST — Partners (Benzinga)

- [Earnings](https://polygon.io/docs/rest/partners/benzinga/earnings): Historical/upcoming earnings with EPS and revenue estimates
- [Analyst Ratings](https://polygon.io/docs/rest/partners/benzinga/analyst-ratings): Rating actions and price targets
- [Consensus Ratings](https://polygon.io/docs/rest/partners/benzinga/consensus-ratings): Aggregated analyst consensus
- [Corporate Guidance](https://polygon.io/docs/rest/partners/benzinga/corporate-guidance): Company earnings guidance
- [News](https://polygon.io/docs/rest/partners/benzinga/news): Real-time Benzinga articles
- [Bulls Bears Say](https://polygon.io/docs/rest/partners/benzinga/bulls-bears-say): Analyst bull/bear summaries
- [Analyst Details](https://polygon.io/docs/rest/partners/benzinga/analyst-details): Analyst profiles
- [Firm Details](https://polygon.io/docs/rest/partners/benzinga/firm-details): Analyst firm data

## REST — Economy

- [Treasury Yields](https://polygon.io/docs/rest/economy/treasury-yields): US treasury yield curve
- [Inflation](https://polygon.io/docs/rest/economy/inflation): Realized CPI data
- [Inflation Expectations](https://polygon.io/docs/rest/economy/inflation-expectations): Forward expectations
- [Labor Market](https://polygon.io/docs/rest/economy/labor-market): Unemployment, participation, earnings

## REST — Market Operations

- [Market Status](https://polygon.io/docs/rest/stocks/market-operations/market-status): Current trading status
- [Market Holidays](https://polygon.io/docs/rest/stocks/market-operations/market-holidays): Upcoming holidays
- [Exchanges](https://polygon.io/docs/rest/stocks/market-operations/exchanges): Exchange list
- [Condition Codes](https://polygon.io/docs/rest/stocks/market-operations/condition-codes): Trade/quote conditions

## WebSocket — Options

- [Aggregates Per Minute](https://polygon.io/docs/websocket/options/aggregates-per-minute)
- [Aggregates Per Second](https://polygon.io/docs/websocket/options/aggregates-per-second)
- [Fair Market Value](https://polygon.io/docs/websocket/options/fair-market-value)
- [Quotes](https://polygon.io/docs/websocket/options/quotes)
- [Trades](https://polygon.io/docs/websocket/options/trades)

## WebSocket — Stocks

- [Aggregates Per Minute](https://polygon.io/docs/websocket/stocks/aggregates-per-minute)
- [Aggregates Per Second](https://polygon.io/docs/websocket/stocks/aggregates-per-second)
- [Fair Market Value](https://polygon.io/docs/websocket/stocks/fair-market-value)
- [Quotes](https://polygon.io/docs/websocket/stocks/quotes)
- [Trades](https://polygon.io/docs/websocket/stocks/trades)
- [Imbalances (NOI)](https://polygon.io/docs/websocket/stocks/imbalances)
- [LULD](https://polygon.io/docs/websocket/stocks/luld)
