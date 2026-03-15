"""
gsri_engine.py — Systemic Risk Score (SRS) and Global Systemic Risk Index (GSRI)

FILE LOCATION: Save this file as:
    ~/Desktop/srx-platform/backend/gsri_engine.py

WHAT THIS MODULE DOES:

    1. SYSTEMIC RISK SCORE (SRS):
       A composite 0–100 score measuring real-time systemic stress.
       Built from four raw signals:

         V_t — Volatility Signal:
               Rolling 20-day annualized volatility across major assets.
               High V_t means prices are swinging wildly.

         L_t — Liquidity Proxy (Amihud Illiquidity Ratio):
               abs(return) / dollar_volume, scaled by 10^9 for readability.
               High L_t means markets are illiquid (hard to trade without
               moving the price). Aggregated across assets into one signal.

         C_t — Correlation Signal:
               Rolling 20-day average off-diagonal correlation.
               High C_t means all assets are moving together (herd behavior),
               which is dangerous because diversification stops working.

         M_t — Drawdown / Stress Signal:
               Rolling drawdown acceleration — how fast are prices falling
               from their recent peaks? Captures acute crash dynamics.

       Combined via a non-linear weighting function:
         SRS_t = f(V_t, L_t, C_t, M_t)
       calibrated so that known crises (2008, 2020) score 80+.

    2. GLOBAL SYSTEMIC RISK INDEX (GSRI):
       A higher-level 0–100 score that combines asset-class-specific stress:
         - Equity volatility (from SPY)
         - Credit stress (from HYG)
         - Treasury volatility (from TLT)
         - Crypto volatility (from BTC-USD)
         - Cross-asset correlation (average pairwise)

MAIN FUNCTIONS:
    compute_srs_components()    → Raw V_t, L_t, C_t, M_t time series
    compute_srs_series()        → SRS time series (0–100)
    compute_gsri_series()       → GSRI time series (0–100)
    calculate_gsri()            → API-ready output with current value + history

BACKWARD COMPATIBILITY:
    calculate_gsri(period, rolling_window) is used by:
      - backend/main.py (the /gsri endpoint)
      - backend/pricing_engine.py (GSRI-adjusted pricing)
      - frontend/dashboard.py (reads current_gsri, risk_level, gsri_history, sub_scores)
    All return keys are preserved.
"""

import numpy as np
import pandas as pd
import sys
import os

# Add the project root to the Python path so we can import from data/.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from data.market_data import (
    get_market_prices,
    get_market_returns,
    get_market_volume,
    get_returns,
    get_close_prices,
    DEFAULT_TICKERS,
    SRX_CORE_TICKERS,
)


# =============================================================================
# CONSTANTS
# =============================================================================

# Number of trading days in a year (used to annualize daily statistics).
TRADING_DAYS_PER_YEAR = 252

# Default rolling window for sub-signal calculations (in trading days).
# 20 trading days ≈ 1 calendar month.
DEFAULT_ROLLING_WINDOW = 20

# Amihud illiquidity scaling factor.
# Raw Amihud values are extremely small decimals (like 0.000000001).
# Multiplying by 10^9 makes them readable (values around 0.1 to 100).
AMIHUD_SCALE_FACTOR = 1e9

# SRS sub-signal weights (calibrated to historical stress events).
# These determine how much each signal contributes to the overall SRS.
SRS_WEIGHT_VOLATILITY = 0.30    # V_t — how wild are price swings?
SRS_WEIGHT_LIQUIDITY = 0.20     # L_t — how hard is it to trade?
SRS_WEIGHT_CORRELATION = 0.25   # C_t — are all assets moving together?
SRS_WEIGHT_DRAWDOWN = 0.25      # M_t — how fast are prices falling?

# GSRI sub-component weights.
GSRI_WEIGHT_EQUITY_VOL = 0.25
GSRI_WEIGHT_CREDIT_STRESS = 0.25
GSRI_WEIGHT_TREASURY_VOL = 0.15
GSRI_WEIGHT_CRYPTO_VOL = 0.10
GSRI_WEIGHT_CROSS_CORR = 0.25

# Shock Multiplier — detects sudden acceleration in volatility or drawdown.
# If either signal doubles within SHOCK_WINDOW trading days, the final
# SRS/GSRI is multiplied by SHOCK_MULTIPLIER. This ensures exogenous shocks
# (like COVID) break past thresholds even when the lookback dilutes the signal.
SHOCK_MULTIPLIER = 1.25
SHOCK_WINDOW = 5         # 5 trading days = 1 week
SHOCK_THRESHOLD = 1.0    # 100% increase = doubling


# =============================================================================
# HELPER: Non-linear scoring function
# =============================================================================

