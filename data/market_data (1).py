"""
market_data.py — Downloads and caches market data from Yahoo Finance.

FILE LOCATION: ~/Desktop/srx-platform/data/market_data.py

FIXES IN THIS VERSION:
    1. Column normalization — yfinance 0.2.31+ returns lowercase columns
       ('close' instead of 'Close') for some tickers. We now normalize
       ALL column names to Title Case immediately after download.
    2. Period-aware cache keys — cache files now include the period
       (e.g., SPY_2y.csv vs SPY_1y.csv) so different lookback windows
       don't collide.
    3. Reduced cache TTL — from 24h to 4h. Market data that's a day old
       is stale for a risk dashboard.
    4. Retry logic — one automatic retry with a 2-second delay on failure.
    5. Graceful degradation — if a ticker fails, the rest still proceed.
       get_market_prices() now warns instead of silently dropping.
"""

import os
import sys
import time
import pandas as pd
import numpy as np

try:
    import yfinance as yf
except ImportError:
    raise ImportError(
        "\n\nERROR: 'yfinance' is not installed.\n"
        "Fix: pip install yfinance\n"
    )

# =============================================================================
# CONFIGURATION
# =============================================================================

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")

# Cache TTL: 4 hours (14400 seconds). Was 24h — too stale for a risk dashboard.
CACHE_MAX_AGE_SECONDS = 14400

SRX_CORE_TICKERS = ["SPY", "TLT", "HYG", "GLD", "UUP", "BTC-USD"]

DEFAULT_TICKERS = [
    "SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "HYG", "LQD", "GLD", "VNQ",
]

DEFAULT_PERIOD = "2y"


# =============================================================================
# HELPERS
# =============================================================================

def _standardize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _get_cache_path(ticker: str, period: str = DEFAULT_PERIOD) -> str:
    """Cache path includes the period so 2y and 1y don't collide."""
    safe_name = ticker.replace("/", "_")
    return os.path.join(CACHE_DIR, f"{safe_name}_{period}.csv")


def _is_cache_fresh(filepath: str) -> bool:
    if not os.path.exists(filepath):
        return False
    file_age_seconds = time.time() - os.path.getmtime(filepath)
    return file_age_seconds < CACHE_MAX_AGE_SECONDS


