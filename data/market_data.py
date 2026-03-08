"""
market_data.py — Downloads and caches market data from Yahoo Finance.

FILE LOCATION: Save this file as:
    ~/Desktop/srx-platform/data/market_data.py

WHAT THIS MODULE DOES:
    1. Downloads historical adjusted close prices and volume data from Yahoo Finance
    2. Saves raw downloaded data into data/cache/ as CSV files
    3. Reuses cached CSV files when possible (cache lasts 24 hours)
    4. Handles missing data safely (no crashes if a ticker is bad)
    5. Uses an INNER JOIN across all assets so only dates shared by every asset remain
       (this removes crypto-only Sundays and holidays where some assets don't trade)
    6. Calculates daily returns
    7. Returns clean pandas DataFrames ready for portfolio math

CORE TICKERS (used by the SRX platform):
    SPY      — S&P 500 equities
    TLT      — 20+ Year US Treasury bonds
    HYG      — High-yield corporate bonds (junk bonds)
    GLD      — Gold
    UUP      — US Dollar Index proxy
    BTC-USD  — Bitcoin (cryptocurrency)

MAIN FUNCTIONS (the three you will use most):
    get_market_prices()  → DataFrame of closing prices, one column per ticker
    get_market_returns() → DataFrame of daily percentage returns
    get_market_volume()  → DataFrame of daily trading volume

LEGACY FUNCTIONS (still work, used by other SRX modules):
    get_close_prices()   → Same as get_market_prices but takes custom ticker lists
    get_returns()        → Same as get_market_returns but takes custom ticker lists
"""

import os
import time
import pandas as pd
import numpy as np

# Try to import yfinance. If it's not installed, show a helpful error.
try:
    import yfinance as yf
except ImportError:
    raise ImportError(
        "\n\n"
        "ERROR: The 'yfinance' package is not installed.\n"
        "Fix: Run this command in your terminal:\n"
        "  pip install yfinance\n"
    )


# =============================================================================
# CONFIGURATION
# =============================================================================

# Where to save cached CSV files.
# os.path.dirname(__file__) gives us the folder this script lives in (data/),
# then we append /cache to get data/cache/.
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")

# How long cached data stays valid (in seconds).
# 86400 seconds = 24 hours. After 24 hours, the cache is considered stale
# and the data will be re-downloaded from Yahoo Finance.
CACHE_MAX_AGE_SECONDS = 86400

# ---- SRX Core Tickers ----
# These six tickers represent the major asset classes the SRX platform tracks.
# Every ticker is UPPERCASE to avoid case-sensitivity issues in pandas columns.
SRX_CORE_TICKERS = [
    "SPY",      # S&P 500 ETF — represents US equities
    "TLT",      # iShares 20+ Year Treasury Bond — represents US government bonds
    "HYG",      # iShares iBoxx High Yield Corporate Bond — represents credit risk
    "GLD",      # SPDR Gold Trust — represents gold / commodities
    "UUP",      # Invesco DB US Dollar Index — represents US Dollar strength
    "BTC-USD",  # Bitcoin in US Dollars — represents cryptocurrency
]

# ---- Default Tickers for GSRI (backward compatibility) ----
# These are used by gsri_engine.py for the Global Systemic Risk Index.
# We keep this list so existing code doesn't break.
DEFAULT_TICKERS = [
    "SPY",   # S&P 500 (US large-cap stocks)
    "QQQ",   # Nasdaq 100 (US tech stocks)
    "IWM",   # Russell 2000 (US small-cap stocks)
    "EFA",   # International developed markets
    "EEM",   # Emerging markets
    "TLT",   # 20+ year US Treasury bonds
    "HYG",   # High-yield corporate bonds (junk bonds)
    "LQD",   # Investment-grade corporate bonds
    "GLD",   # Gold
    "VNQ",   # Real estate (REITs)
]

# Default time period for downloading data.
# "2y" means 2 years of daily data.
DEFAULT_PERIOD = "2y"