def _nonlinear_score(value: float, low: float, high: float, exponent: float = 1.5) -> float:
    """
    Map a raw value to a 0–100 score using a non-linear (power) curve.

    Why non-linear?
        In financial risk, the jump from "calm" to "slightly stressed" is
        less dangerous than the jump from "stressed" to "crisis." A non-linear
        curve makes the score accelerate upward as conditions worsen, so the
        difference between 70 and 90 is treated as more significant than
        the difference between 20 and 40. This matches how systemic crises
        actually develop — slowly at first, then very fast.

    Parameters:
        value:    The raw signal value to score.
        low:      The value that maps to score 0 (calm conditions).
        high:     The value that maps to score 100 (crisis conditions).
        exponent: Controls the curve shape. 1.0 = linear, >1.0 = convex
                  (slow start, fast finish), <1.0 = concave.

    Returns:
        A float from 0.0 to 100.0.
    """
    if high <= low:
        return 0.0

    # Clamp the value to [low, high] range.
    clamped = max(low, min(high, value))

    # Normalize to 0–1 range.
    normalized = (clamped - low) / (high - low)

    # Apply the non-linear power curve.
    scored = normalized ** exponent

    return scored * 100.0


def _compute_shock_series(v_scores: pd.Series, m_scores: pd.Series) -> pd.Series:
    """
    Compute the shock multiplier for each day in the time series.

    If either the volatility score or drawdown score doubled within the
    last SHOCK_WINDOW days, return SHOCK_MULTIPLIER (1.25). Otherwise 1.0.

    This is applied element-wise to produce a full Series that can be
    multiplied into the SRS or GSRI.
    """
    multipliers = pd.Series(1.0, index=v_scores.index)

    for scores in [v_scores, m_scores]:
        shifted = scores.shift(SHOCK_WINDOW)
        # Where the past value was > 5 (non-trivial) and current is double
        acceleration = (scores / shifted.replace(0, np.nan)).fillna(0)
        shock_mask = (shifted > 5) & (acceleration >= (1.0 + SHOCK_THRESHOLD))
        multipliers = multipliers.where(~shock_mask, SHOCK_MULTIPLIER)

    return multipliers


# =============================================================================
# SRS COMPONENT: V_t — Volatility Signal
# =============================================================================

def _compute_volatility_signal(
    returns: pd.DataFrame,
    window: int = DEFAULT_ROLLING_WINDOW,
) -> pd.Series:
    """
    Compute V_t: the rolling annualized volatility signal.

    For each day, this calculates the standard deviation of returns over
    the past `window` days, then annualizes it by multiplying by sqrt(252).
    The result is averaged across all assets to get one number per day.

    When V_t is high, it means prices across markets are swinging wildly —
    a sign of stress or panic.

    Parameters:
        returns: DataFrame of daily returns (one column per asset).
        window: Rolling window in trading days (default: 20 ≈ 1 month).

    Returns:
        A pandas Series of the cross-asset average annualized volatility per day.
    """
    # Rolling standard deviation, annualized.
    rolling_vol = returns.rolling(window=window).std() * np.sqrt(TRADING_DAYS_PER_YEAR)

    # Average across all assets for each day.
    avg_vol = rolling_vol.mean(axis=1)

    return avg_vol


# =============================================================================
# SRS COMPONENT: L_t — Liquidity Proxy (Amihud Illiquidity Ratio)
# =============================================================================

def _compute_liquidity_signal(
    prices: pd.DataFrame,
    volume: pd.DataFrame,
    returns: pd.DataFrame,
    window: int = DEFAULT_ROLLING_WINDOW,
) -> pd.Series:
    """
    Compute L_t: the Amihud Illiquidity Ratio as a liquidity stress signal.

    The Amihud ratio measures price impact per dollar traded:
        Amihud_i,t = |return_i,t| / dollar_volume_i,t

    Where dollar_volume = price × share_volume.

    A HIGH Amihud ratio means the asset is ILLIQUID (even small trades
    move the price a lot). During crises, liquidity dries up and the
    Amihud ratio spikes — you can see this clearly in 2008 and March 2020.

    Scaling:
        Raw Amihud values are extremely small (like 0.000000002).
        We multiply by 10^9 so values become readable (0.1 to 100 range).
        This scaling is applied CONSISTENTLY to each asset BEFORE
        aggregating, so comparisons across assets are fair.

    Parameters:
        prices: DataFrame of closing prices (one column per asset).
        volume: DataFrame of trading volume (one column per asset).
        returns: DataFrame of daily returns (one column per asset).
        window: Rolling window for smoothing.

    Returns:
        A pandas Series of the cross-asset average Amihud ratio (scaled).
    """
    # Find tickers that exist in all three DataFrames.
    common_tickers = list(
        set(prices.columns) & set(volume.columns) & set(returns.columns)
    )

    if not common_tickers:
        print("  WARNING: No common tickers between prices, volume, and returns for Amihud.")
        # Return a neutral series (ones) so downstream math doesn't break.
        return pd.Series(0.0, index=returns.index)

    amihud_per_asset = {}

    for ticker in common_tickers:
        # Dollar volume = price × number of shares traded.
        dollar_vol = prices[ticker].abs() * volume[ticker].abs()

        # Avoid division by zero: replace 0 dollar volume with NaN.
        dollar_vol = dollar_vol.replace(0, np.nan)

        # Amihud ratio = |daily return| / dollar volume.
        daily_amihud = returns[ticker].abs() / dollar_vol

        # Scale by 10^9 so the values are human-readable.
        # This scaling is applied PER ASSET before aggregation, ensuring
        # consistency across all assets.
        daily_amihud = daily_amihud * AMIHUD_SCALE_FACTOR

        # Smooth with a rolling mean to reduce noise.
        amihud_per_asset[ticker] = daily_amihud.rolling(window=window).mean()

    # Combine into a DataFrame and take the cross-asset average.
    amihud_df = pd.DataFrame(amihud_per_asset)
    avg_amihud = amihud_df.mean(axis=1)

    return avg_amihud


