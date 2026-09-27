#!/usr/bin/env python3
"""
CryptoPulse AI - Autonomous Crypto Market Analyst & Sentiment Agent
Core implementation framework
"""

import json
import time
import datetime
import requests
import logging
import asyncio
import aiohttp
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

# Try to import playwright, but make it optional for environments where it's not available
try:
    from playwright.async_api import async_playwright, BrowserContext, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Module-level logger
logger = logging.getLogger(__name__)
if not PLAYWRIGHT_AVAILABLE:
    logger.warning("Playwright not available. Some scraping features will be disabled.")

# Configuration
CONFIG_PATH = "config/user_preferences.json"
EULA_PATH = "EULA_ACKNOWLEDGMENT.md"

class RiskProfile(Enum):
    AGGRESSIVE = "Aggressive"
    BALANCED = "Balanced"
    CONSERVATIVE = "Conservative"

class SignalStrength(Enum):
    WEAK = "Weak"
    MODERATE = "Moderate"
    STRONG = "Strong"

@dataclass
class MarketSignal:
    timestamp: datetime.datetime
    source: str
    symbol: str
    signal_type: str
    strength: SignalStrength
    confidence: float  # 0-1
    data: Dict[str, Any]

@dataclass
class ProbabilisticForecast:
    timestamp: datetime.datetime
    symbol: str
    timeframe: str
    directional_bias: Dict[str, float]  # {"bullish": 0.6, "bearish": 0.3, "neutral": 0.1}
    scenarios: Dict[str, Dict[str, Any]]  # bull, base, bear scenarios with targets and probabilities
    invalidation_levels: List[float]  # price levels that would invalidate thesis
    confidence_interval: float  # 0-1