# =============================================================================
# HELPER FUNCTIONS (internal — used by the main functions below)
# =============================================================================

def _standardize_ticker(ticker: str) -> str:
    """
    Standardize a ticker symbol to uppercase and strip whitespace.

    Why this matters:
        Without this, "spy" and "SPY" would be treated as different columns
        in a pandas DataFrame, causing bugs that are hard to find.

    Examples:
        _standardize_ticker("  spy ")  → "SPY"
        _standardize_ticker("btc-usd") → "BTC-USD"
    """
    return ticker.strip().upper()


def _get_cache_path(ticker: str) -> str:
    """
    Build the file path where a ticker's cached data would be stored.

    We replace "/" with "_" in the ticker name because some tickers
    (like "BTC-USD") contain characters that are fine in filenames,
    but "/" would break the path.

    Example:
        _get_cache_path("SPY")     → ".../data/cache/SPY.csv"
        _get_cache_path("BTC-USD") → ".../data/cache/BTC-USD.csv"
    """
    # Replace any slashes just in case (shouldn't happen with Yahoo tickers,
    # but better safe than sorry).
    safe_name = ticker.replace("/", "_")
    return os.path.join(CACHE_DIR, f"{safe_name}.csv")


def _is_cache_fresh(filepath: str) -> bool:
    """
    Check if a cached file exists and is recent enough to use.

    Returns True if the file exists AND was modified less than 24 hours ago.
    Returns False otherwise (meaning we should re-download).
    """
    if not os.path.exists(filepath):
        return False

    # time.time() gives the current time in seconds since 1970.
    # os.path.getmtime() gives the file's last modification time the same way.
    # The difference is how many seconds ago the file was last saved.
    file_age_seconds = time.time() - os.path.getmtime(filepath)

    return file_age_seconds < CACHE_MAX_AGE_SECONDS


def _safe_to_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure a DataFrame's index is a proper DatetimeIndex.

    Why this is needed:
        When we load data from a CSV cache, pandas sometimes reads the dates
        as plain strings instead of datetime objects. This causes crashes when
        other code tries to call .strftime() or do date math on the index.
        This function forces the conversion so dates always work properly.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # Also remove timezone info if present (yfinance sometimes adds it,
    # but mixing tz-aware and tz-naive dates causes errors).
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    return df


# =============================================================================
# DOWNLOAD FUNCTIONS
# =============================================================================