# =============================================================================
# SRS COMPONENT: C_t — Correlation Signal
# =============================================================================

def _compute_correlation_signal(
    returns: pd.DataFrame,
    window: int = DEFAULT_ROLLING_WINDOW,
) -> pd.Series:
    """
    Compute C_t: the rolling average off-diagonal correlation.

    For each day, this calculates the correlation matrix of returns over
    the past `window` days, then takes the average of the off-diagonal
    elements (i.e., the pairwise correlations between different assets).

    When C_t is high (close to +1), all assets are moving together.
    This is a classic crisis signal: diversification breaks down because
    investors sell everything at once ("risk-off" behavior).

    When C_t is low or negative, assets are moving independently,
    which is healthy for diversification.

    Parameters:
        returns: DataFrame of daily returns.
        window: Rolling window in trading days.

    Returns:
        A pandas Series of the average off-diagonal correlation per day.
    """
    n_assets = returns.shape[1]
    dates = returns.index
    corr_values = []

    if n_assets < 2:
        # Need at least 2 assets to compute correlation.
        return pd.Series(0.0, index=dates)

    for i in range(len(dates)):
        if i < window - 1:
            # Not enough data yet for a full window.
            corr_values.append(np.nan)
            continue

        # Get the returns window.
        window_data = returns.iloc[i - window + 1: i + 1]

        # Compute correlation matrix.
        corr_matrix = window_data.corr()

        # Extract off-diagonal elements (exclude the 1.0 diagonal).
        mask = ~np.eye(n_assets, dtype=bool)
        off_diag = corr_matrix.values[mask]

        # Take the mean of all pairwise correlations.
        if len(off_diag) > 0 and not np.all(np.isnan(off_diag)):
            avg_corr = np.nanmean(off_diag)
        else:
            avg_corr = np.nan

        corr_values.append(avg_corr)

    return pd.Series(corr_values, index=dates, name="correlation_signal")


# =============================================================================
# SRS COMPONENT: M_t — Drawdown / Stress Signal
# =============================================================================

def _compute_drawdown_signal(
    prices: pd.DataFrame,
    window: int = DEFAULT_ROLLING_WINDOW,
) -> pd.Series:
    """
    Compute M_t: the drawdown acceleration signal.

    This measures how quickly prices are falling from their recent peaks.
    It captures acute crash dynamics — the speed of the decline matters
    as much as the depth.

    How it works:
        1. For each asset, compute the rolling peak (highest price in window).
        2. Compute drawdown = (current price - peak) / peak.
        3. Compute drawdown acceleration = change in drawdown over 5 days.
           A rapidly increasing drawdown (more negative) means a crash is
           accelerating — this is the most dangerous condition.
        4. Average across all assets.
        5. Take the absolute value (we care about magnitude, not direction).

    Parameters:
        prices: DataFrame of closing prices.
        window: Rolling window for peak calculation.

    Returns:
        A pandas Series of the average drawdown acceleration per day.
    """
    accel_per_asset = {}

    for ticker in prices.columns:
        price = prices[ticker]

        # Rolling peak: highest price in the past `window` days.
        rolling_peak = price.rolling(window=window).max()

        # Drawdown from the rolling peak (will be 0 at peaks, negative during declines).
        drawdown = (price - rolling_peak) / rolling_peak

        # Drawdown acceleration: how much did the drawdown change over 5 days?
        # A value of -0.05 means the drawdown deepened by 5 percentage points
        # in just 5 days — that's a fast crash.
        acceleration = drawdown.diff(periods=5)

        # We care about the magnitude of acceleration (how fast things are getting worse).
        accel_per_asset[ticker] = acceleration.abs()

    accel_df = pd.DataFrame(accel_per_asset)
    avg_accel = accel_df.mean(axis=1)

    return avg_accel


