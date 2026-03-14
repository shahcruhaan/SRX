"""
market_data.py — Downloads and caches market data from Yahoo Finance.

FILE LOCATION: ~/Desktop/srx-platform/data/market_data.py

KEY DESIGN DECISION:
    This module uses yf.download() (batch endpoint) instead of
    yf.Ticker().history() (single-ticker endpoint).

    Why: Yahoo Finance aggressively blocks cloud server IPs when they
    receive sequential single-ticker API calls. The error manifests as:
        "Expecting value: line 1 column 1 (char 0)"
        "$SPY: possibly delisted; no price data found"
    This is not a real delisting — it's Yahoo returning an HTML bot
    challenge page instead of JSON data.

    yf.download() uses a different Yahoo endpoint (v8/finance/chart)
    that handles batch requests in a single HTTP call and is far more
    tolerant of cloud IPs (Streamlit Cloud, AWS, GCP, etc.).

PUBLIC API (unchanged — all callers work without modification):
    get_market_prices(tickers, period)  → DataFrame of closing prices
    get_market_returns(tickers, period) → DataFrame of daily returns
    get_market_volume(tickers, period)  → DataFrame of daily volume
    get_close_prices(tickers, period)   → Legacy wrapper for get_market_prices
    get_returns(tickers, period)        → Legacy wrapper for get_market_returns
    download_single_ticker(ticker, period) → Single ticker DataFrame
    download_multiple_tickers(tickers, period) → Dict of DataFrames
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
CACHE_MAX_AGE_SECONDS = 14400  # 4 hours

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
    safe_name = ticker.replace("/", "_")
    return os.path.join(CACHE_DIR, f"{safe_name}_{period}.csv")


def _is_cache_fresh(filepath: str) -> bool:
    if not os.path.exists(filepath):
        return False
    return (time.time() - os.path.getmtime(filepath)) < CACHE_MAX_AGE_SECONDS


def _safe_to_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize column names to Title Case.
    Handles yfinance 0.2.31+ lowercase columns and MultiIndex from batch downloads.
    """
    rename_map = {}
    for col in df.columns:
        c = col.strip() if isinstance(col, str) else str(col)
        title = c.title()
        if title.lower().replace(" ", "") in ("adjclose", "adjustedclose"):
            title = "Adj Close"
        rename_map[col] = title
    return df.rename(columns=rename_map)


