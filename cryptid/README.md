# CryptoPulse AI - Autonomous Crypto Market Analyst

## Overview
CryptoPulse AI is an autonomous end-to-end Crypto Market Intelligence, Sentiment & Probabilistic Forecasting Agent designed to ingest real-time data, analyze correlations, and generate actionable market insights.

## System Architecture

### Core Components
1. **Data Ingestion Layer** - Scrapers & API Fetchers
2. **Correlation Engine** - Multi-factor analysis
3. **Sentiment Assessment** - Sector impact evaluation  
4. **Probabilistic Forecasting** - Scenario modeling with confidence intervals
5. **Notification System** - Alerts & scheduled reports
6. **User Preferences** - Configurable risk profile & delivery

## Data Sources

### On-Chain & DEX Liquidity (Micro)
- DexScreener API: Token pairs, volume, liquidity, buy/sell ratios
- Jupiter API: Aggregator volume, swap routes, limit order sentiment
- Meteora DLMM: Dynamic liquidity distribution, fee yields
- GMGN.ai: Smart money tracking, KOL wallets, CTO signals
- Token.com/Launchpads: Tokenomics, supply shifts, early interest

### Macro & Web2 Media (Macro)
- X/Twitter API & Playwright Scraper
- Bloomberg/Reuters Crypto RSS
- Reddit (r/CryptoCurrency, r/solana, etc.)
- Crypto Forums (Bitcointalk, Governance)
- Crypto Fear & Greed Index, Coinglass Liquidation Maps
- Funding Rates, BTC/ETH Open Interest

## Processing Pipeline

### Layer 1: Multi-Factor Correlation
- Macro-to-Crypto: DXY, Fed Rates, Treasury Yields, S&P 500 vs BTC/ETH
- On-Chain Flow: DEX liquidity shifts vs social velocity (X/Reddit)
- Smart Money Divergence: GMGN wallet accumulation vs retail sentiment

### Layer 2: Sector Impact Assessment
- DeFi & Liquidity Protocols (Solana AMMs, Lending, Yield)
- Layer 1/Layer 2 Infrastructure (SOL, ETH, BASE, Monad, SUI)
- Memecoins & High-Beta Assets (Pump.fun, GMGN trending)
- AI & DePIN Tokens (Compute, AI agents, decentralized storage)

### Layer 3: Probabilistic Forecasting
Outputs expressed in percentages with confidence intervals:
- Directional Bias: Bullish/Bearish/Neutral (% Probability)
- Scenario Distributions:
  - Bull Scenario: ($Target with P% probability)
  - Base Scenario: ($Target with P% probability)  
  - Bear Scenario: ($Target with P% probability)
- Key Invalidation Levels: Price/structural conditions that invalidate thesis

## User Interface & Consent

### EULA Requirements
Before activation, user must acknowledge:
> "DISCLAIMER & EULA: This agent provides probabilistic market insights derived from web-scraped data and algorithmic sentiment analysis. Outputs do NOT constitute financial, investment, or trading advice. Cryptocurrencies carry high risk. The user retains 100% responsibility for execution decisions."

### Configuration (`config/user_preferences.json`)
- Risk Profile: Aggressive/Balanced/Conservative
- Focus Assets/Chains: Customizable array
- Notification Thresholds: Volatility, smart money, sentiment shifts
- Delivery Preferences: Morning digest time, alert channels

## Notification & Reporting

### Morning Briefing (Scheduled Daily)
1. Macro Backdrop: Fed news, TradFi performance
2. On-Chain Health: Liquidations, Jupiter volume, DEX movements
3. Sentiment & Correlation Score: 0-100 scale with drivers
4. Sector Impact Matrix: Winners, Losers, Emerging Trends
5. Key Levels to Watch: BTC, ETH, top 3 watchlist tokens

### Urgent Market Alerts (Event-Driven)
- Volume Anomalies: >3x spike on DexScreener/Jupiter
- Macro Volatility: Reuters/Bloomberg breaking news
- Smart Money Movements: Large wallet shifts via GMGN/Meteora

## Execution Workflow (Claude Code)
When executed, the agent runs this loop:
1. **Init Check**: Verify consent, watchlist, webhook setup
2. **Scrape & Ingest**: Fetch data from enabled endpoints
3. **Process & Reason**: Compute correlation matrix & forecast
4. **Format & Deliver**: CLI dashboard or trigger notifications

## Implementation Status
This repository contains:
- EULA acknowledgment framework
- User preferences configuration template
- System architecture documentation
- Placeholder for actual implementation

To activate full functionality, API keys and scraping capabilities would need to be configured for the enabled data sources listed above.