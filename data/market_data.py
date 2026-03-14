"""
market_data.py — Downloads and caches market data from Yahoo Finance.

FILE LOCATION: ~/Desktop/srx-platform/data/market_data.py

ARCHITECTURE: "Persistent Browser Impersonation"

    Yahoo Finance (2025-2026) blocks requests at the TLS layer before
    even reading HTTP headers. The fix requires impersonating a real
    browser at the socket level using curl_cffi.

    Session strategy:
        1. Create ONE curl_cffi session impersonating Chrome.
        2. Perform a "warm-up" GET to finance.yahoo.com to collect cookies
           and establish IP trust. Yahoo's firewall requires a valid cookie
           jar — requests without cookies get skeleton responses.
        3. Reuse this session for ALL yf.download() and yf.Ticker().history()
           calls. Session persistence matters — Yahoo tracks session
           continuity and flags fresh sessions that jump straight to data.

    Download strategy (three phases):
        Phase 1 — Batch download via yf.download() with the warm session.
        Phase 2 — Single-ticker fallback via yf.Ticker().history() for
                   failures. The .history() method hits /v8/finance/chart/
                   which has different rate-limit rules than the batch endpoint.
        Phase 3 — Emergency stale-cache recovery. If a ticker fails all API
                   attempts, load any existing cache file even if it's older
                   than the TTL. Stale data beats no data.

PUBLIC API (unchanged — no dashboard changes needed):
    get_market_prices(tickers, period)
    get_market_returns(tickers, period)
    get_market_volume(tickers, period)
    get_close_prices(tickers, period)
    get_returns(tickers, period)
    download_single_ticker(ticker, period)
    download_multiple_tickers(tickers, period)
"""

import os
import sys
import time
import json
import random
import pandas as pd
import numpy as np

try:
    import yfinance as yf
except ImportError:
    raise ImportError("\n\nERROR: 'yfinance' not installed. Fix: pip install yfinance\n")

# Disable yfinance timezone cache to prevent stale-tz bot flags.
try:
    yf.set_tz_cache(False)
except AttributeError:
    pass

# Import curl_cffi for persistent browser impersonation.
_HAS_CURL_CFFI = False
try:
    from curl_cffi.requests import Session as CffiSession
    _HAS_CURL_CFFI = True
except ImportError:
    print("  [WARN]  curl_cffi not installed. Using yfinance defaults.")
    print("          For best results: pip install curl_cffi")


# =============================================================================
# CONFIGURATION
# =============================================================================

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
CACHE_MAX_AGE_SECONDS = 14400   # 4 hours (fresh cache)
BATCH_CHUNK_SIZE = 5
LOCKOUT_COOLDOWN = 12

SRX_CORE_TICKERS = ["SPY", "TLT", "HYG", "GLD", "UUP", "BTC-USD"]
DEFAULT_TICKERS = [
    "SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "HYG", "LQD", "GLD", "VNQ",
]
DEFAULT_PERIOD = "2y"


# =============================================================================
# PERSISTENT SESSION — created once, reused for all downloads
# =============================================================================

_SESSION = None

def _get_session():
    """
    Get or create a persistent curl_cffi session impersonating Chrome.

    The session performs a warm-up request to finance.yahoo.com on first
    creation to collect Yahoo's consent cookies. Without these cookies,
    Yahoo returns skeleton responses (headers present, data empty).
    """
    global _SESSION

    if _SESSION is not None:
        return _SESSION

    if not _HAS_CURL_CFFI:
        return None  # yfinance will use its own default session

    try:
        session = CffiSession(impersonate="chrome120")

        # Warm-up: hit the homepage to collect cookies and establish trust.
        # Yahoo's bot detection checks for a valid cookie jar. Requests
        # that jump directly to the data API without cookies get flagged.
        print("  [INIT]   Establishing browser session with Yahoo Finance...")
        resp = session.get(
            "https://finance.yahoo.com",
            timeout=15,
            allow_redirects=True,
        )

        cookie_count = len(session.cookies)
        print(f"  [INIT]   Session ready. Cookies collected: {cookie_count}")

        if cookie_count == 0:
            print("  [WARN]   No cookies received. Yahoo may still block.")

        _SESSION = session
        return _SESSION

    except Exception as e:
        print(f"  [WARN]   Session init failed: {e}. Using yfinance defaults.")
        return None