# =============================================================================
# SRS: Combine V_t, L_t, C_t, M_t into a single score
# =============================================================================

def compute_srs_components(
    tickers: list = None,
    period: str = "2y",
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
) -> dict:
    """
    Compute all four SRS sub-signals as time series.

    This is the diagnostic function — use it to understand what is
    driving systemic risk at any point in time.

    Parameters:
        tickers: List of tickers. If None, uses SRX_CORE_TICKERS.
        period: Historical period ("1y", "2y", "5y").
        rolling_window: Window for rolling calculations.

    Returns:
        A dictionary with:
          "components": DataFrame with columns [date, V_t, L_t, C_t, M_t]
          "tickers_used": List of tickers that had data
          "error": Error message if something failed
    """
    try:
        if tickers is None:
            tickers = SRX_CORE_TICKERS

        tickers = [t.strip().upper() for t in tickers]

        # ---- Download all data ----
        prices = get_market_prices(tickers, period)
        if prices.empty:
            return {"error": "Could not download price data for SRS components."}

        returns = get_market_returns(tickers, period)
        if returns.empty:
            return {"error": "Could not download return data for SRS components."}

        volume = get_market_volume(tickers, period)
        # Volume might fail for some tickers (crypto volume can be unreliable).
        # If so, we still compute V_t, C_t, M_t and set L_t to neutral.

        available_tickers = list(returns.columns)

        # ---- Compute each sub-signal ----
        v_t = _compute_volatility_signal(returns, rolling_window)
        c_t = _compute_correlation_signal(returns, rolling_window)
        m_t = _compute_drawdown_signal(prices, rolling_window)

        if not volume.empty:
            l_t = _compute_liquidity_signal(prices, volume, returns, rolling_window)
        else:
            print("  WARNING: No volume data available. Liquidity signal set to neutral.")
            l_t = pd.Series(0.0, index=returns.index)

        # ---- Build the components DataFrame ----
        components = pd.DataFrame({
            "V_t": v_t,
            "L_t": l_t,
            "C_t": c_t,
            "M_t": m_t,
        }, index=returns.index)

        # Add date column.
        if hasattr(components.index, "strftime"):
            components["date"] = components.index.strftime("%Y-%m-%d")
        else:
            components["date"] = components.index.astype(str).str[:10]

        # Drop rows where signals haven't warmed up yet (NaN from rolling windows).
        components = components.dropna(subset=["V_t", "C_t", "M_t"])

        return {
            "components": components,
            "tickers_used": available_tickers,
        }

    except Exception as error:
        return {
            "error": (
                f"SRS component calculation failed: {error}\n"
                f"Check your internet connection and ticker symbols."
            )
        }


def compute_srs_series(
    tickers: list = None,
    period: str = "2y",
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
) -> dict:
    """
    Compute the full SRS (Systemic Risk Score) time series (0–100).

    SRS_t = f(V_t, L_t, C_t, M_t) where f is a non-linear weighting function.

    The non-linear scoring maps each raw signal to a 0–100 sub-score using
    calibration thresholds based on historical stress events:
      - V_t (volatility): 5% annualized = calm (0), 60% = crisis (100)
      - L_t (liquidity):   0 = liquid (0), 50 (scaled) = illiquid (100)
      - C_t (correlation): -0.2 = diversified (0), +0.8 = herding (100)
      - M_t (drawdown):    0% = stable (0), 5% acceleration = crash (100)

    Parameters:
        tickers: List of tickers. If None, uses SRX_CORE_TICKERS.
        period: Historical period.
        rolling_window: Window for rolling calculations.

    Returns:
        Dictionary with:
          "srs_series": DataFrame [date, srs, V_t_score, L_t_score, C_t_score, M_t_score]
          "current_srs": Most recent SRS value
          "tickers_used": Tickers with data
    """
    try:
        comp_result = compute_srs_components(tickers, period, rolling_window)

        if "error" in comp_result:
            return comp_result

        components = comp_result["components"]

        # ---- Score each sub-signal using the non-linear function ----
        # The thresholds (low, high) are calibrated so that:
        #   - Normal markets score 10–30
        #   - Stressed markets score 40–60
        #   - Crisis conditions score 70–100

        v_scores = components["V_t"].apply(
            lambda x: _nonlinear_score(x, low=0.05, high=0.60, exponent=1.5)
        )
        l_scores = components["L_t"].apply(
            lambda x: _nonlinear_score(x, low=0.0, high=50.0, exponent=1.3)
        )
        c_scores = components["C_t"].apply(
            lambda x: _nonlinear_score(x, low=-0.2, high=0.8, exponent=1.4)
        )
        m_scores = components["M_t"].apply(
            lambda x: _nonlinear_score(x, low=0.0, high=0.05, exponent=1.6)
        )

        # ---- Combine into SRS using calibrated weights ----
        srs = (
            SRS_WEIGHT_VOLATILITY * v_scores +
            SRS_WEIGHT_LIQUIDITY * l_scores +
            SRS_WEIGHT_CORRELATION * c_scores +
            SRS_WEIGHT_DRAWDOWN * m_scores
        )

        # ---- Apply Shock Multiplier ----
        # If volatility or drawdown doubled in 5 days, amplify by 1.25×.
        shock = _compute_shock_series(v_scores, m_scores)
        srs = srs * shock

        # Clamp to 0–100.
        srs = srs.clip(0, 100)

        # ---- Build output DataFrame ----
        srs_df = pd.DataFrame({
            "date": components["date"],
            "srs": srs.round(2),
            "V_t_score": v_scores.round(2),
            "L_t_score": l_scores.round(2),
            "C_t_score": c_scores.round(2),
            "M_t_score": m_scores.round(2),
            "shock_multiplier": shock,
            "V_t_raw": components["V_t"].round(6),
            "L_t_raw": components["L_t"].round(6),
            "C_t_raw": components["C_t"].round(6),
            "M_t_raw": components["M_t"].round(6),
        })

        current_srs = float(srs.iloc[-1]) if len(srs) > 0 else 0.0

        return {
            "srs_series": srs_df,
            "current_srs": round(current_srs, 2),
            "tickers_used": comp_result["tickers_used"],
        }

    except Exception as error:
        return {
            "error": (
                f"SRS series calculation failed: {error}\n"
                f"Check your internet connection and ticker symbols."
            )
        }


