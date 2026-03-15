"""
historical_validation.py — Walk-Forward Crisis Validation Engine

FILE LOCATION: ~/Desktop/srx-platform/backend/historical_validation.py

CALIBRATION PHILOSOPHY:
    Short windows (20/40d) detect "Shock" regimes — flash crashes, sudden
    liquidity events. Thresholds are TIGHT so the GSRI hits Elevated fast.

    Long windows (90/120d) detect "Structural" regimes — slow rot, credit
    buildup, subprime contagion. Thresholds are DEEP so Elevated represents
    sustained systemic stress, not noise.

    The Shock Multiplier (1.25x) fires when vol or drawdown doubles in 5
    days, ensuring exogenous shocks (COVID) break past threshold even when
    the longer lookback dilutes the signal.

RISK ZONES:
    0-29:   Normal          (green)
    30-49:  Monitoring       (yellow)
    50-74:  Elevated / Hedging Entry Zone   (orange) — 2σ event
    75-100: Critical / Systemic Failure Zone (red)   — 3σ event
"""

import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from data.market_data import get_market_prices, get_market_returns, get_market_volume


# =============================================================================
# VIX COMPARISON HELPERS
# =============================================================================

def normalize_series(series: pd.Series) -> pd.Series:
    """Min-max normalize a Series to 0-100 over its range."""
    smin = series.min()
    smax = series.max()
    if smax == smin:
        return pd.Series(50.0, index=series.index)
    return ((series - smin) / (smax - smin) * 100).round(2)