def _reset_session():
    """Force a new session on next call (used after lockout detection)."""
    global _SESSION
    _SESSION = None


# =============================================================================
# HELPERS
# =============================================================================

def _human_delay(lo: float = 0.3, hi: float = 1.5):
    time.sleep(random.uniform(lo, hi))


def _standardize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _get_cache_path(ticker: str, period: str = DEFAULT_PERIOD) -> str:
    return os.path.join(CACHE_DIR, f"{ticker.replace('/', '_')}_{period}.csv")


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
    """Title Case columns. Handles yfinance lowercase and MultiIndex flattening."""
    # If MultiIndex, flatten it first
    if isinstance(df.columns, pd.MultiIndex):
        # For single-ticker batch: columns are (Field, Ticker) or (Ticker, Field)
        # Try to extract just the field names
        df.columns = [
            col[0] if isinstance(col, tuple) else col
            for col in df.columns
        ]

    rename = {}
    for col in df.columns:
        c = col.strip() if isinstance(col, str) else str(col)
        t = c.title()
        if t.lower().replace(" ", "") in ("adjclose", "adjustedclose"):
            t = "Adj Close"
        rename[col] = t
    return df.rename(columns=rename)


def _is_json_error(e: Exception) -> bool:
    return (
        isinstance(e, json.JSONDecodeError)
        or "JSONDecodeError" in type(e).__name__
        or "Expecting value" in str(e)
        or "possibly delisted" in str(e)
        or "No price data" in str(e)
    )