def _save_to_cache(ticker: str, period: str, df: pd.DataFrame):
    """Save a single-ticker DataFrame to the CSV cache."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = _get_cache_path(ticker, period)
        df.to_csv(path)
    except Exception as e:
        print(f"  [WARN]   Could not cache {ticker}: {e}")


def _load_from_cache(ticker: str, period: str) -> pd.DataFrame:
    """Load a single-ticker DataFrame from cache. Returns empty if stale/missing."""
    path = _get_cache_path(ticker, period)
    if not _is_cache_fresh(path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            return pd.DataFrame()
        df = _safe_to_datetime_index(df)
        df = _normalize_columns(df)
        return df
    except Exception:
        return pd.DataFrame()


# =============================================================================
# BATCH DOWNLOAD — the core fix for Streamlit Cloud
# =============================================================================

def _batch_download(tickers: list, period: str = DEFAULT_PERIOD) -> dict:
    """
    Download multiple tickers in ONE HTTP call using yf.download().

    This is the fix for the Yahoo bot-detection issue. Instead of making
    N sequential yf.Ticker().history() calls (each hitting Yahoo's
    single-ticker endpoint), this makes ONE batch request that Yahoo's
    infrastructure handles more gracefully.

    Returns:
        dict of {ticker: DataFrame} with columns [Open, High, Low, Close, Volume]
    """
    tickers = [_standardize_ticker(t) for t in tickers]

    # Check which tickers have fresh cache
    cached = {}
    to_download = []
    for t in tickers:
        df = _load_from_cache(t, period)
        if not df.empty:
            cached[t] = df
            print(f"  [CACHE]  {t}: {len(df)} rows")
        else:
            to_download.append(t)

    if not to_download:
        print("  All tickers served from cache.")
        return cached

    # Batch download the uncached tickers
    print(f"  [BATCH]  Downloading {len(to_download)} tickers: {to_download}")

    results = dict(cached)  # Start with cached data

    for attempt in range(1, 4):  # Up to 3 attempts
        if not to_download:
            break

        try:
            raw = yf.download(
                tickers=to_download,
                period=period,
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )

            if raw is None or raw.empty:
                print(f"  [WARN]   Attempt {attempt}: empty response from Yahoo.")
                if attempt < 3:
                    wait = attempt * 3
                    print(f"           Retrying in {wait}s...")
                    time.sleep(wait)
                continue

            # Parse the batch response.
            # yf.download with group_by="ticker" returns:
            #   - MultiIndex columns (ticker, field) when multiple tickers
            #   - Simple columns (field) when only one ticker
            still_failed = []

            if len(to_download) == 1:
                # Single ticker — columns are just field names
                ticker = to_download[0]
                df = raw.copy()
                df = _normalize_columns(df)
                df = _safe_to_datetime_index(df)

                # Keep only needed columns
                keep = [c for c in ["Open", "High", "Low", "Close", "Volume"]
                        if c in df.columns]

                if "Close" in keep and len(df.dropna(subset=["Close"])) > 0:
                    df = df[keep].dropna(subset=["Close"])
                    results[ticker] = df
                    _save_to_cache(ticker, period, df)
                    print(f"  [OK]     {ticker}: {len(df)} rows")
                else:
                    still_failed.append(ticker)
                    print(f"  [FAIL]   {ticker}: no Close data")
            else:
                # Multiple tickers — MultiIndex columns
                for ticker in to_download:
                    try:
                        if ticker in raw.columns.get_level_values(0):
                            df = raw[ticker].copy()
                        else:
                            # Try case-insensitive match
                            matches = [t for t in raw.columns.get_level_values(0).unique()
                                       if t.upper() == ticker.upper()]
                            if matches:
                                df = raw[matches[0]].copy()
                            else:
                                still_failed.append(ticker)
                                print(f"  [FAIL]   {ticker}: not in batch response")
                                continue

                        df = _normalize_columns(df)
                        df = _safe_to_datetime_index(df)

                        keep = [c for c in ["Open", "High", "Low", "Close", "Volume"]
                                if c in df.columns]

                        if "Close" in keep and len(df.dropna(subset=["Close"])) > 0:
                            df = df[keep].dropna(subset=["Close"])
                            results[ticker] = df
                            _save_to_cache(ticker, period, df)
                            print(f"  [OK]     {ticker}: {len(df)} rows")
                        else:
                            still_failed.append(ticker)
                            print(f"  [FAIL]   {ticker}: no Close data in batch")

                    except Exception as e:
                        still_failed.append(ticker)
                        print(f"  [FAIL]   {ticker}: {e}")

            to_download = still_failed
            if to_download and attempt < 3:
                wait = attempt * 3
                print(f"  [RETRY]  {len(to_download)} failed, retrying in {wait}s...")
                time.sleep(wait)

        except Exception as e:
            print(f"  [ERROR]  Batch download attempt {attempt} failed: {e}")
            if attempt < 3:
                wait = attempt * 3
                print(f"           Retrying in {wait}s...")
                time.sleep(wait)

    if to_download:
        print(f"  [FAIL]   Could not download after 3 attempts: {to_download}")

    return results


# =============================================================================
# SINGLE-TICKER DOWNLOAD (backward compatible, now uses batch internally)
# =============================================================================

def download_single_ticker(
    ticker: str,
    period: str = DEFAULT_PERIOD,
    _retry: bool = True,
) -> pd.DataFrame:
    """
    Download data for one ticker. Returns empty DataFrame on failure.
    Now uses yf.download() internally for cloud compatibility.
    """
    ticker = _standardize_ticker(ticker)

    # Try cache first
    cached = _load_from_cache(ticker, period)
    if not cached.empty:
        print(f"  [CACHE]  {ticker}: {len(cached)} rows")
        return cached

    # Use batch download for a single ticker
    result = _batch_download([ticker], period)
    return result.get(ticker, pd.DataFrame())


def download_multiple_tickers(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> dict:
    """Download data for multiple tickers. Returns dict of {ticker: DataFrame}."""
    if tickers is None:
        tickers = DEFAULT_TICKERS
    tickers = [_standardize_ticker(t) for t in tickers]

    print(f"\n  Downloading {len(tickers)} tickers: {tickers}")
    print("  " + "-" * 58)

    results = _batch_download(tickers, period)

    succeeded = len(results)
    failed = [t for t in tickers if t not in results]
    print("  " + "-" * 58)
    print(f"  Done. {succeeded} succeeded, {len(failed)} failed.")
    if failed:
        print(f"  Failed: {failed}")

    return results


# =============================================================================
# PUBLIC FUNCTIONS — unchanged API
# =============================================================================

def get_market_prices(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> pd.DataFrame:
    """
    Get closing prices. Inner join across all assets.
    Removes crypto weekends, stock holidays, and any date with gaps.
    """
    try:
        if tickers is None:
            tickers = SRX_CORE_TICKERS
        tickers = [_standardize_ticker(t) for t in tickers]

        all_data = download_multiple_tickers(tickers, period)
        if not all_data:
            print("  ERROR: No data downloaded.")
            return pd.DataFrame()

        close_dict = {}
        for ticker, df in all_data.items():
            if "Close" in df.columns:
                close_dict[ticker] = df["Close"]
            else:
                print(f"  WARN: {ticker} missing 'Close'. Cols: {list(df.columns)}")

        if not close_dict:
            print("  ERROR: No Close data available.")
            return pd.DataFrame()

        close_prices = pd.DataFrame(close_dict)
        rows_before = len(close_prices)
        close_prices = close_prices.dropna()
        rows_after = len(close_prices)

        if rows_before - rows_after > 0:
            print(f"  [JOIN]   Dropped {rows_before - rows_after} rows (gaps/holidays).")

        if close_prices.empty:
            print("  ERROR: No overlapping dates after inner join.")
            return pd.DataFrame()

        close_prices = close_prices.sort_index()
        close_prices = _safe_to_datetime_index(close_prices)

        start = close_prices.index[0]
        end = close_prices.index[-1]
        s = start.strftime('%Y-%m-%d') if hasattr(start, 'strftime') else str(start)[:10]
        e = end.strftime('%Y-%m-%d') if hasattr(end, 'strftime') else str(end)[:10]
        print(f"  [RESULT] {len(close_prices)} rows x {len(close_prices.columns)} tickers ({s} to {e})")

        return close_prices

    except Exception as error:
        print(f"\n  ERROR in get_market_prices(): {error}")
        return pd.DataFrame()


def get_market_returns(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> pd.DataFrame:
    """Daily returns (decimal fraction). Uses get_market_prices() internally."""
    try:
        prices = get_market_prices(tickers, period)
        if prices.empty:
            return pd.DataFrame()

        returns = prices.pct_change().dropna()

        if returns.isin([np.inf, -np.inf]).any().any():
            n = returns.isin([np.inf, -np.inf]).sum().sum()
            print(f"  WARN: {n} infinite returns replaced with 0.")
            returns = returns.replace([np.inf, -np.inf], 0.0)

        return returns

    except Exception as error:
        print(f"\n  ERROR in get_market_returns(): {error}")
        return pd.DataFrame()


def get_market_volume(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> pd.DataFrame:
    """Daily volume. Inner join across all assets."""
    try:
        if tickers is None:
            tickers = SRX_CORE_TICKERS
        tickers = [_standardize_ticker(t) for t in tickers]

        all_data = download_multiple_tickers(tickers, period)
        if not all_data:
            return pd.DataFrame()

        vol_dict = {}
        for ticker, df in all_data.items():
            if "Volume" in df.columns:
                vol_dict[ticker] = df["Volume"]

        if not vol_dict:
            return pd.DataFrame()

        return pd.DataFrame(vol_dict).dropna().sort_index()

    except Exception as error:
        print(f"\n  ERROR in get_market_volume(): {error}")
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
    print("SRX — Market Data Test")
    print("=" * 70)

    ok = True

    print("\n--- TEST 1: get_market_prices() ---")
    p = get_market_prices()
    if not p.empty:
        print(f"  Shape: {p.shape}, Cols: {list(p.columns)}")
        print(f"  Last row:\n{p.tail(1).to_string()}")
    else:
        print("  FAILED"); ok = False

    print("\n--- TEST 2: get_market_returns() ---")
    r = get_market_returns()
    if not r.empty:
        print(f"  Shape: {r.shape}")
    else:
        print("  FAILED"); ok = False

    print("\n--- TEST 3: get_market_volume() ---")
    v = get_market_volume()
    if not v.empty:
        print(f"  Shape: {v.shape}")
    else:
        print("  FAILED"); ok = False

    print("\n--- TEST 4: Column normalization ---")
    t = pd.DataFrame({"close": [1], "open": [2], "volume": [3]})
    n = _normalize_columns(t)
    assert list(n.columns) == ["Close", "Open", "Volume"], f"Got {list(n.columns)}"
    print("  OK")

    print("\n" + "=" * 70)
    print("ALL PASSED" if ok else "SOME FAILED")
    print("=" * 70)