def fetch_vix_for_era(era: dict, gsri_dates) -> dict:
    """
    Download ^VIX data for a crisis era and align to the GSRI date index.

    Returns:
        {
            "vix_raw": pd.Series (raw VIX values, aligned),
            "vix_normalized": pd.Series (0-100 normalized for chart overlay),
            "available": bool,
            "warning": str or None,
        }
    """
    import yfinance as yf

    try:
        window_start = pd.Timestamp(era["window_start"])
        window_end = pd.Timestamp(era["window_end"])

        raw = yf.download(
            "^VIX",
            start=(window_start - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
            end=(window_end + pd.Timedelta(days=5)).strftime("%Y-%m-%d"),
            auto_adjust=True, progress=False,
        )

        if raw is None or raw.empty:
            return {"available": False, "warning": "VIX data unavailable for this era."}

        # Flatten MultiIndex if present
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        # Normalize column names
        raw.columns = [c.strip().title() for c in raw.columns]

        if "Close" not in raw.columns:
            return {"available": False, "warning": "VIX data missing Close column."}

        if raw.index.tz is not None:
            raw.index = raw.index.tz_localize(None)

        vix = raw["Close"]
        if not isinstance(vix, pd.Series):
            return {"available": False, "warning": "VIX Close is not a Series."}

        # Align to GSRI dates via forward-fill then reindex
        gsri_idx = pd.DatetimeIndex(gsri_dates)
        vix_aligned = vix.reindex(gsri_idx.union(vix.index)).ffill().reindex(gsri_idx)
        vix_aligned = vix_aligned.dropna()

        if len(vix_aligned) < 10:
            return {"available": False, "warning": f"Only {len(vix_aligned)} VIX data points after alignment."}

        return {
            "vix_raw": vix_aligned,
            "vix_normalized": normalize_series(vix_aligned),
            "available": True,
            "warning": None,
        }

    except Exception as e:
        return {"available": False, "warning": f"VIX download failed: {e}"}

# =============================================================================
# CRISIS DEFINITIONS
# =============================================================================

CRISIS_ERAS = {
    "2008_gfc": {
        "label": "2008 Global Financial Crisis",
        "window_start": "2007-06-01",
        "window_end": "2009-06-30",
        "crash_date": "2008-09-15",
        "bottom_date": "2009-03-09",
        "annotation": "Lehman Brothers Collapse",
    },
    "2020_covid": {
        "label": "2020 COVID-19 Crash",
        "window_start": "2019-09-01",
        "window_end": "2020-09-30",
        "crash_date": "2020-03-11",
        "bottom_date": "2020-03-23",
        "annotation": "WHO Declares Pandemic",
    },
    "2022_rates": {
        "label": "2022 Rate Tightening",
        "window_start": "2022-01-01",
        "window_end": "2023-03-31",
        "crash_date": "2022-06-13",
        "bottom_date": "2022-10-12",
        "annotation": "Aggressive Fed Tightening",
    },
}

HISTORICAL_TICKERS = ["SPY", "TLT", "HYG", "GLD", "EFA", "EEM", "QQQ", "IWM"]

SRS_W_VOL = 0.30
SRS_W_LIQ = 0.20
SRS_W_CORR = 0.25
SRS_W_DD = 0.25

AMIHUD_SCALE = 1e9

SHOCK_MULTIPLIER = 1.25
SHOCK_ACCELERATION_WINDOW = 5
SHOCK_ACCELERATION_THRESHOLD = 1.0  # 100% increase = doubling


# =============================================================================
# ADAPTIVE THRESHOLDS — tighter for short windows, deeper for long
# =============================================================================

def _get_thresholds(lookback: int) -> dict:
    """
    Return scoring thresholds calibrated to the lookback window.

    Short windows (20d): tight thresholds → fast signal for flash crashes.
    Long windows (120d): deep thresholds → sustained stress for structural decay.
    """
    if lookback <= 20:
        return {"vol": (0.06, 0.28), "liq": (0.0, 15.0), "corr": (0.05, 0.55), "dd": (0.0, 0.06)}
    elif lookback <= 40:
        return {"vol": (0.07, 0.32), "liq": (0.0, 20.0), "corr": (0.03, 0.60), "dd": (0.0, 0.07)}
    elif lookback <= 60:
        return {"vol": (0.08, 0.38), "liq": (0.0, 25.0), "corr": (0.0, 0.65), "dd": (0.0, 0.09)}
    elif lookback <= 90:
        return {"vol": (0.09, 0.42), "liq": (0.0, 30.0), "corr": (0.0, 0.70), "dd": (0.0, 0.11)}
    else:
        return {"vol": (0.10, 0.48), "liq": (0.0, 35.0), "corr": (0.0, 0.75), "dd": (0.0, 0.13)}


# =============================================================================
# NONLINEAR SCORING
# =============================================================================

def _score(value, low, high, exponent=1.5):
    if high <= low:
        return 0.0
    clamped = max(low, min(high, value))
    normalized = (clamped - low) / (high - low)
    return round(100.0 * (normalized ** exponent), 2)


# =============================================================================
# SHOCK MULTIPLIER
# =============================================================================

def _compute_shock_multiplier(
    v_scores: list, m_scores: list,
    accel_window: int = SHOCK_ACCELERATION_WINDOW,
    threshold: float = SHOCK_ACCELERATION_THRESHOLD,
) -> float:
    """
    If volatility or drawdown DOUBLED within the last `accel_window` days,
    return 1.25x multiplier. Otherwise return 1.0.
    """
    for scores in [v_scores, m_scores]:
        if len(scores) >= accel_window + 1:
            current = scores[-1]
            past = scores[-(accel_window + 1)]
            if past > 5 and current > 0:
                ratio = current / past
                if ratio >= (1.0 + threshold):
                    return SHOCK_MULTIPLIER
    return 1.0


# =============================================================================
# REGIME CLASSIFICATION
# =============================================================================

def _classify_regime(gsri_df: pd.DataFrame, era: dict) -> dict:
    """
    Classify the crisis detection as Structural or Exogenous Shock.

    Structural: GSRI ≥ 50 more than 100 days before crash.
    Exogenous Shock: GSRI ≥ 50 within 10 days of crash AND shock multiplier fired.
    """
    crash = pd.Timestamp(era["crash_date"])
    pre = gsri_df[gsri_df["date"] < crash]

    elevated = pre[pre["gsri"] >= 50]
    shock_active = gsri_df["shock_multiplier"].max() > 1.0

    if not elevated.empty:
        first_elevated = elevated.iloc[0]["date"]
        lead_days = (crash - first_elevated).days

        if lead_days > 100:
            return {
                "regime": "Structural Decay",
                "lead_days": lead_days,
                "first_elevated": first_elevated,
                "narrative": (
                    f"The GSRI crossed the Elevated threshold (50) on "
                    f"{first_elevated.strftime('%Y-%m-%d')}, a full {lead_days} days "
                    f"before the crash. This is a Structural Regime detection — the "
                    f"engine identified internal systemic rot building through rising "
                    f"cross-asset correlation and deteriorating liquidity conditions "
                    f"long before the visible market break."
                ),
            }
        elif lead_days <= 10 and shock_active:
            return {
                "regime": "Exogenous Shock",
                "lead_days": lead_days,
                "first_elevated": first_elevated,
                "narrative": (
                    f"The GSRI crossed Elevated just {lead_days} days before the crash, "
                    f"with the Shock Multiplier (1.25×) activated by a rapid doubling "
                    f"of volatility within 5 trading days. This is an Exogenous Shock "
                    f"detection — the engine responded to sudden liquidity evaporation "
                    f"and volatility acceleration characteristic of black swan events."
                ),
            }
        else:
            return {
                "regime": "Early Warning",
                "lead_days": lead_days,
                "first_elevated": first_elevated,
                "narrative": (
                    f"The GSRI reached Elevated {lead_days} days before the crash date. "
                    f"The signal provided actionable lead time for hedging entry."
                ),
            }
    else:
        # Check if it reached elevated after crash
        post = gsri_df[gsri_df["date"] >= crash]
        post_elevated = post[post["gsri"] >= 50]
        peak = gsri_df["gsri"].max()

        if shock_active:
            return {
                "regime": "Exogenous Shock (Reactive)",
                "lead_days": 0,
                "first_elevated": crash,
                "narrative": (
                    f"The Shock Multiplier activated during the crash as volatility "
                    f"doubled within 5 days. The GSRI peaked at {peak:.1f}. The speed "
                    f"of the dislocation exceeded the lookback window's ability to "
                    f"provide advance warning, but the Shock Multiplier correctly "
                    f"identified the systemic break in real-time."
                ),
            }
        else:
            return {
                "regime": "Below Threshold",
                "lead_days": 0,
                "first_elevated": None,
                "narrative": (
                    f"The GSRI peaked at {peak:.1f}, below the Elevated threshold (50). "
                    f"Try a shorter lookback window for faster sensitivity or verify "
                    f"the selected tickers have sufficient cross-asset diversity."
                ),
            }


# =============================================================================
# WALK-FORWARD ENGINE
# =============================================================================

def compute_walkforward_gsri(
    tickers: list = None,
    era_key: str = "2008_gfc",
    lookback: int = 60,
    benchmark: str = "SPY",
) -> dict:
    if tickers is None:
        tickers = HISTORICAL_TICKERS
    tickers = [t.strip().upper() for t in tickers]
    if benchmark not in tickers:
        tickers = [benchmark] + tickers

    era = CRISIS_ERAS.get(era_key)
    if era is None:
        return {"error": f"Unknown era '{era_key}'. Options: {list(CRISIS_ERAS.keys())}"}

    thresholds = _get_thresholds(lookback)

    window_start = pd.Timestamp(era["window_start"])
    window_end = pd.Timestamp(era["window_end"])
    earliest_needed = window_start - pd.Timedelta(days=lookback * 3)

    import yfinance as yf

    print(f"\n  [HIST]   {era['label']} | Lookback={lookback}d | Thresholds: {thresholds}")

    all_prices, all_returns, all_volume = {}, {}, {}

    for t in tickers:
        try:
            raw = yf.download(t, start=earliest_needed.strftime("%Y-%m-%d"),
                              end=(window_end + pd.Timedelta(days=5)).strftime("%Y-%m-%d"),
                              auto_adjust=True, progress=False)
            if raw is None or raw.empty:
                continue

            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)

            rename = {}
            for c in raw.columns:
                s = c.strip() if isinstance(c, str) else str(c)
                title = s.title()
                if title.lower().replace(" ", "") in ("adjclose", "adjustedclose"):
                    title = "Adj Close"
                rename[c] = title
            raw = raw.rename(columns=rename)

            if "Close" not in raw.columns:
                continue

            if raw.index.tz is not None:
                raw.index = raw.index.tz_localize(None)

            close_col = raw["Close"]
            if not isinstance(close_col, pd.Series) or len(close_col.dropna()) < 50:
                continue

            in_window = close_col[(close_col.index >= window_start) & (close_col.index <= window_end)]
            if len(in_window) < 50:
                print(f"  [HIST]   {t}: {len(in_window)} days in window, skipping")
                continue

            all_prices[t] = close_col
            all_returns[t] = close_col.pct_change()
            if "Volume" in raw.columns and isinstance(raw["Volume"], pd.Series):
                all_volume[t] = raw["Volume"]

            print(f"  [HIST]   {t}: {len(close_col)} rows")
        except Exception as e:
            print(f"  [HIST]   {t}: failed ({e})")

    if not all_prices:
        return {"error": "No tickers had data for this era."}

    prices = pd.DataFrame(all_prices).ffill().dropna()
    returns = pd.DataFrame(all_returns).ffill().dropna()
    volume = pd.DataFrame(all_volume).ffill().dropna() if all_volume else pd.DataFrame()

    if prices.empty or returns.empty:
        return {"error": "No overlapping data for this era."}

    available = list(prices.columns)
    if benchmark not in available:
        return {"error": f"Benchmark '{benchmark}' has no data for this era."}

    window_dates = returns[(returns.index >= window_start) & (returns.index <= window_end)].index
    if len(window_dates) < 10:
        return {"error": f"Only {len(window_dates)} trading days in window."}

    # ---- Walk-forward ----
    rows = []
    v_history, m_history = [], []

    vl, vh = thresholds["vol"]
    ll, lh = thresholds["liq"]
    cl, ch = thresholds["corr"]
    dl, dh = thresholds["dd"]

    for t in window_dates:
        ret_slice = returns[returns.index <= t].tail(lookback)
        px_slice = prices[prices.index <= t].tail(lookback)

        if len(ret_slice) < max(20, lookback // 3):
            continue

        # V_t
        avg_vol = ret_slice.std().mean() * np.sqrt(252)
        v_score = _score(avg_vol, vl, vh)

        # C_t
        cm = ret_slice.corr()
        n = len(cm)
        avg_corr = cm.values[~np.eye(n, dtype=bool)].mean() if n > 1 else 0.0
        c_score = _score(avg_corr, cl, ch)

        # L_t
        l_score = 0.0
        if not volume.empty:
            vol_slice = volume[volume.index <= t].tail(lookback)
            shared = list(set(ret_slice.columns) & set(vol_slice.columns))
            if shared and len(vol_slice) > 5:
                amihud = (ret_slice[shared].abs() / vol_slice[shared].replace(0, np.nan)).mean().mean() * AMIHUD_SCALE
                l_score = _score(amihud, ll, lh)

        # M_t
        raw_dd = 0.0
        m_score = 0.0
        if len(px_slice) > 5 and benchmark in px_slice.columns:
            bm = px_slice[benchmark]
            raw_dd = abs(((bm - bm.cummax()) / bm.cummax()).min())
            m_score = _score(raw_dd, dl, dh)

        # Track history for shock detection
        v_history.append(v_score)
        m_history.append(m_score)

        # Shock Multiplier
        shock = _compute_shock_multiplier(v_history, m_history)

        # Combine
        raw_gsri = (SRS_W_VOL * v_score + SRS_W_LIQ * l_score +
                    SRS_W_CORR * c_score + SRS_W_DD * m_score)
        gsri = min(100.0, round(raw_gsri * shock, 2))

        rows.append({
            "date": t,
            "gsri": gsri,
            "gsri_raw": round(raw_gsri, 2),
            "volatility": round(v_score, 2),
            "correlation": round(c_score, 2),
            "liquidity": round(l_score, 2),
            "drawdown": round(m_score, 2),
            "shock_multiplier": shock,
            "raw_vol": round(avg_vol, 4),
            "raw_corr": round(avg_corr, 4),
            "raw_dd": round(raw_dd, 4),
        })

    if not rows:
        return {"error": "Walk-forward produced no results."}

    gsri_df = pd.DataFrame(rows)
    gsri_df["date"] = pd.to_datetime(gsri_df["date"])

    bm_window = prices[(prices.index >= window_start) & (prices.index <= window_end)][benchmark]

    snapshots = _build_snapshots(gsri_df, era)
    regime = _classify_regime(gsri_df, era)

    # Fetch VIX for comparison
    vix_data = fetch_vix_for_era(era, gsri_df["date"])

    return {
        "era": era,
        "era_key": era_key,
        "gsri_series": gsri_df,
        "benchmark_prices": bm_window,
        "benchmark_ticker": benchmark,
        "signal_snapshots": snapshots,
        "tickers_used": available,
        "lookback": lookback,
        "thresholds": thresholds,
        "regime": regime,
        "vix": vix_data,
    }


# =============================================================================
# SNAPSHOTS
# =============================================================================

def _build_snapshots(gsri_df: pd.DataFrame, era: dict) -> pd.DataFrame:
    crash = pd.Timestamp(era["crash_date"])
    bottom = pd.Timestamp(era["bottom_date"])
    dates_index = gsri_df["date"]

    def _closest(target):
        return (dates_index - target).abs().idxmin()

    crash_idx = _closest(crash)
    offsets = {"T-10": -10, "T-5": -5, "T-2": -2, "T-1": -1, "Crash": 0}

    rows = []
    for label, offset in offsets.items():
        idx = max(0, min(crash_idx + offset, len(gsri_df) - 1))
        r = gsri_df.iloc[idx]
        rows.append({
            "Event": label, "Date": r["date"].strftime("%Y-%m-%d"),
            "GSRI": r["gsri"], "Shock": r["shock_multiplier"],
            "Vol": r["volatility"], "Corr": r["correlation"],
            "Liq": r["liquidity"], "DD": r["drawdown"],
        })

    bottom_idx = _closest(bottom)
    if bottom_idx < len(gsri_df):
        r = gsri_df.iloc[bottom_idx]
        rows.append({
            "Event": "Bottom", "Date": r["date"].strftime("%Y-%m-%d"),
            "GSRI": r["gsri"], "Shock": r["shock_multiplier"],
            "Vol": r["volatility"], "Corr": r["correlation"],
            "Liq": r["liquidity"], "DD": r["drawdown"],
        })

    return pd.DataFrame(rows)


if __name__ == "__main__":
    for era in ["2008_gfc", "2020_covid"]:
        print(f"\n{'='*70}\n{era}\n{'='*70}")
        r = compute_walkforward_gsri(era_key=era, lookback=60)
        if "error" in r:
            print(f"  ERROR: {r['error']}")
        else:
            print(f"  Regime: {r['regime']['regime']}")
            print(f"  Peak GSRI: {r['gsri_series']['gsri'].max():.1f}")
            print(f"  {r['regime']['narrative'][:120]}...")