def _safe_to_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """Force index to DatetimeIndex and strip timezone."""
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize column names to Title Case.

    yfinance >= 0.2.31 returns lowercase columns for some tickers:
        'close', 'open', 'high', 'low', 'volume'
    Older versions and some ticker types return Title Case:
        'Close', 'Open', 'High', 'Low', 'Volume'

    This function ensures we always get Title Case, regardless of
    yfinance version or ticker type.
    """
    rename_map = {}
    for col in df.columns:
        title = col.strip().title()
        # Handle 'Adj Close' / 'adj close' / 'Adj close' variants
        if title.lower().replace(" ", "") in ("adjclose", "adjustedclose"):
            title = "Adj Close"
        rename_map[col] = title
    df = df.rename(columns=rename_map)
    return df


# =============================================================================
# DOWNLOAD
# =============================================================================

def download_single_ticker(
    ticker: str,
    period: str = DEFAULT_PERIOD,
    _retry: bool = True,
) -> pd.DataFrame:
    """
    Download price + volume data for one ticker. Returns empty DataFrame on failure.

    Features:
        - Normalizes column names (fixes yfinance lowercase bug)
        - Period-aware caching (2y and 1y don't collide)
        - One automatic retry on failure with 2s delay
    """
    ticker = _standardize_ticker(ticker)
    cache_path = _get_cache_path(ticker, period)

    # ---- Try cache ----
    if _is_cache_fresh(cache_path):
        try:
            cached = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            if not cached.empty:
                cached = _safe_to_datetime_index(cached)
                cached = _normalize_columns(cached)
                print(f"  [CACHE]  {ticker}: {len(cached)} rows (period={period})")
                return cached
        except Exception:
            print(f"  [WARN]   {ticker}: cache corrupted, re-downloading")

    # ---- Download from Yahoo Finance ----
    try:
        print(f"  [FETCH]  {ticker}: downloading from Yahoo Finance (period={period})...")
        stock = yf.Ticker(ticker)
        data = stock.history(period=period)

        if data is None or data.empty:
            if _retry:
                print(f"  [RETRY]  {ticker}: empty response, retrying in 2s...")
                time.sleep(2)
                return download_single_ticker(ticker, period, _retry=False)
            print(
                f"\n"
                f"  WARNING: No data for '{ticker}'.\n"
                f"  Check the symbol at https://finance.yahoo.com\n"
            )
            return pd.DataFrame()

        # Normalize column names IMMEDIATELY (the core fix for Issue 2)
        data = _normalize_columns(data)

        # Keep only the columns we need
        columns_to_keep = ["Open", "High", "Low", "Close", "Volume"]
        available = [c for c in columns_to_keep if c in data.columns]

        if "Close" not in available:
            # Even after normalization, no Close column — truly broken data
            print(f"  WARNING: {ticker} has no 'Close' column even after normalization.")
            print(f"           Available columns: {list(data.columns)}")
            return pd.DataFrame()

        data = data[available]
        data = _safe_to_datetime_index(data)

        # Save to cache (period-aware filename)
        os.makedirs(CACHE_DIR, exist_ok=True)
        data.to_csv(cache_path)
        print(f"  [FETCH]  {ticker}: {len(data)} rows saved (period={period})")
        return data

    except Exception as error:
        if _retry:
            print(f"  [RETRY]  {ticker}: error ({error}), retrying in 2s...")
            time.sleep(2)
            return download_single_ticker(ticker, period, _retry=False)
        print(
            f"\n"
            f"  ERROR downloading {ticker}: {error}\n"
            f"  Possible fixes:\n"
            f"    1. Check internet connection\n"
            f"    2. Verify '{ticker}' is a valid symbol\n"
            f"    3. Run: pip install --upgrade yfinance\n"
        )
        return pd.DataFrame()


def download_multiple_tickers(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> dict:
    """Download data for multiple tickers. Returns dict of {ticker: DataFrame}."""
    if tickers is None:
        tickers = DEFAULT_TICKERS
    tickers = [_standardize_ticker(t) for t in tickers]

    print(f"\nDownloading {len(tickers)} tickers: {tickers}")
    print("-" * 60)

    results = {}
    failed = []
    for ticker in tickers:
        data = download_single_ticker(ticker, period)
        if not data.empty:
            results[ticker] = data
        else:
            failed.append(ticker)

    print("-" * 60)
    print(f"Done. {len(results)} succeeded, {len(failed)} failed.")
    if failed:
        print(f"  Failed tickers: {failed}")
    print()

    if not results:
        print(
            "WARNING: No data downloaded for any ticker.\n"
            "Check your internet connection.\n"
        )

    return results


# =============================================================================
# MAIN PUBLIC FUNCTIONS
# =============================================================================

def get_market_prices(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> pd.DataFrame:
    """
    Get closing prices for tickers. Inner join across all assets.

    The inner join keeps only dates where EVERY ticker has data,
    which removes crypto weekends, stock holidays, etc.
    """
    try:
        if tickers is None:
            tickers = SRX_CORE_TICKERS
        tickers = [_standardize_ticker(t) for t in tickers]

        all_data = download_multiple_tickers(tickers, period)
        if not all_data:
            print("ERROR: No data downloaded.")
            return pd.DataFrame()

        # Build close price table — tolerant of missing tickers
        close_dict = {}
        skipped = []
        for ticker, df in all_data.items():
            if "Close" in df.columns:
                close_dict[ticker] = df["Close"]
            else:
                skipped.append(ticker)
                print(f"  WARNING: {ticker} has no 'Close' column after normalization.")
                print(f"           Columns present: {list(df.columns)}")

        if skipped:
            print(f"  Skipped tickers (no Close data): {skipped}")

        if not close_dict:
            print("ERROR: None of the downloaded data has 'Close' prices.")
            return pd.DataFrame()

        close_prices = pd.DataFrame(close_dict)
        rows_before = len(close_prices)
        close_prices = close_prices.dropna()
        rows_after = len(close_prices)

        if rows_before - rows_after > 0:
            print(
                f"  [JOIN]   Dropped {rows_before - rows_after} rows "
                f"(crypto weekends, holidays, gaps)."
            )

        if close_prices.empty:
            print("ERROR: After inner join, no overlapping dates remain.")
            return pd.DataFrame()

        close_prices = close_prices.sort_index()
        start = close_prices.index[0]
        end = close_prices.index[-1]
        start_str = start.strftime('%Y-%m-%d') if hasattr(start, 'strftime') else str(start)[:10]
        end_str = end.strftime('%Y-%m-%d') if hasattr(end, 'strftime') else str(end)[:10]

        print(
            f"  [RESULT] {len(close_prices)} rows x {len(close_prices.columns)} tickers "
            f"({start_str} to {end_str})"
        )
        return close_prices

    except Exception as error:
        print(f"\nERROR in get_market_prices(): {error}")
        return pd.DataFrame()


def get_market_returns(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> pd.DataFrame:
    """Get daily returns (decimal fraction). Uses get_market_prices() internally."""
    try:
        close_prices = get_market_prices(tickers, period)
        if close_prices.empty:
            return pd.DataFrame()

        returns = close_prices.pct_change().dropna()

        if returns.isin([np.inf, -np.inf]).any().any():
            inf_count = returns.isin([np.inf, -np.inf]).sum().sum()
            print(f"  WARNING: {inf_count} infinite returns replaced with 0.")
            returns = returns.replace([np.inf, -np.inf], 0.0)

        return returns

    except Exception as error:
        print(f"\nERROR in get_market_returns(): {error}")
        return pd.DataFrame()


def get_market_volume(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> pd.DataFrame:
    """Get daily volume. Inner join across all assets."""
    try:
        if tickers is None:
            tickers = SRX_CORE_TICKERS
        tickers = [_standardize_ticker(t) for t in tickers]

        all_data = download_multiple_tickers(tickers, period)
        if not all_data:
            return pd.DataFrame()

        volume_dict = {}
        for ticker, df in all_data.items():
            if "Volume" in df.columns:
                volume_dict[ticker] = df["Volume"]
            else:
                print(f"  WARNING: {ticker} has no 'Volume' column.")

        if not volume_dict:
            return pd.DataFrame()

        volume_df = pd.DataFrame(volume_dict).dropna().sort_index()
        return volume_df

    except Exception as error:
        print(f"\nERROR in get_market_volume(): {error}")
        return pd.DataFrame()


# =============================================================================
# LEGACY WRAPPERS
# =============================================================================

def get_close_prices(tickers: list = None, period: str = DEFAULT_PERIOD) -> pd.DataFrame:
    if tickers is None:
        tickers = DEFAULT_TICKERS
    return get_market_prices(tickers, period)


def get_returns(tickers: list = None, period: str = DEFAULT_PERIOD) -> pd.DataFrame:
    if tickers is None:
        tickers = DEFAULT_TICKERS
    return get_market_returns(tickers, period)


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("SRX PLATFORM — Market Data Module Test")
    print("=" * 70)

    all_passed = True

    print("\n--- TEST 1: get_market_prices() ---\n")
    prices = get_market_prices()
    if not prices.empty:
        print(f"\nShape: {prices.shape[0]} rows x {prices.shape[1]} columns")
        print(f"Columns: {list(prices.columns)}")
        print(f"\nFirst 3 rows:\n{prices.head(3).to_string()}")
        print(f"\nLast 3 rows:\n{prices.tail(3).to_string()}")
    else:
        print("FAILED: No price data."); all_passed = False

    print("\n--- TEST 2: get_market_returns() ---\n")
    returns = get_market_returns()
    if not returns.empty:
        print(f"Shape: {returns.shape[0]} rows x {returns.shape[1]} columns")
        print(f"\nStats:\n{returns.describe().round(6).to_string()}")
    else:
        print("FAILED: No return data."); all_passed = False

    print("\n--- TEST 3: get_market_volume() ---\n")
    volume = get_market_volume()
    if not volume.empty:
        print(f"Shape: {volume.shape[0]} rows x {volume.shape[1]} columns")
    else:
        print("FAILED: No volume data."); all_passed = False

    # TEST 4: Verify column normalization works
    print("\n--- TEST 4: Column normalization ---\n")
    test_df = pd.DataFrame({"close": [1, 2], "open": [3, 4], "volume": [5, 6]})
    normed = _normalize_columns(test_df)
    expected = ["Close", "Open", "Volume"]
    actual = list(normed.columns)
    if actual == expected:
        print(f"  ✓ Normalized {list(test_df.columns)} → {actual}")
    else:
        print(f"  ✗ Expected {expected}, got {actual}"); all_passed = False

    print("\n" + "=" * 70)
    print("ALL PASSED" if all_passed else "SOME TESTS FAILED")
    print("=" * 70)