def _clean_ticker_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize, filter columns, drop rows without Close data."""
    if df is None or df.empty:
        return pd.DataFrame()

    df = _normalize_columns(df)
    df = _safe_to_datetime_index(df)

    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    if "Close" not in keep:
        return pd.DataFrame()

    df = df[keep].dropna(subset=["Close"])
    return df if len(df) > 0 else pd.DataFrame()


# =============================================================================
# CACHE — with emergency stale-cache recovery
# =============================================================================

def _save_to_cache(ticker: str, period: str, df: pd.DataFrame):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        df.to_csv(_get_cache_path(ticker, period))
    except Exception as e:
        print(f"  [WARN]   Cache write failed for {ticker}: {e}")


def _load_from_cache(ticker: str, period: str, allow_stale: bool = False) -> pd.DataFrame:
    """
    Load from cache. If allow_stale=True, ignores TTL and loads any existing file.
    This is the emergency recovery path — stale data beats no data.
    """
    path = _get_cache_path(ticker, period)

    if not allow_stale and not _is_cache_fresh(path):
        return pd.DataFrame()

    if not os.path.exists(path):
        return pd.DataFrame()

    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            return pd.DataFrame()
        df = _normalize_columns(_safe_to_datetime_index(df))
        if allow_stale and not _is_cache_fresh(path):
            age_h = (time.time() - os.path.getmtime(path)) / 3600
            print(f"  [STALE]  {ticker}: loaded from cache ({age_h:.1f}h old)")
        return df
    except Exception:
        return pd.DataFrame()


# =============================================================================
# EXTRACT — handles MultiIndex from yf.download()
# =============================================================================

def _extract_from_batch(raw, ticker: str, batch_size: int) -> pd.DataFrame:
    """
    Extract one ticker from a yf.download() response.

    yf.download() returns different structures:
        - 1 ticker:  Simple columns (Open, High, Low, Close, Volume)
        - N tickers: MultiIndex columns [(ticker, field), ...]
        - 2025+ yfinance: Sometimes (field, ticker) instead of (ticker, field)
    """
    try:
        if raw is None or raw.empty:
            return pd.DataFrame()

        # Case 1: Single ticker — simple columns
        if batch_size == 1:
            return _clean_ticker_df(raw.copy())

        # Case 2: MultiIndex
        if isinstance(raw.columns, pd.MultiIndex):
            level0_vals = raw.columns.get_level_values(0).unique().tolist()

            # Check if ticker is in level 0 (ticker, field) format
            if ticker in level0_vals:
                return _clean_ticker_df(raw[ticker].copy())

            # Case-insensitive match
            match = next((t for t in level0_vals if str(t).upper() == ticker), None)
            if match is not None:
                return _clean_ticker_df(raw[match].copy())

            # Maybe it's (field, ticker) format — check level 1
            level1_vals = raw.columns.get_level_values(1).unique().tolist()
            if ticker in level1_vals:
                df = raw.xs(ticker, level=1, axis=1).copy()
                return _clean_ticker_df(df)

            match = next((t for t in level1_vals if str(t).upper() == ticker), None)
            if match is not None:
                df = raw.xs(match, level=1, axis=1).copy()
                return _clean_ticker_df(df)

        # Case 3: Flat columns — maybe only one ticker came back
        return _clean_ticker_df(raw.copy())

    except Exception as e:
        print(f"  [WARN]   Extract failed for {ticker}: {e}")
        return pd.DataFrame()


# =============================================================================
# PHASE 1: BATCH DOWNLOAD (yf.download with persistent session)
# =============================================================================

def _download_batch_chunk(tickers: list, period: str, session) -> dict:
    """Download a small chunk via yf.download(). Returns {ticker: df}."""
    kwargs = dict(
        tickers=tickers,
        period=period,
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )

    # Pass session only if we have a valid curl_cffi session
    if session is not None:
        kwargs["session"] = session

    raw = yf.download(**kwargs)

    if raw is None or raw.empty:
        return {}

    results = {}
    for t in tickers:
        df = _extract_from_batch(raw, t, len(tickers))
        if not df.empty:
            results[t] = df
            _save_to_cache(t, period, df)
            print(f"  [OK]     {t}: {len(df)} rows")
        else:
            print(f"  [EMPTY]  {t}: skeleton or missing in batch response")

    return results


# =============================================================================
# PHASE 2: SINGLE-TICKER FALLBACK (yf.Ticker.history — v8 endpoint)
# =============================================================================

def _download_v8_single(ticker: str, period: str, session) -> pd.DataFrame:
    """
    Fallback: use yf.Ticker().history() which hits /v8/finance/chart/.
    This endpoint has different rate-limit rules than the batch downloader.
    """
    try:
        _human_delay(1.0, 3.0)

        t_obj = yf.Ticker(ticker)

        # Pass session if available — Ticker objects accept it too
        if session is not None:
            t_obj._session = session

        data = t_obj.history(period=period, auto_adjust=True)

        df = _clean_ticker_df(data)
        if not df.empty:
            _save_to_cache(ticker, period, df)
        return df

    except Exception as e:
        if _is_json_error(e):
            print(f"  [BLOCK]  {ticker}: Yahoo blocking v8 endpoint")
        else:
            print(f"  [ERROR]  {ticker} v8: {e}")
        return pd.DataFrame()


# =============================================================================
# ORCHESTRATOR
# =============================================================================

def _batch_download(tickers: list, period: str = DEFAULT_PERIOD) -> dict:
    """
    Four-phase download:
        0. Fresh cache
        1. Batch chunks via yf.download() + persistent session
        2. Single-ticker via yf.Ticker().history() (v8 endpoint)
        3. Emergency stale-cache recovery
    """
    tickers = [_standardize_ticker(t) for t in tickers]

    # ---- Phase 0: Fresh cache ----
    results = {}
    to_download = []
    for t in tickers:
        df = _load_from_cache(t, period, allow_stale=False)
        if not df.empty:
            results[t] = df
            print(f"  [CACHE]  {t}: {len(df)} rows")
        else:
            to_download.append(t)

    if not to_download:
        print("  All tickers served from cache.")
        return results

    # Get persistent session (creates + warms on first call)
    session = _get_session()

    # ---- Phase 1: Batch chunks ----
    print(f"  [BATCH]  Fetching {len(to_download)} tickers in chunks of {BATCH_CHUNK_SIZE}")

    random.shuffle(to_download)
    chunks = [to_download[i:i + BATCH_CHUNK_SIZE]
              for i in range(0, len(to_download), BATCH_CHUNK_SIZE)]

    still_failed = []
    lockout = False

    for i, chunk in enumerate(chunks):
        if lockout:
            still_failed.extend(chunk)
            continue

        if i > 0:
            _human_delay(0.5, 2.0)

        print(f"  [CHUNK]  {i+1}/{len(chunks)}: {chunk}")

        try:
            got = _download_batch_chunk(chunk, period, session)
            results.update(got)
            still_failed.extend([t for t in chunk if t not in got])

        except json.JSONDecodeError:
            print(f"  [COOL]   JSONDecodeError — cooling down {LOCKOUT_COOLDOWN}s...")
            time.sleep(LOCKOUT_COOLDOWN + random.uniform(0, 3))

            # Reset session to get fresh cookies
            _reset_session()
            session = _get_session()

            # Retry chunk once
            try:
                _human_delay(1.0, 2.0)
                got = _download_batch_chunk(chunk, period, session)
                results.update(got)
                still_failed.extend([t for t in chunk if t not in got and t not in results])
            except Exception:
                print(f"  [LOCK]   Still blocked. Moving to v8 fallback.")
                still_failed.extend([t for t in chunk if t not in results])
                lockout = True

        except Exception as e:
            print(f"  [ERROR]  Chunk failed: {e}")
            still_failed.extend([t for t in chunk if t not in results])

    # ---- Phase 2: v8 single-ticker fallback ----
    still_failed = list(dict.fromkeys(t for t in still_failed if t not in results))

    if still_failed:
        print(f"  [v8]     Recovering {len(still_failed)} tickers via Ticker.history()")

        if lockout:
            cool = LOCKOUT_COOLDOWN + random.uniform(3, 6)
            print(f"  [COOL]   Extra cooldown: {cool:.0f}s")
            time.sleep(cool)
            _reset_session()
            session = _get_session()

        for t in still_failed:
            if t in results:
                continue
            print(f"  [v8]     {t}...")
            df = _download_v8_single(t, period, session)
            if not df.empty:
                results[t] = df
                print(f"  [OK]     {t}: {len(df)} rows (v8 recovered)")

    # ---- Phase 3: Emergency stale-cache recovery ----
    final_failed = [t for t in tickers if t not in results]
    if final_failed:
        print(f"  [STALE]  Attempting stale-cache recovery for: {final_failed}")
        for t in final_failed:
            df = _load_from_cache(t, period, allow_stale=True)
            if not df.empty:
                results[t] = df

    # ---- Report ----
    truly_failed = [t for t in tickers if t not in results]
    if truly_failed:
        print(f"  [SKIP]   No data available (even stale) for: {truly_failed}")

    return results


# =============================================================================
# PUBLIC DOWNLOAD FUNCTIONS
# =============================================================================

def download_single_ticker(
    ticker: str,
    period: str = DEFAULT_PERIOD,
    _retry: bool = True,
) -> pd.DataFrame:
    ticker = _standardize_ticker(ticker)
    cached = _load_from_cache(ticker, period)
    if not cached.empty:
        print(f"  [CACHE]  {ticker}: {len(cached)} rows")
        return cached
    result = _batch_download([ticker], period)
    return result.get(ticker, pd.DataFrame())


def download_multiple_tickers(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> dict:
    if tickers is None:
        tickers = DEFAULT_TICKERS
    tickers = [_standardize_ticker(t) for t in tickers]

    print(f"\n  Downloading {len(tickers)} tickers: {tickers}")
    print("  " + "-" * 58)

    results = _batch_download(tickers, period)

    succeeded = len(results)
    failed = [t for t in tickers if t not in results]
    print("  " + "-" * 58)
    print(f"  Done. {succeeded}/{len(tickers)} succeeded.")
    if failed:
        print(f"  Unavailable: {failed}")

    return results


# =============================================================================
# PUBLIC DATA FUNCTIONS
# =============================================================================

def get_market_prices(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> pd.DataFrame:
    """
    Get closing prices. Forward-fills gaps, then drops leading NaNs.
    Continues with partial tickers if some fail.
    """
    try:
        if tickers is None:
            tickers = SRX_CORE_TICKERS
        tickers = [_standardize_ticker(t) for t in tickers]

        all_data = download_multiple_tickers(tickers, period)

        if not all_data:
            print("  ERROR: No data for any ticker.")
            return pd.DataFrame()

        close_dict = {}
        missing = []
        for t in tickers:
            if t in all_data and "Close" in all_data[t].columns:
                close_dict[t] = all_data[t]["Close"]
            else:
                missing.append(t)

        if missing:
            print(f"  [WARN]   Missing: {missing}. Continuing with {len(close_dict)}/{len(tickers)}.")

        if not close_dict:
            print("  ERROR: No Close data available.")
            return pd.DataFrame()

        close_prices = pd.DataFrame(close_dict)
        rows_before = len(close_prices)
        close_prices = close_prices.ffill().dropna()
        rows_after = len(close_prices)

        if rows_before - rows_after > 0:
            print(f"  [JOIN]   Dropped {rows_before - rows_after} rows.")

        if close_prices.empty:
            print("  ERROR: No overlapping dates.")
            return pd.DataFrame()

        close_prices = _safe_to_datetime_index(close_prices.sort_index())

        s = close_prices.index[0]
        e = close_prices.index[-1]
        print(f"  [RESULT] {len(close_prices)} rows x {len(close_prices.columns)} tickers "
              f"({s.strftime('%Y-%m-%d') if hasattr(s,'strftime') else str(s)[:10]} to "
              f"{e.strftime('%Y-%m-%d') if hasattr(e,'strftime') else str(e)[:10]})")

        return close_prices

    except Exception as error:
        print(f"\n  ERROR in get_market_prices(): {error}")
        return pd.DataFrame()


def get_market_returns(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> pd.DataFrame:
    try:
        prices = get_market_prices(tickers, period)
        if prices.empty:
            return pd.DataFrame()

        returns = prices.pct_change().dropna()
        if returns.isin([np.inf, -np.inf]).any().any():
            returns = returns.replace([np.inf, -np.inf], 0.0)
        return returns

    except Exception as error:
        print(f"\n  ERROR in get_market_returns(): {error}")
        return pd.DataFrame()


def get_market_volume(
    tickers: list = None,
    period: str = DEFAULT_PERIOD,
) -> pd.DataFrame:
    try:
        if tickers is None:
            tickers = SRX_CORE_TICKERS
        tickers = [_standardize_ticker(t) for t in tickers]

        all_data = download_multiple_tickers(tickers, period)
        if not all_data:
            return pd.DataFrame()

        vol = {t: df["Volume"] for t, df in all_data.items() if "Volume" in df.columns}
        if not vol:
            return pd.DataFrame()

        return pd.DataFrame(vol).ffill().dropna().sort_index()

    except Exception as error:
        print(f"\n  ERROR in get_market_volume(): {error}")
        return pd.DataFrame()


# =============================================================================
# LEGACY
# =============================================================================

def get_close_prices(tickers=None, period=DEFAULT_PERIOD):
    return get_market_prices(tickers or DEFAULT_TICKERS, period)

def get_returns(tickers=None, period=DEFAULT_PERIOD):
    return get_market_returns(tickers or DEFAULT_TICKERS, period)


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("SRX — Market Data Test (Persistent Browser Impersonation)")
    print("=" * 70)

    ok = True

    print("\n--- TEST 1: get_market_prices() ---")
    p = get_market_prices()
    if not p.empty:
        print(f"  Shape: {p.shape}, Cols: {list(p.columns)}")
        print(f"  Last:\n{p.tail(1).to_string()}")
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

    print("\n--- TEST 5: MultiIndex normalization ---")
    mi = pd.MultiIndex.from_tuples([("SPY", "close"), ("SPY", "volume")])
    t2 = pd.DataFrame([[1, 2]], columns=mi)
    n2 = _normalize_columns(t2)
    print(f"  Flattened: {list(n2.columns)}")
    assert "Close" in n2.columns or "Spy" in n2.columns, "MultiIndex flatten failed"
    print("  OK")

    print("\n" + "=" * 70)
    print("ALL PASSED" if ok else "SOME FAILED")
    print("=" * 70)