def download_single_ticker(ticker: str, period: str = DEFAULT_PERIOD) -> pd.DataFrame:
    """
    Download historical price and volume data for one ticker symbol.

    How it works:
        1. Standardize the ticker to UPPERCASE.
        2. Check if we already have recent data cached in a CSV file.
        3. If yes, load from the CSV (fast, no internet needed).
        4. If no, download fresh data from Yahoo Finance and save it to CSV.

    Parameters:
        ticker: Stock/ETF symbol like "SPY", "GLD", or "BTC-USD"
        period: How far back to go. Options: "1y", "2y", "5y", "10y", "max"

    Returns:
        A pandas DataFrame with columns: Open, High, Low, Close, Volume
        The index is the date (DatetimeIndex).
        Returns an EMPTY DataFrame if the download fails.
    """
    # Step 1: Force uppercase so "spy" and "SPY" are treated the same.
    ticker = _standardize_ticker(ticker)
    cache_path = _get_cache_path(ticker)

    # ---- Step 2: Try loading from cache first ----
    if _is_cache_fresh(cache_path):
        try:
            cached_data = pd.read_csv(cache_path, index_col=0, parse_dates=True)

            if not cached_data.empty:
                # Force the index to be proper datetime (see helper above).
                cached_data = _safe_to_datetime_index(cached_data)
                print(f"  [CACHE HIT]  {ticker}: loaded {len(cached_data)} rows from cache")
                return cached_data

        except Exception:
            # If the cache file is corrupted or unreadable, we'll just
            # ignore it and re-download fresh data below.
            print(f"  [CACHE WARN] {ticker}: cache file corrupted, will re-download")

    # ---- Step 3: Download from Yahoo Finance ----
    try:
        print(f"  [DOWNLOAD]   {ticker}: fetching from Yahoo Finance...")
        stock = yf.Ticker(ticker)
        data = stock.history(period=period)

        # Check if Yahoo returned any data at all.
        if data is None or data.empty:
            print(
                f"\n"
                f"  WARNING: No data returned for ticker '{ticker}'.\n"
                f"  This could mean:\n"
                f"    1. The ticker symbol is misspelled (check on finance.yahoo.com)\n"
                f"    2. The stock/ETF was delisted or doesn't exist\n"
                f"    3. Yahoo Finance is temporarily down or rate-limiting you\n"
                f"  Tip: Go to https://finance.yahoo.com and search for '{ticker}'\n"
                f"       to verify it's a real symbol.\n"
            )
            return pd.DataFrame()

        # Keep only the columns we need for analysis.
        # "Open", "High", "Low" are useful for more advanced analytics later.
        # "Close" is the main price we use for returns.
        # "Volume" tells us how much trading happened.
        columns_to_keep = ["Open", "High", "Low", "Close", "Volume"]
        available_columns = [col for col in columns_to_keep if col in data.columns]

        if "Close" not in available_columns:
            print(f"  WARNING: {ticker} data has no 'Close' column. Skipping.")
            return pd.DataFrame()

        data = data[available_columns]

        # Force proper datetime index.
        data = _safe_to_datetime_index(data)

        # ---- Step 4: Save to cache ----
        # Create the cache directory if it doesn't exist yet.
        os.makedirs(CACHE_DIR, exist_ok=True)
        data.to_csv(cache_path)

        print(f"  [DOWNLOAD]   {ticker}: got {len(data)} rows, saved to cache")
        return data

    except Exception as error:
        print(
            f"\n"
            f"  ERROR downloading {ticker}: {error}\n"
            f"\n"
            f"  Possible fixes:\n"
            f"    1. Check your internet connection (try opening a website)\n"
            f"    2. Make sure '{ticker}' is a valid ticker symbol\n"
            f"    3. Try again in a few minutes (Yahoo may be rate-limiting)\n"
            f"    4. Run: pip install --upgrade yfinance\n"
        )
        return pd.DataFrame()