# =============================================================================
# GSRI: Global Systemic Risk Index
# =============================================================================

def compute_gsri_series(
    tickers: list = None,
    period: str = "2y",
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
) -> dict:
    """
    Compute the GSRI (Global Systemic Risk Index) time series (0–100).

    The GSRI combines asset-class-specific stress signals:
      1. Equity Volatility (25%):  Rolling vol of SPY
      2. Credit Stress (25%):      Rolling vol of HYG + HYG-TLT spread
      3. Treasury Volatility (15%): Rolling vol of TLT
      4. Crypto Volatility (10%):  Rolling vol of BTC-USD
      5. Cross-Asset Correlation (25%): Average off-diagonal correlation

    Parameters:
        tickers: List of tickers. If None, uses SRX_CORE_TICKERS.
        period: Historical period.
        rolling_window: Window for rolling calculations.

    Returns:
        Dictionary with:
          "gsri_series": DataFrame [date, gsri, equity_vol, credit_stress,
                                    treasury_vol, crypto_vol, cross_corr]
          "current_gsri": Most recent GSRI value
          "tickers_used": Tickers with data
    """
    try:
        if tickers is None:
            tickers = SRX_CORE_TICKERS

        tickers = [t.strip().upper() for t in tickers]

        # Download returns.
        returns = get_market_returns(tickers, period)
        if returns.empty:
            return {"error": "Could not download data for GSRI calculation."}

        available = list(returns.columns)
        if len(available) < 2:
            return {
                "error": (
                    f"Need at least 2 tickers with data for GSRI. "
                    f"Only got: {available}"
                )
            }

        # Ensure enough data for the rolling window.
        if len(returns) < rolling_window + 10:
            return {
                "error": (
                    f"Not enough data. Need at least {rolling_window + 10} days, "
                    f"but only have {len(returns)}. Try a longer period."
                )
            }

        # ---- 1. Equity Volatility ----
        # Use SPY if available, otherwise the first equity-like ticker.
        equity_ticker = "SPY" if "SPY" in available else available[0]
        equity_vol = (
            returns[equity_ticker].rolling(window=rolling_window).std()
            * np.sqrt(TRADING_DAYS_PER_YEAR)
        )
        equity_vol_score = equity_vol.apply(
            lambda x: _nonlinear_score(x, low=0.05, high=0.60, exponent=1.5)
        )

        # ---- 2. Credit Stress ----
        # Use HYG volatility + spread vs. TLT (flight to safety indicator).
        if "HYG" in available:
            credit_vol = (
                returns["HYG"].rolling(window=rolling_window).std()
                * np.sqrt(TRADING_DAYS_PER_YEAR)
            )
            credit_vol_score = credit_vol.apply(
                lambda x: _nonlinear_score(x, low=0.03, high=0.40, exponent=1.4)
            )

            # If TLT is also available, add a spread component.
            # When HYG falls and TLT rises, credit stress is high.
            if "TLT" in available:
                hyg_cum = (1 + returns["HYG"]).rolling(window=rolling_window).apply(
                    lambda x: x.prod() - 1, raw=True
                )
                tlt_cum = (1 + returns["TLT"]).rolling(window=rolling_window).apply(
                    lambda x: x.prod() - 1, raw=True
                )
                # Positive spread = TLT outperforming HYG = stress.
                spread = tlt_cum - hyg_cum
                spread_score = spread.apply(
                    lambda x: _nonlinear_score(x, low=-0.10, high=0.15, exponent=1.3)
                )
                # Blend: 60% vol-based, 40% spread-based.
                credit_stress_score = 0.60 * credit_vol_score + 0.40 * spread_score
            else:
                credit_stress_score = credit_vol_score
        else:
            # No credit data — use a neutral 50.
            credit_stress_score = pd.Series(50.0, index=returns.index)

        # ---- 3. Treasury Volatility ----
        if "TLT" in available:
            treasury_vol = (
                returns["TLT"].rolling(window=rolling_window).std()
                * np.sqrt(TRADING_DAYS_PER_YEAR)
            )
            treasury_vol_score = treasury_vol.apply(
                lambda x: _nonlinear_score(x, low=0.03, high=0.30, exponent=1.3)
            )
        else:
            treasury_vol_score = pd.Series(50.0, index=returns.index)

        # ---- 4. Crypto Volatility ----
        if "BTC-USD" in available:
            crypto_vol = (
                returns["BTC-USD"].rolling(window=rolling_window).std()
                * np.sqrt(TRADING_DAYS_PER_YEAR)
            )
            crypto_vol_score = crypto_vol.apply(
                lambda x: _nonlinear_score(x, low=0.20, high=1.20, exponent=1.2)
            )
        else:
            crypto_vol_score = pd.Series(50.0, index=returns.index)

        # ---- 5. Cross-Asset Correlation ----
        corr_signal = _compute_correlation_signal(returns, rolling_window)
        cross_corr_score = corr_signal.apply(
            lambda x: _nonlinear_score(x, low=-0.2, high=0.8, exponent=1.4)
        )

        # ---- Combine into GSRI ----
        gsri = (
            GSRI_WEIGHT_EQUITY_VOL * equity_vol_score +
            GSRI_WEIGHT_CREDIT_STRESS * credit_stress_score +
            GSRI_WEIGHT_TREASURY_VOL * treasury_vol_score +
            GSRI_WEIGHT_CRYPTO_VOL * crypto_vol_score +
            GSRI_WEIGHT_CROSS_CORR * cross_corr_score
        )

        # ---- Apply Shock Multiplier ----
        # Uses equity vol (primary risk signal) and cross-correlation (herding).
        shock = _compute_shock_series(equity_vol_score, cross_corr_score)
        gsri = gsri * shock

        gsri = gsri.clip(0, 100)

        # ---- Build output DataFrame ----
        # Format dates safely.
        if hasattr(returns.index, "strftime"):
            dates = returns.index.strftime("%Y-%m-%d")
        else:
            dates = returns.index.astype(str).str[:10]

        gsri_df = pd.DataFrame({
            "date": dates,
            "gsri": gsri.round(2),
            "equity_vol": equity_vol_score.round(2),
            "credit_stress": credit_stress_score.round(2),
            "treasury_vol": treasury_vol_score.round(2),
            "crypto_vol": crypto_vol_score.round(2),
            "cross_corr": cross_corr_score.round(2),
            "shock_multiplier": shock,
        })

        # Drop warm-up NaN rows.
        gsri_df = gsri_df.dropna(subset=["gsri"])

        current_gsri = float(gsri_df["gsri"].iloc[-1]) if len(gsri_df) > 0 else 0.0

        return {
            "gsri_series": gsri_df,
            "current_gsri": round(current_gsri, 2),
            "tickers_used": available,
        }

    except Exception as error:
        return {
            "error": (
                f"GSRI series calculation failed: {error}\n"
                f"Check your internet connection and ticker symbols."
            )
        }