# Scraper Classes
class DexScreenerScraper:
    """Fast API-first & Playwright-fallback scraper for DexScreener."""

    BASE_API_URL = "https://api.dexscreener.com/latest/dex"

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"})
        return self.session

    async def fetch_token_pairs(self, token_address: str) -> List[Dict[str, Any]]:
        """Fetch pairs directly via official DexScreener REST endpoints."""
        url = f"{self.BASE_API_URL}/tokens/{token_address}"
        session = await self._get_session()
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("pairs", [])
                else:
                    logger.warning(f"DexScreener API status {response.status}, switching to Playwright fallback.")
                    return []
        except Exception as e:
            logger.error(f"Error fetching DexScreener API: {e}")
            return []

    async def scrape_trending_playwright(self, context: BrowserContext) -> List[Dict[str, Any]]:
        """Fallback browser scraper if REST API is blocked or rate limited."""
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not available, skipping browser fallback")
            return []

        page: Page = await context.new_page()
        trending_pairs = []
        try:
            logger.info("Navigating to DexScreener trending page...")
            await page.goto("https://dexscreener.com/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector("a.ds-dex-table-row", timeout=10000)

            rows = await page.query_selector_all("a.ds-dex-table-row")
            for row in rows[:10]: # Top 10 trending
                href = await row.get_attribute("href")
                text = await row.inner_text()
                trending_pairs.append({
                    "url": f"https://dexscreener.com{href}" if href else None,
                    "raw_text": text.replace("\n", " ")
                })
        except Exception as e:
            logger.error(f"Playwright error on DexScreener: {e}")
        finally:
            await page.close()
        return trending_pairs

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


class GMGNScraper:
    """Stealth Playwright Scraper for GMGN.ai (Bypasses Cloudflare & Bot Controls)."""

    BASE_URL = "https://gmgn.ai"

    async def scrape_trending_tokens(self, context: BrowserContext, chain: str = "sol", time_period: str = "24h") -> List[Dict[str, Any]]:
        """
        Scrapes trending tokens and smart money activity on GMGN.
        Applies browser stealth to pass Cloudflare checks.
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not available, skipping GMGN scraping")
            return []

        page: Page = await context.new_page()
        tokens = []

        # Intercept network XHR responses to catch direct API payloads
        async def handle_response(response):
            if "quotation/v1/rank" in response.url or "swaps" in response.url:
                try:
                    if response.status == 200:
                        json_data = await response.json()
                        if "data" in json_data and "rank" in json_data["data"]:
                            nonlocal tokens
                            tokens = json_data["data"]["rank"]
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            target_url = f"{self.BASE_URL}/{chain}/trending?period={time_period}"
            logger.info(f"Navigating stealth browser to GMGN: {target_url}")

            await page.goto(target_url, wait_until="networkidle", timeout=45000)

            # Mimic real human scrolling behavior to trigger lazy dynamic fetches
            await page.mouse.wheel(0, 500)
            await asyncio.sleep(2)
            await page.mouse.wheel(0, -200)
            await asyncio.sleep(1)

            if not tokens:
                logger.info("DOM fallback parsing for GMGN tokens...")
                # DOM Fallback strategy if network interception yields no items
                elements = await page.query_selector_all("tbody tr")
                for el in elements[:10]:
                    text = await el.inner_text()
                    tokens.append({"raw_row": text.replace("\n", " | ")})

        except Exception as e:
            logger.error(f"GMGN Scraping Exception: {e}")
        finally:
            await page.close()

        return tokens


class JupiterScraper:
    """API-based Scraper for Jupiter Aggregator (Solana DEX aggregator)."""

    BASE_API_URL = "https://quote-api.jup.ag/v6"

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"})
        return self.session

    async def fetch_volume_data(self, token_mint: str = "So11111111111111111111111111111111111111112") -> List[Dict[str, Any]]:
        """Fetch 24h volume and swap data for a token via Jupiter API."""
        url = f"{self.BASE_API_URL}/stats"
        session = await self._get_session()
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    # Return volume data for SOL or specified token
                    return data.get("volume", [])
                else:
                    logger.warning(f"Jupiter API status {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching Jupiter API: {e}")
            return []

    async def fetch_price_data(self, input_mint: str, output_mint: str, amount: int) -> Dict[str, Any]:
        """Get price quote for a swap via Jupiter API."""
        url = f"{self.BASE_API_URL}/quote"
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": "50"
        }
        session = await self._get_session()
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.warning(f"Jupiter quote API status {response.status}")
                    return {}
        except Exception as e:
            logger.error(f"Error fetching Jupiter quote: {e}")
            return {}

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


class MeteoraScraper:
    """API-based Scraper for Meteora DLMM (Dynamic Liquidity Market Maker)."""

    BASE_API_URL = "https://api.meteora.ag"

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"})
        return self.session

    async def fetch_dlmm_pools(self) -> List[Dict[str, Any]]:
        """Fetch DLMM pool information including TVL and fee yields."""
        url = f"{self.BASE_API_URL}/dlmm/pools"
        session = await self._get_session()
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("pools", [])
                else:
                    logger.warning(f"Meteora API status {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching Meteora DLMM pools: {e}")
            return []

    async def fetch_pool_fees(self, pool_address: str) -> Dict[str, Any]:
        """Fetch fee information for a specific DLMM pool."""
        url = f"{self.BASE_API_URL}/dlmm/{pool_address}/fees"
        session = await self._get_session()
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.warning(f"Meteora fees API status {response.status}")
                    return {}
        except Exception as e:
            logger.error(f"Error fetching Meteora pool fees: {e}")
            return {}

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


class CryptoPulseAgent:
    def __init__(self):
        self.config = self.load_config()
        self.logger = self.setup_logging()
        self.eula_acknowledged = self.check_eula()
        self.data_sources = {}
        self.active_signals = []
        self.forecasts = {}

    def load_config(self) -> Dict[str, Any]:
        """Load user preferences from config file"""
        try:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.warning(f"Config file not found at {CONFIG_PATH}, using defaults")
            return self.get_default_config()
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing config file: {e}")
            return self.get_default_config()

    def get_default_config(self) -> Dict[str, Any]:
        """Return default configuration"""
        return {
            "riskProfile": "Balanced",
            "focusAssetsChains": ["SOL", "ETH", "BTC"],
            "notificationThresholds": {
                "priceVolatilitySpike": {"percentage": 5, "timeframe": "15m"},
                "smartMoneyInflows": {"amountUSD": 100000},
                "sentimentShift": {"fearGreedDelta": 15}
            },
            "deliveryPreferences": {
                "morningDigestTime": "08:00",
                "urgentAlerts": {"telegram": False, "webhook": "", "desktopPush": True}
            },
            "enabledDataSources": {
                "onChain": ["dexScreener", "jupiter", "meteora", "gmgn"],
                "macroWeb2": ["twitter", "reddit", "bloomberg", "reuters", "fearGreedIndex"]
            }
        }

    def setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('crypto_pulse.log'),
                logging.StreamHandler()
            ]
        )
        return logging.getLogger('CryptoPulseAI')

    def check_eula(self) -> bool:
        """Check if EULA has been acknowledged"""
        try:
            with open(EULA_PATH, 'r') as f:
                content = f.read()
                # In a real implementation, we'd check for user acknowledgment
                # For now, we'll assume it needs to be acknowledged
                return "I ACKNOWLEDGE AND ACCEPT THE EULA ABOVE" in content
        except FileNotFoundError:
            self.logger.error("EULA file not found")
            return False

    def initialize(self) -> bool:
        """Initialize the agent - check prerequisites"""
        if not self.eula_acknowledged:
            self.logger.error("EULA not acknowledged. Please acknowledge EULA before starting.")
            return False

        self.logger.info("CryptoPulse AI initialized successfully")
        self.logger.info(f"Risk Profile: {self.config['riskProfile']}")
        self.logger.info(f"Focus Assets: {self.config['focusAssetsChains']}")
        return True

    async def _scrape_data_sources_async(self) -> List[MarketSignal]:
        """
        Async method to scrape data from enabled sources using the actual scrapers
        """
        signals = []

        # Initialize scrapers if needed
        dex_scraper = DexScreenerScraper() if "dexScreener" in self.config["enabledDataSources"]["onChain"] else None
        gmgn_scraper = GMGNScraper() if "gmgn" in self.config["enabledDataSources"]["onChain"] else None
        jupiter_scraper = JupiterScraper() if "jupiter" in self.config["enabledDataSources"]["onChain"] else None
        meteora_scraper = MeteoraScraper() if "meteora" in self.config["enabledDataSources"]["onChain"] else None

        try:
            # Prepare data for the scraping pipeline
            if dex_scraper or gmgn_scraper or jupiter_scraper or meteora_scraper:
                # Run the scraping pipeline
                market_data = await self._run_scraping_pipeline(dex_scraper, gmgn_scraper, jupiter_scraper, meteora_scraper)

                # Convert DexScreener data to MarketSignals
                if dex_scraper and market_data.get("dexscreener", {}).get("api_pairs_count", 0) > 0:
                    pair = market_data["dexscreener"].get("sample_pair")
                    if pair:
                        # Extract relevant data with safe defaults
                        volume_24h = float(pair.get("volume", {}).get("h24", 0))
                        price_change_24h = float(pair.get("priceChange", {}).get("h24", 0))
                        liquidity = float(pair.get("liquidity", {}).get("usd", 0))

                        # Determine signal strength based on volume
                        strength = SignalStrength.STRONG if volume_24h > 5000000 else \
                                 SignalStrength.MODERATE if volume_24h > 1000000 else SignalStrength.WEAK

                        signals.append(MarketSignal(
                            timestamp=datetime.datetime.now(),
                            source="dexScreener",
                            symbol=f"{pair.get('baseToken', {}).get('symbol', 'UNKNOWN')}/USD",
                            signal_type="volume_spike",
                            strength=strength,
                            confidence=0.8,
                            data={
                                "volume_24h": volume_24h,
                                "price_change_24h": price_change_24h,
                                "liquidity": liquidity,
                                "buy_sell_ratio": 1.0  # Would need trade data to calculate properly
                            }
                        ))

                # Convert GMGN data to MarketSignals
                if gmgn_scraper:
                    for token in market_data.get("gmgn_intelligence", {}).get("top_tokens", [])[:5]:
                        # Extract token info with safe defaults
                        symbol = token.get("symbol", "UNKNOWN")
                        buy_amount = float(token.get("buyAmount5m", 0))
                        sell_amount = float(token.get("sellAmount5m", 0))
                        total_amount = buy_amount + sell_amount

                        # Determine signal strength based on transaction volume
                        strength = SignalStrength.STRONG if total_amount > 100000 else \
                                 SignalStrength.MODERATE if total_amount > 50000 else SignalStrength.WEAK

                        signals.append(MarketSignal(
                            timestamp=datetime.datetime.now(),
                            source="gmgn",
                            symbol=f"{symbol}/USD",
                            signal_type="smart_money_inflow",
                            strength=strength,
                            confidence=0.85,
                            data={
                                "amount_usd": total_amount,
                                "buy_sell_ratio": buy_amount / max(sell_amount, 1),
                                "price_change_5m": float(token.get("priceChange5m", 0)),
                                "holders": int(token.get("holders", 0))
                            }
                        ))

                # Convert Jupiter data to MarketSignals
                if jupiter_scraper and market_data.get("jupiter_data", {}).get("volume_stats"):
                    # Process Jupiter volume data for volume spike signals
                    volume_stats = market_data["jupiter_data"]["volume_stats"]
                    if isinstance(volume_stats, list) and len(volume_stats) > 0:
                        # Take the most recent volume data (assuming it's sorted by time)
                        latest_volume = volume_stats[0] if isinstance(volume_stats[0], dict) else {}
                        if isinstance(latest_volume, dict):
                            volume_24h = float(latest_volume.get("volume24h", 0))

                            # Determine signal strength based on volume
                            strength = SignalStrength.STRONG if volume_24h > 10000000 else \
                                     SignalStrength.MODERATE if volume_24h > 5000000 else SignalStrength.WEAK

                            signals.append(MarketSignal(
                                timestamp=datetime.datetime.now(),
                                source="jupiter",
                                symbol="JUP/USD",  # Jupiter token or aggregate
                                signal_type="volume_spike",
                                strength=strength,
                                confidence=0.75,
                                data={
                                    "volume_24h": volume_24h,
                                    "source": "jupiter_aggregator"
                                }
                            ))

                # Convert Meteora data to MarketSignals
                if meteora_scraper and market_data.get("meteora_intelligence", {}).get("sample_pools"):
                    # Process Meteora DLMM pools for liquidity and fee yield signals
                    sample_pools = market_data["meteora_intelligence"]["sample_pools"]
                    for pool in sample_pools[:3]:  # Process top 3 pools
                        if isinstance(pool, dict):
                            tvl = float(pool.get("tvl", 0))
                            fee_yield = float(pool.get("feeYield", 0))

                            # Determine signal strength based on TVL
                            strength = SignalStrength.STRONG if tvl > 5000000 else \
                                     SignalStrength.MODERATE if tvl > 1000000 else SignalStrength.WEAK

                            signals.append(MarketSignal(
                                timestamp=datetime.datetime.now(),
                                source="meteora",
                                symbol=f"{pool.get('tokenA', {}).get('symbol', 'UNKNOWN')}/{pool.get('tokenB', {}).get('symbol', 'UNKNOWN')}",
                                signal_type="liquidity_pool",
                                strength=strength,
                                confidence=0.8,
                                data={
                                    "tvl": tvl,
                                    "fee_yield": fee_yield,
                                    "pool_address": pool.get("address", "unknown")
                                }
                            ))
        except Exception as e:
            self.logger.error(f"Error during scraping: {e}")
            # Fall back to placeholder data if scraping fails
            return self._scrape_data_sources_placeholder()
        finally:
            # Clean up scrapers
            if dex_scraper:
                await dex_scraper.close()
            if jupiter_scraper:
                await jupiter_scraper.close()
            if meteora_scraper:
                await meteora_scraper.close()
            # GMGN scraper cleans up its own pages

        return signals

    def _scrape_data_sources_placeholder(self) -> List[MarketSignal]:
        """
        Placeholder scraping method (original implementation)
        Used as fallback if scraping fails
        """
        signals = []

        # Example: DexScreener-like data (placeholder)
        if "dexScreener" in self.config["enabledDataSources"]["onChain"]:
            # This would call the actual DexScreener API or scraper
            signal = MarketSignal(
                timestamp=datetime.datetime.now(),
                source="dexScreener",
                symbol="SOL/USD",
                signal_type="volume_spike",
                strength=SignalStrength.MODERATE,
                confidence=0.75,
                data={
                    "volume_24h": 12500000,
                    "price_change_24h": 3.2,
                    "buy_sell_ratio": 1.4
                }
            )
            signals.append(signal)

        # Example: Jupiter API data (placeholder)
        if "jupiter" in self.config["enabledDataSources"]["onChain"]:
            # This would call the actual Jupiter API or scraper
            signal = MarketSignal(
                timestamp=datetime.datetime.now(),
                source="jupiter",
                symbol="JUP/USD",
                signal_type="volume_spike",
                strength=SignalStrength.MODERATE,
                confidence=0.75,
                data={
                    "volume_24h": 8500000,
                    "source": "jupiter_aggregator"
                }
            )
            signals.append(signal)

        # Example: Meteora DLMM data (placeholder)
        if "meteora" in self.config["enabledDataSources"]["onChain"]:
            # This would call the actual Meteora API or scraper
            signal = MarketSignal(
                timestamp=datetime.datetime.now(),
                source="meteora",
                symbol="SOL/USDC",
                signal_type="liquidity_pool",
                strength=SignalStrength.MODERATE,
                confidence=0.8,
                data={
                    "tvl": 3200000,
                    "fee_yield": 0.085,
                    "pool_address": "meteora_dlmm_pool_123"
                }
            )
            signals.append(signal)

        # Example: Fear & Greed Index (placeholder)
        if "fearGreedIndex" in self.config["enabledDataSources"]["macroWeb2"]:
            signal = MarketSignal(
                timestamp=datetime.datetime.now(),
                source="fearGreedIndex",
                symbol="BTC",
                signal_type="sentiment",
                strength=SignalStrength.STRONG,
                confidence=0.9,
                data={
                    "value": 65,
                    "classification": "Greed",
                    "change_24h": 5
                }
            )
            signals.append(signal)

        return signals

    def scrape_data_sources(self) -> List[MarketSignal]:
        """
        Scrape data from enabled sources
        Uses actual scrapers when available, falls back to placeholders
        """
        # Check if we have the necessary dependencies for scraping
        if not PLAYWRIGHT_AVAILABLE:
            self.logger.warning("Playwright not available, using placeholder data")
            return self._scrape_data_sources_placeholder()

        try:
            # Run the async scraping method
            return asyncio.run(self._scrape_data_sources_async())
        except Exception as e:
            self.logger.error(f"Error running async scraping: {e}")
            self.logger.info("Falling back to placeholder data")
            return self._scrape_data_sources_placeholder()

    def _run_scraping_pipeline(self, dex_scraper: Optional[DexScreenerScraper],
                              gmgn_scraper: Optional[GMGNScraper],
                              jupiter_scraper: Optional[JupiterScraper],
                              meteora_scraper: Optional[MeteoraScraper]) -> Dict[str, Any]:
        """
        Run the scraping pipeline (adapted from user's run_market_data_pipeline function)
        """
        async def _inner_pipeline():
            logger = self.logger  # Use the agent's logger

            logger.info("Starting Crypto Intelligence Data Engine...")

            # 1. Fetch DexScreener Public REST data (Async)
            solana_usdc_token = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            dex_api_task = None
            jupiter_api_task = None
            meteora_api_task = None

            if dex_scraper:
                dex_api_task = asyncio.create_task(dex_scraper.fetch_token_pairs(solana_usdc_token))
            if jupiter_scraper:
                jupiter_api_task = asyncio.create_task(jupiter_scraper.fetch_volume_data())
            if meteora_scraper:
                meteora_api_task = asyncio.create_task(meteora_scraper.fetch_dlmm_pools())

            # 2. Launch Stealth Playwright for Browser-locked Sources (if available)
            dex_browser_results = []
            gmgn_results = []

            if (dex_scraper or gmgn_scraper) and PLAYWRIGHT_AVAILABLE:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(
                        headless=True,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--no-sandbox",
                            "--disable-setuid-sandbox"
                        ]
                    )

                    # Set stealth context headers
                    context = await browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                        viewport={"width": 1440, "height": 900},
                        locale="en-US"
                    )

                    # Execute Playwright scraper tasks concurrently
                    tasks = []
                    if gmgn_scraper:
                        tasks.append(asyncio.create_task(gmgn_scraper.scrape_trending_tokens(context, chain="sol")))
                    if dex_scraper:
                        tasks.append(asyncio.create_task(dex_scraper.scrape_trending_playwright(context)))
                    # Note: Jupiter and Meteora primarily use REST APIs,
                    # but browser scraping can be added here if needed for specific data
                    if jupiter_scraper:
                        # Jupiter browser scraping (if needed for specific UI data)
                        # tasks.append(asyncio.create_task(jupiter_scraper.scrape_something_browser(context)))
                        pass
                    if meteora_scraper:
                        # Meteora browser scraping (if needed for specific UI data)
                        # tasks.append(asyncio.create_task(meteora_scraper.scrape_something_browser(context)))
                        pass

                    # Await all pipeline tasks simultaneously
                    if tasks:
                        results = await asyncio.gather(*tasks)
                        # Extract results in order
                        result_idx = 0
                        if gmgn_scraper:
                            gmgn_results = results[result_idx]
                            result_idx += 1
                        if dex_scraper:
                            dex_browser_results = results[result_idx] if result_idx < len(results) else []
                        # Extract Jupiter and Meteora browser results if tasks were added
                        # if jupiter_scraper:
                        #     jupiter_browser_results = results[result_idx] if result_idx < len(results) else []
                        #     result_idx += 1
                        # if meteora_scraper:
                        #     meteora_browser_results = results[result_idx] if result_idx < len(results) else []
                        #     result_idx += 1

                    await browser.close()
            elif dex_scraper or gmgn_scraper:
                # Playwright is not available but we have Playwright-dependent scrapers
                logger.warning("Playwright not available but DexScreener or GMGN scraper is enabled. Skipping Playwright-based scraping.")

            # Clean up scrapers
            if dex_scraper:
                await dex_scraper.close()
            if jupiter_scraper:
                await jupiter_scraper.close()
            if meteora_scraper:
                await meteora_scraper.close()

            # Wait for API tasks
            dex_api_results = []
            jupiter_api_results = []
            meteora_api_results = []

            if dex_api_task:
                dex_api_results = await dex_api_task
            if jupiter_api_task:
                jupiter_api_results = await jupiter_api_task
            if meteora_api_task:
                meteora_api_results = await meteora_api_task

            # Compile Consolidated Payload
            consolidated_market_data = {
                "dexscreener": {
                    "api_pairs_count": len(dex_api_results),
                    "sample_pair": dex_api_results[0] if dex_api_results else None,
                    "browser_trending": dex_browser_results[:5]
                },
                "gmgn_intelligence": {
                    "trending_count": len(gmgn_results),
                    "top_tokens": gmgn_results[:5]
                },
                "jupiter_data": {
                    "volume_stats": jupiter_api_results if isinstance(jupiter_api_results, list) else [],
                    "sample_volume": jupiter_api_results[0] if isinstance(jupiter_api_results, list) and len(jupiter_api_results) > 0 else None
                },
                "meteora_intelligence": {
                    "pools_count": len(meteora_api_results) if isinstance(meteora_api_results, list) else 0,
                    "sample_pools": meteora_api_results[:5] if isinstance(meteora_api_results, list) else []
                }
            }

            return consolidated_market_data

        return _inner_pipeline()

    def correlate_factors(self, signals: List[MarketSignal]) -> Dict[str, Any]:
        """
        Layer 1: Multi-Factor Correlation Model
        Analyze correlations between different data points
        """
        correlations = {
            "macro_to_crypto": {},
            "on_chain_flow": {},
            "smart_money_divergence": {}
        }

        # Placeholder correlation analysis
        # In reality, this would use statistical methods (Pearson, Spearman, etc.)
        # to find relationships between different data streams

        for signal in signals:
            if signal.source == "dexScreener" and signal.signal_type == "volume_spike":
                correlations["on_chain_flow"]["volume_signal"] = signal.confidence
            elif signal.source == "fearGreedIndex" and signal.signal_type == "sentiment":
                correlations["macro_to_crypto"]["sentiment_signal"] = (signal.data["value"] - 50) / 50  # Normalize to -1 to 1

        return correlations

    def assess_sector_impact(self, signals: List[MarketSignal], correlations: Dict[str, Any]) -> Dict[str, Any]:
        """
        Layer 2: Sector Impact Assessment
        Categorize affected industries/narratives
        """
        sectors = {
            "defi_liquidity": {"impact": 0.0, "trend": "neutral"},
            "layer1_layer2": {"impact": 0.0, "trend": "neutral"},
            "memecoins_high_beta": {"impact": 0.0, "trend": "neutral"},
            "ai_depin": {"impact": 0.0, "trend": "neutral"}
        }

        # Placeholder sector impact assessment
        # Would analyze which sectors are most affected by the signals

        for signal in signals:
            if signal.source in ["dexScreener", "jupiter", "meteora"]:
                # Likely affects DeFi & liquidity protocols
                sectors["defi_liquidity"]["impact"] += signal.confidence * 0.3
                if signal.data.get("price_change_24h", 0) > 0:
                    sectors["defi_liquidity"]["trend"] = "bullish"
                else:
                    sectors["defi_liquidity"]["trend"] = "bearish"

        return sectors

    def generate_probabilistic_forecast(self,
                                    signals: List[MarketSignal],
                                    correlations: Dict[str, Any],
                                    sector_impact: Dict[str, Any]) -> List[ProbabilisticForecast]:
        """
        Layer 3: Probabilistic Forecasting Engine
        Generate forecasts with confidence intervals
        """
        forecasts = []

        # Generate forecast for each focus asset
        for asset in self.config["focusAssetsChains"]:
            # Placeholder forecast generation
            # In reality, this would use time series models, machine learning, etc.

            # Simple example based on aggregated signals
            bullish_score = 0.0
            bearish_score = 0.0

            for signal in signals:
                if asset in signal.symbol or signal.symbol in asset:
                    if signal.data.get("price_change_24h", 0) > 0:
                        bullish_score += signal.confidence
                    else:
                        bearish_score += signal.confidence

            # Normalize scores
            total_score = bullish_score + bearish_score
            if total_score > 0:
                bullish_prob = bullish_score / total_score
                bearish_prob = bearish_score / total_score
            else:
                bullish_prob = 0.33
                bearish_prob = 0.33

            neutral_prob = 1.0 - (bullish_prob + bearish_prob)

            # Ensure probabilities sum to 1
            total = bullish_prob + bearish_prob + neutral_prob
            bullish_prob /= total
            bearish_prob /= total
            neutral_prob /= total

            # Generate scenario targets (placeholder - would be based on technical analysis)
            current_price = 100.0  # Would get actual price from data
            forecast = ProbabilisticForecast(
                timestamp=datetime.datetime.now(),
                symbol=asset,
                timeframe="24h",
                directional_bias={
                    "bullish": round(bullish_prob, 2),
                    "bearish": round(bearish_prob, 2),
                    "neutral": round(neutral_prob, 2)
                },
                scenarios={
                    "bull": {
                        "target": round(current_price * 1.08, 2),
                        "probability": round(bullish_prob, 2)
                    },
                    "base": {
                        "target": round(current_price * 1.02, 2),
                        "probability": round(neutral_prob, 2)
                    },
                    "bear": {
                        "target": round(current_price * 0.95, 2),
                        "probability": round(bearish_prob, 2)
                    }
                },
                invalidation_levels=[
                    round(current_price * 0.92, 2),  # Below this invalidates bull thesis
                    round(current_price * 1.10, 2)   # Above this invalidates bear thesis
                ],
                confidence_interval=0.75  # Would be calculated based on model confidence
            )
            forecasts.append(forecast)

        return forecasts

    def generate_morning_briefing(self,
                                signals: List[MarketSignal],
                                forecasts: List[ProbabilisticForecast]) -> Dict[str, Any]:
        """
        Generate the morning briefing report
        """
        briefing = {
            "timestamp": datetime.datetime.now().isoformat(),
            "macro_backdrop": {
                "fed_news": ["Placeholder: No major Fed announcements"],
                "tradfi_performance": {"sp500": "+0.5%", "dxy": "-0.2%"},
                "summary": "TradFi markets showing moderate gains"
            },
            "on_chain_health": {
                "liquidations": "$2.1M in last 24h",
                "jupiter_volume": "$145M",
                "dex_movements": "Net inflow to SOL ecosystem",
                "summary": "On-chain activity moderate with selective accumulation"
            },
            "sentiment_correlation_score": {
                "score": 65,  # 0-100 scale
                "classification": "Greed",
                "primary_drivers": [
                    "Positive BTC momentum",
                    "Increasing DeFi TVL",
                    "Reduced exchange reserves"
                ]
            },
            "sector_impact_matrix": {
                "winners": ["DeFi Infrastructure", "AI Tokens"],
                "losers": ["Memecoins", "Overleveraged L2s"],
                "emerging_trends": ["Real World Assets (RWA)", "Modular Blockchains"]
            },
            "key_levels_to_watch": {
                "BTC": {"level": 67500, "significance": "Psychological resistance"},
                "ETH": {"level": 3450, "significance": "200-day MA"},
                "watchlist": [
                    {"symbol": "SOL", "level": 180, "reason": "Breakout level"},
                    {"symbol": "AVAX", "level": 38, "reason": "TVL support"},
                    {"symbol": "MATIC", "level": 0.85, "reason": "Polygon 2.0 catalyst"}
                ]
            },
            "forecasts": [
                {
                    "symbol": f.symbol,
                    "timeframe": f.timeframe,
                    "directional_bias": f.directional_bias,
                    "scenarios": f.scenarios
                } for f in forecasts
            ]
        }

        return briefing

    def check_urgent_alerts(self, signals: List[MarketSignal]) -> List[Dict[str, Any]]:
        """
        Check for urgent market alert conditions
        """
        alerts = []

        for signal in signals:
            # Volume Anomalies: >3x spike in volume
            if (signal.source == "dexScreener" and
                signal.signal_type == "volume_spike" and
                signal.data.get("volume_24h", 0) >
                signal.data.get("average_volume_24h", 1) * 3):
                alerts.append({
                    "type": "volume_anomaly",
                    "symbol": signal.symbol,
                    "message": f"Volume spike detected: {signal.data['volume_24h']:,} (>{signal.data.get('average_volume_24h', 0)*3:.0f}x average)",
                    "severity": "high",
                    "timestamp": signal.timestamp.isoformat()
                })

            # Smart Money Movements (placeholder)
            if signal.source == "gmgn" and signal.signal_type == "smart_money_inflow":
                if signal.data.get("amount_usd", 0) > self.config["notificationThresholds"]["smartMoneyInflows"]["amountUSD"]:
                    alerts.append({
                        "type": "smart_money_movement",
                        "symbol": signal.symbol,
                        "message": f"Large smart money inflow: ${signal.data['amount_usd']:,.0f}",
                        "severity": "medium",
                        "timestamp": signal.timestamp.isoformat()
                    })

        return alerts

    def run_cycle(self):
        """Execute one full cycle of the agent workflow"""
        self.logger.info("Starting CryptoPulse AI cycle...")

        # 1. Init Check (already done in initialize)

        # 2. Scrape & Ingest
        self.logger.info("Scraping data sources...")
        signals = self.scrape_data_sources()
        self.logger.info(f"Collected {len(signals)} signals from data sources")

        # 3. Process & Reason
        self.logger.info("Processing data and generating forecasts...")
        correlations = self.correlate_factors(signals)
        sector_impact = self.assess_sector_impact(signals, correlations)
        forecasts = self.generate_probabilistic_forecast(signals, correlations, sector_impact)

        # 4. Format & Deliver
        self.logger.info("Generating reports...")

        # Morning briefing (if it's morning time)
        now = datetime.datetime.now()
        morning_time = datetime.datetime.strptime(
            self.config["deliveryPreferences"]["morningDigestTime"], "%H:%M"
        ).time()

        if now.time().hour == morning_time.hour and now.time().minute == morning_time.minute:
            briefing = self.generate_morning_briefing(signals, forecasts)
            self.deliver_briefing(briefing)

        # Urgent alerts
        alerts = self.check_urgent_alerts(signals)
        if alerts:
            self.deliver_alerts(alerts)

        # Store signals for history
        self.active_signals.extend(signals)
        # Keep only last 1000 signals to prevent memory issues
        if len(self.active_signals) > 1000:
            self.active_signals = self.active_signals[-1000:]

        self.logger.info("Cycle completed successfully")

    def deliver_briefing(self, briefing: Dict[str, Any]):
        """Deliver the morning briefing"""
        self.logger.info("=== MORNING BRIEFING ===")
        self.logger.info(f"Sentiment Score: {briefing['sentiment_correlation_score']['score']}/100 ({briefing['sentiment_correlation_score']['classification']})")
        self.logger.info(f"Market Bias: Bullish {briefing['forecasts'][0]['directional_bias']['bullish']*100:.0f}% | "
                        f"Bearish {briefing['forecasts'][0]['directional_bias']['bearish']*100:.0f}% | "
                        f"Neutral {briefing['forecasts'][0]['directional_bias']['neutral']*100:.0f}%")
        self.logger.info("========================")

        # In a real implementation, this would send via email, telegram, desktop notification, etc.

    def deliver_alerts(self, alerts: List[Dict[str, Any]]):
        """Deliver urgent alerts"""
        for alert in alerts:
            self.logger.warning(f"URGENT ALERT: {alert['message']}")
            # In a real implementation, this would trigger immediate notifications

    def run_continuous(self, interval_seconds: int = 300):
        """Run the agent continuously with specified interval"""
        self.logger.info(f"Starting continuous monitoring (interval: {interval_seconds}s)")

        try:
            while True:
                self.run_cycle()
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            self.logger.info("Shutting down CryptoPulse AI...")
        except Exception as e:
            self.logger.error(f"Error in continuous run: {e}")
            raise

def main():
    """Main entry point"""
    print("🚀 Initializing CryptoPulse AI...")
    agent = CryptoPulseAgent()

    if not agent.initialize():
        print("❌ Failed to initialize agent. Please check EULA acknowledgment and configuration.")
        return

    print("✅ CryptoPulse AI initialized successfully!")
    print("\nChoose an option:")
    print("1. Run single analysis cycle")
    print("2. Start continuous monitoring (5-minute intervals)")
    print("3. View current configuration")
    print("4. Acknowledge EULA (if not done)")

    choice = input("\nEnter choice (1-4): ").strip()

    if choice == "1":
        agent.run_cycle()
        print("✅ Analysis cycle completed. Check logs for details.")
    elif choice == "2":
        print("🔄 Starting continuous monitoring... Press Ctrl+C to stop")
        agent.run_continuous(300)  # 5 minutes
    elif choice == "3":
        print(f"📋 Current Configuration:")
        print(json.dumps(agent.config, indent=2))
    elif choice == "4":
        print("📝 To acknowledge EULA, please edit the EULA_ACKNOWLEDGMENT.md file")
        print("   and add the phrase: 'I ACKNOWLEDGE AND ACCEPT THE EULA ABOVE'")
        print("   Then restart the agent.")
    else:
        print("❌ Invalid choice")

if __name__ == "__main__":
    main()