def download_multiple_tickers(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> dict:
    """
    Download data for multiple tickers and return a dictionary.

    Parameters:
        tickers: List of ticker symbols. If None, uses DEFAULT_TICKERS.
        period:  How far back to go ("1y", "2y", "5y", etc.)

    Returns:
        A dictionary where:
            keys   = ticker symbols (uppercase strings)
            values = DataFrames with columns [Open, High, Low, Close, Volume]
        Example: {"SPY": <DataFrame>, "GLD": <DataFrame>, ...}

        Tickers that failed to download are simply not included in the dict.
    """
    if tickers is None:
        tickers = DEFAULT_TICKERS

    # Standardize all tickers to uppercase.
    tickers = [_standardize_ticker(t) for t in tickers]

    print(f"\nDownloading data for {len(tickers)} tickers: {tickers}")
    print("-" * 60)

    results = {}
    for ticker in tickers:
        data = download_single_ticker(ticker, period)
        if not data.empty:
            results[ticker] = data

    # Summary.
    successful = len(results)
    failed = len(tickers) - successful
    print("-" * 60)
    print(f"Done. {successful} succeeded, {failed} failed.\n")

    if successful == 0:
        print(
            "WARNING: No data was downloaded for any ticker.\n"
            "The platform will not work without data.\n"
            "Check your internet connection and try again.\n"
        )

    return results


# =============================================================================
# MAIN PUBLIC FUNCTIONS — Use these in your code
# =============================================================================

def get_market_prices(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> pd.DataFrame:
    """
    Get closing prices for the SRX core tickers (or custom tickers).

    This is the MAIN function for getting price data in the SRX platform.

    How the INNER JOIN works:
        BTC-USD trades 7 days a week (including weekends).
        SPY, TLT, etc. only trade Monday through Friday.
        If we kept ALL dates, weekend rows would have prices for BTC-USD
        but NaN (missing) for everything else. This would break portfolio math.

        By using an INNER JOIN, we keep ONLY the dates where EVERY ticker
        has data. This automatically removes:
          - Crypto-only Sundays and Saturdays
          - US holidays where stocks don't trade but crypto does
          - Any day where even one asset has missing data

    Parameters:
        tickers: List of ticker symbols. If None, uses SRX_CORE_TICKERS.
        period:  How far back to go ("1y", "2y", "5y", etc.)

    Returns:
        A DataFrame where:
          - Each COLUMN is a ticker (uppercase string)
          - Each ROW is a trading date
          - Values are closing prices
          - Only dates where ALL tickers have data are included

        Example output:
                        SPY      TLT      HYG      GLD      UUP    BTC-USD
            2023-01-03  380.12   102.45   73.90   168.50   28.15   16625.08
            2023-01-04  383.76   103.12   74.22   170.22   28.05   16863.24
            ...
    """
    try:
        if tickers is None:
            tickers = SRX_CORE_TICKERS

        # Standardize all tickers to uppercase.
        tickers = [_standardize_ticker(t) for t in tickers]

        # Download all ticker data.
        all_data = download_multiple_tickers(tickers, period)

        if not all_data:
            print("ERROR: Cannot build price table — no data was downloaded.")
            return pd.DataFrame()

        # Extract the "Close" column from each ticker's DataFrame.
        close_dict = {}
        for ticker, df in all_data.items():
            if "Close" in df.columns:
                close_dict[ticker] = df["Close"]
            else:
                print(f"  WARNING: {ticker} has no 'Close' column, skipping.")

        if not close_dict:
            print("ERROR: None of the downloaded data contains 'Close' prices.")
            return pd.DataFrame()

        # ---- INNER JOIN: keep only dates where ALL tickers have data ----
        # pd.DataFrame(close_dict) aligns all series by their index (dates).
        # By default, this is an OUTER join (keeps all dates, fills gaps with NaN).
        # Then .dropna() removes any row that has even one NaN.
        # The result is effectively an INNER JOIN: only dates where every
        # single ticker has a valid closing price.
        close_prices = pd.DataFrame(close_dict)

        # Count how many rows we have before dropping.
        rows_before = len(close_prices)

        # Drop any row where ANY ticker has a missing value.
        # This is what removes crypto weekends, holidays, etc.
        close_prices = close_prices.dropna()

        rows_after = len(close_prices)
        rows_dropped = rows_before - rows_after

        if rows_dropped > 0:
            print(
                f"  [INNER JOIN] Dropped {rows_dropped} dates where not all "
                f"tickers had data (e.g., crypto weekends, holidays)."
            )

        if close_prices.empty:
            print(
                "ERROR: After inner join, no overlapping dates remain.\n"
                "This means the tickers don't share any common trading dates.\n"
                "Possible fix: Remove tickers that trade on very different schedules."
            )
            return pd.DataFrame()

        # Sort by date just to be safe.
        close_prices = close_prices.sort_index()

        print(
            f"  [RESULT]     {len(close_prices)} rows x {len(close_prices.columns)} tickers "
            f"(date range: {close_prices.index[0].strftime('%Y-%m-%d')} to "
            f"{close_prices.index[-1].strftime('%Y-%m-%d')})"
        )

        return close_prices

    except Exception as error:
        print(
            f"\n"
            f"ERROR in get_market_prices(): {error}\n"
            f"Possible fixes:\n"
            f"  1. Check your internet connection\n"
            f"  2. Verify your ticker symbols are valid\n"
            f"  3. Try a shorter period (e.g., '1y' instead of '5y')\n"
        )
        return pd.DataFrame()


def get_market_returns(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> pd.DataFrame:
    """
    Get daily percentage returns for the SRX core tickers (or custom tickers).

    A "return" is how much the price changed from one day to the next,
    expressed as a decimal fraction:
        0.02 means the price went UP by 2%
       -0.03 means the price went DOWN by 3%

    Uses get_market_prices() internally, so the same inner-join logic applies:
    only dates where all tickers have data are included.

    Parameters:
        tickers: List of ticker symbols. If None, uses SRX_CORE_TICKERS.
        period:  How far back to go.

    Returns:
        A DataFrame of daily returns with the same structure as get_market_prices()
        but with one fewer row (the first day has no "previous day" to compare to).

        Example output:
                         SPY       TLT       HYG       GLD       UUP   BTC-USD
            2023-01-04   0.0096   0.0065   0.0043   0.0102  -0.0036    0.0143
            2023-01-05  -0.0120  -0.0030  -0.0020   0.0055   0.0012   -0.0085
            ...
    """
    try:
        close_prices = get_market_prices(tickers, period)

        if close_prices.empty:
            return pd.DataFrame()

        # pct_change() calculates: (today - yesterday) / yesterday
        # The first row becomes NaN because there's no "yesterday" for day 1.
        # dropna() removes that first NaN row.
        returns = close_prices.pct_change().dropna()

        # Safety check: replace any infinite values with 0.
        # This can happen if a price was exactly 0 on some day (division by zero).
        if returns.isin([np.inf, -np.inf]).any().any():
            inf_count = returns.isin([np.inf, -np.inf]).sum().sum()
            print(
                f"  WARNING: Found {inf_count} infinite return values "
                f"(likely from a $0 price). Replacing with 0."
            )
            returns = returns.replace([np.inf, -np.inf], 0.0)

        return returns

    except Exception as error:
        print(
            f"\n"
            f"ERROR in get_market_returns(): {error}\n"
            f"Possible fixes:\n"
            f"  1. Make sure get_market_prices() works first\n"
            f"  2. Check your internet connection\n"
            f"  3. Verify your ticker symbols\n"
        )
        return pd.DataFrame()


def get_market_volume(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> pd.DataFrame:
    """
    Get daily trading volume for the SRX core tickers (or custom tickers).

    Volume is the number of shares (or coins, for crypto) traded each day.
    High volume means lots of people are buying/selling.
    Low volume can indicate illiquidity (hard to buy/sell without moving price).

    Uses the same inner-join logic as get_market_prices().

    Parameters:
        tickers: List of ticker symbols. If None, uses SRX_CORE_TICKERS.
        period:  How far back to go.

    Returns:
        A DataFrame of daily volumes, one column per ticker.

        Example output:
                            SPY         TLT         HYG       GLD       UUP      BTC-USD
            2023-01-03  89000000    15000000    20000000   8000000   1500000   12000000000
            2023-01-04  92000000    14500000    19500000   7800000   1450000   11500000000
            ...
    """
    try:
        if tickers is None:
            tickers = SRX_CORE_TICKERS

        # Standardize all tickers to uppercase.
        tickers = [_standardize_ticker(t) for t in tickers]

        # Download all ticker data.
        all_data = download_multiple_tickers(tickers, period)

        if not all_data:
            print("ERROR: Cannot build volume table — no data was downloaded.")
            return pd.DataFrame()

        # Extract the "Volume" column from each ticker's DataFrame.
        volume_dict = {}
        for ticker, df in all_data.items():
            if "Volume" in df.columns:
                volume_dict[ticker] = df["Volume"]
            else:
                print(f"  WARNING: {ticker} has no 'Volume' column, skipping.")

        if not volume_dict:
            print("ERROR: None of the downloaded data contains 'Volume' data.")
            return pd.DataFrame()

        # Inner join: only keep dates where ALL tickers have volume data.
        volume_df = pd.DataFrame(volume_dict).dropna().sort_index()

        if volume_df.empty:
            print("ERROR: After inner join, no overlapping volume dates remain.")
            return pd.DataFrame()

        return volume_df

    except Exception as error:
        print(
            f"\n"
            f"ERROR in get_market_volume(): {error}\n"
            f"Possible fixes:\n"
            f"  1. Check your internet connection\n"
            f"  2. Verify your ticker symbols\n"
        )
        return pd.DataFrame()


# =============================================================================
# LEGACY FUNCTIONS (backward compatibility — used by other SRX modules)
# =============================================================================

def get_close_prices(tickers: list = None, period: str = DEFAULT_PERIOD) -> pd.DataFrame:
    """
    Legacy wrapper — calls get_market_prices() internally.

    This function exists so that portfolio_engine.py, gsri_engine.py, and
    pricing_engine.py continue to work without any changes.

    The only difference from get_market_prices() is the default tickers:
    this function defaults to DEFAULT_TICKERS (10 ETFs for GSRI),
    while get_market_prices() defaults to SRX_CORE_TICKERS (6 assets).
    """
    if tickers is None:
        tickers = DEFAULT_TICKERS
    return get_market_prices(tickers, period)


def get_returns(tickers: list = None, period: str = DEFAULT_PERIOD) -> pd.DataFrame:
    """
    Legacy wrapper — calls get_market_returns() internally.

    This function exists so that portfolio_engine.py, gsri_engine.py, and
    pricing_engine.py continue to work without any changes.
    """
    if tickers is None:
        tickers = DEFAULT_TICKERS
    return get_market_returns(tickers, period)


# =============================================================================
# EXAMPLE USAGE — Run this file directly to test it
# =============================================================================

if __name__ == "__main__":
    """
    This block only runs when you execute this file directly:
        cd ~/Desktop/srx-platform
        source venv/bin/activate
        python3 -m data.market_data

    It does NOT run when other modules import from this file.
    This is a safe way to include test/demo code.
    """

    print("=" * 70)
    print("SRX PLATFORM — Market Data Module Test")
    print("=" * 70)

    # Track whether all tests pass.
    all_passed = True

    # ---- Test 1: Get closing prices ----
    print("\n--- TEST 1: get_market_prices() ---\n")
    prices = get_market_prices()

    if not prices.empty:
        print(f"\nShape: {prices.shape[0]} rows x {prices.shape[1]} columns")
        print(f"Columns: {list(prices.columns)}")
        print(f"\nFirst 5 rows:")
        print(prices.head().to_string())
        print(f"\nLast 5 rows:")
        print(prices.tail().to_string())
    else:
        print("FAILED: No price data returned.")
        all_passed = False

    # ---- Test 2: Get daily returns ----
    print("\n\n--- TEST 2: get_market_returns() ---\n")
    returns = get_market_returns()

    if not returns.empty:
        print(f"\nShape: {returns.shape[0]} rows x {returns.shape[1]} columns")
        print(f"\nFirst 5 rows (daily returns as decimals):")
        print(returns.head().to_string())
        print(f"\nBasic statistics:")
        print(returns.describe().round(6).to_string())
    else:
        print("FAILED: No return data returned.")
        all_passed = False

    # ---- Test 3: Get volume ----
    print("\n\n--- TEST 3: get_market_volume() ---\n")
    volume = get_market_volume()

    if not volume.empty:
        print(f"\nShape: {volume.shape[0]} rows x {volume.shape[1]} columns")
        print(f"\nFirst 5 rows:")
        print(volume.head().to_string())
    else:
        print("FAILED: No volume data returned.")
        all_passed = False

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    if all_passed:
        print("STATUS: All 3 tests passed. Market data module is working.")
    else:
        print("STATUS: Some tests failed. Check the error messages above.")
    print("=" * 70)