# =============================================================================
# API FUNCTION: calculate_gsri (backward compatible)
# =============================================================================

def calculate_gsri(
    tickers: list = None,
    period: str = "2y",
    rolling_window: int = 60,
) -> dict:
    """
    Calculate the Global Systemic Risk Index — API-ready output.

    This is the main function used by:
      - backend/main.py (the /gsri endpoint)
      - backend/pricing_engine.py (GSRI-adjusted pricing)
      - frontend/dashboard.py (renders charts and metrics)

    It returns the same keys as the original version for full backward
    compatibility, plus new SRS data.

    Parameters:
        tickers: List of tickers. If None, uses DEFAULT_TICKERS for the GSRI
                 and SRX_CORE_TICKERS for the SRS.
        period:  Historical period ("1y", "2y", "5y").
        rolling_window: Rolling window in trading days. The API default is 60
                        (≈ 3 months), which gives smoother results. The internal
                        sub-signals use 20-day windows for finer resolution.

    Returns:
        A dictionary with:
          current_gsri:  Float (0–100) — the most recent GSRI value
          risk_level:    String — human-readable risk level
          tickers_used:  List of tickers that had data
          rolling_window_days: Int — the window used
          sub_scores:    Dict of latest sub-component scores (for dashboard progress bars)
          gsri_history:  List of dicts [{date, gsri, correlation, volatility, credit, tail}, ...]
                         (uses the same key names as the old version for dashboard charts)
          srs_current:   Float (0–100) — the current SRS value (NEW)
          srs_components: Dict of latest SRS sub-signal scores (NEW)
    """
    try:
        if tickers is None:
            tickers = DEFAULT_TICKERS

        # ---- Compute GSRI ----
        # Use a 20-day sub-window for the signals, but the `rolling_window` param
        # from the API controls an additional smoothing pass on the final GSRI.
        gsri_result = compute_gsri_series(tickers, period, rolling_window=DEFAULT_ROLLING_WINDOW)

        if "error" in gsri_result:
            return gsri_result

        gsri_df = gsri_result["gsri_series"]

        # Apply additional smoothing if the API requested a longer window.
        # This makes the GSRI chart less noisy at the cost of being slower to react.
        if rolling_window > DEFAULT_ROLLING_WINDOW and len(gsri_df) > rolling_window:
            smoothing_window = max(2, rolling_window // DEFAULT_ROLLING_WINDOW)
            for col in ["gsri", "equity_vol", "credit_stress", "treasury_vol",
                        "crypto_vol", "cross_corr"]:
                if col in gsri_df.columns:
                    gsri_df[col] = gsri_df[col].rolling(
                        window=smoothing_window, min_periods=1
                    ).mean().round(2)

        # ---- Current GSRI ----
        current_gsri = float(gsri_df["gsri"].iloc[-1]) if len(gsri_df) > 0 else 0.0

        # ---- Risk level ----
        if current_gsri < 20:
            risk_level = "Low — Markets calm"
        elif current_gsri < 40:
            risk_level = "Elevated — Some stress signals"
        elif current_gsri < 60:
            risk_level = "High — Significant stress"
        elif current_gsri < 80:
            risk_level = "Severe — Major stress event"
        else:
            risk_level = "Critical — Systemic crisis conditions"

        # ---- Sub-scores for dashboard progress bars ----
        # The dashboard iterates sub_scores.items() and displays each as a bar.
        latest = gsri_df.iloc[-1] if len(gsri_df) > 0 else {}
        sub_scores = {
            "correlation": float(latest.get("cross_corr", 0)),
            "volatility": float(latest.get("equity_vol", 0)),
            "credit_stress": float(latest.get("credit_stress", 0)),
            "tail": float(latest.get("treasury_vol", 0)),
        }

        # ---- GSRI history for dashboard charts ----
        # The dashboard expects these column names: date, gsri, correlation,
        # volatility, credit, tail.
        gsri_history = []
        for _, row in gsri_df.iterrows():
            gsri_history.append({
                "date": row["date"],
                "gsri": float(row.get("gsri", 0)),
                "correlation": float(row.get("cross_corr", 0)),
                "volatility": float(row.get("equity_vol", 0)),
                "credit": float(row.get("credit_stress", 0)),
                "tail": float(row.get("treasury_vol", 0)),
                "shock": float(row.get("shock_multiplier", 1.0)),
            })

        # ---- Also compute SRS for additional insight ----
        srs_result = compute_srs_series(period=period, rolling_window=DEFAULT_ROLLING_WINDOW)
        srs_current = 0.0
        srs_components = {}
        if "error" not in srs_result:
            srs_current = srs_result["current_srs"]
            srs_df = srs_result["srs_series"]
            if len(srs_df) > 0:
                last_srs = srs_df.iloc[-1]
                srs_components = {
                    "V_t_volatility": float(last_srs.get("V_t_score", 0)),
                    "L_t_liquidity": float(last_srs.get("L_t_score", 0)),
                    "C_t_correlation": float(last_srs.get("C_t_score", 0)),
                    "M_t_drawdown": float(last_srs.get("M_t_score", 0)),
                }

        return {
            # ---- Backward-compatible keys (used by dashboard, pricing, gating) ----
            "current_gsri": round(current_gsri, 2),
            "risk_level": risk_level,
            "tickers_used": gsri_result["tickers_used"],
            "rolling_window_days": rolling_window,
            "sub_scores": sub_scores,
            "gsri_history": gsri_history,
            # ---- New SRS keys ----
            "srs_current": round(srs_current, 2),
            "srs_components": srs_components,
            # ---- Shock Multiplier status ----
            "shock_active": bool(gsri_df["shock_multiplier"].iloc[-1] > 1.0) if "shock_multiplier" in gsri_df.columns and len(gsri_df) > 0 else False,
        }

    except Exception as error:
        return {
            "error": (
                f"GSRI calculation failed: {error}\n"
                f"Make sure you have internet access and valid ticker symbols."
            )
        }


# =============================================================================
# EXAMPLE USAGE — Run this file directly to test it
# =============================================================================

if __name__ == "__main__":
    """
    Run this file directly to test all GSRI engine functions:
        cd ~/Desktop/srx-platform
        source venv/bin/activate
        python3 -m backend.gsri_engine
    """

    print("=" * 70)
    print("SRX PLATFORM — GSRI Engine Test")
    print("=" * 70)

    # Use a shorter period for faster testing.
    test_period = "1y"
    all_passed = True

    # ---- Test 1: SRS Components ----
    print("\n--- TEST 1: compute_srs_components() ---\n")
    comp_result = compute_srs_components(period=test_period)

    if "error" in comp_result:
        print(f"  ERROR: {comp_result['error']}")
        all_passed = False
    else:
        comp_df = comp_result["components"]
        print(f"  Tickers used: {comp_result['tickers_used']}")
        print(f"  Shape: {comp_df.shape[0]} rows x {comp_df.shape[1]} columns")
        print(f"\n  Latest values:")
        last = comp_df.iloc[-1]
        print(f"    V_t (Volatility):   {last['V_t']:.6f}")
        print(f"    L_t (Liquidity):    {last['L_t']:.6f}")
        print(f"    C_t (Correlation):  {last['C_t']:.6f}")
        print(f"    M_t (Drawdown):     {last['M_t']:.6f}")

    # ---- Test 2: SRS Series ----
    print("\n\n--- TEST 2: compute_srs_series() ---\n")
    srs_result = compute_srs_series(period=test_period)

    if "error" in srs_result:
        print(f"  ERROR: {srs_result['error']}")
        all_passed = False
    else:
        srs_df = srs_result["srs_series"]
        print(f"  Current SRS: {srs_result['current_srs']:.2f} / 100")
        print(f"  Shape: {srs_df.shape[0]} rows")
        print(f"\n  Last 5 rows:")
        print(srs_df[["date", "srs", "V_t_score", "L_t_score", "C_t_score", "M_t_score"]]
              .tail().to_string(index=False))
        print(f"\n  SRS statistics:")
        print(f"    Mean:   {srs_df['srs'].mean():.2f}")
        print(f"    Min:    {srs_df['srs'].min():.2f}")
        print(f"    Max:    {srs_df['srs'].max():.2f}")
        print(f"    Median: {srs_df['srs'].median():.2f}")

    # ---- Test 3: GSRI Series ----
    print("\n\n--- TEST 3: compute_gsri_series() ---\n")
    gsri_series_result = compute_gsri_series(period=test_period)

    if "error" in gsri_series_result:
        print(f"  ERROR: {gsri_series_result['error']}")
        all_passed = False
    else:
        gsri_df = gsri_series_result["gsri_series"]
        print(f"  Current GSRI: {gsri_series_result['current_gsri']:.2f} / 100")
        print(f"  Shape: {gsri_df.shape[0]} rows")
        print(f"\n  Last 5 rows:")
        print(gsri_df.tail().to_string(index=False))

    # ---- Test 4: API function (calculate_gsri) ----
    print("\n\n--- TEST 4: calculate_gsri() (API output) ---\n")
    api_result = calculate_gsri(period=test_period)

    if "error" in api_result:
        print(f"  ERROR: {api_result['error']}")
        all_passed = False
    else:
        print(f"  Current GSRI: {api_result['current_gsri']:.2f} / 100")
        print(f"  Risk Level:   {api_result['risk_level']}")
        print(f"  SRS Current:  {api_result['srs_current']:.2f} / 100")
        print(f"\n  Sub-scores (for dashboard):")
        for name, val in api_result["sub_scores"].items():
            print(f"    {name}: {val:.2f}")
        print(f"\n  SRS Components:")
        for name, val in api_result["srs_components"].items():
            print(f"    {name}: {val:.2f}")
        print(f"\n  History length: {len(api_result['gsri_history'])} data points")
        if api_result["gsri_history"]:
            first = api_result["gsri_history"][0]
            last = api_result["gsri_history"][-1]
            print(f"  First entry: {first}")
            print(f"  Last entry:  {last}")

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    if all_passed:
        print("STATUS: All tests passed. GSRI engine is working.")
    else:
        print("STATUS: Some tests failed. Check error messages above.")
    print("=" * 70)
