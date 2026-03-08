"""
portfolio_engine.py — Portfolio Risk Index (PRI), Systemic Risk Score (SRS),
                       and Stress Testing for the SRX Platform.

FILE LOCATION: Save this file as:
    ~/Desktop/srx-platform/backend/portfolio_engine.py

WHAT THIS MODULE DOES:
    1. Accepts a portfolio as a dictionary of ticker → weight mappings
    2. Validates that weights are positive and sum to 1.0 (normalizes if not)
    3. Pulls daily asset returns from market_data.py
    4. Computes weighted daily portfolio returns
    5. Builds a PRI time series starting from a base value of 100
    6. Computes key risk metrics:
       - Annualized volatility (how wild the swings are)
       - Cumulative return (total gain or loss)
       - Maximum drawdown (worst peak-to-trough loss)
       - Rolling volatility (how risk changes over time)
    7. Calculates a PRI composite risk score (0-100)
    8. Calculates Systemic Risk Scores (SRS) per asset
    9. Runs stress test scenarios (2008 crisis, COVID crash, etc.)

INPUT FORMAT:
    Portfolio is a dictionary like:
    {
        "SPY": 0.40,
        "HYG": 0.20,
        "TLT": 0.20,
        "GLD": 0.10,
        "BTC-USD": 0.10
    }

MAIN FUNCTIONS:
    validate_weights(portfolio)    → Checks and normalizes portfolio weights
    compute_max_drawdown(series)   → Calculates max drawdown from any price series
    build_pri_timeseries(portfolio)→ Full PRI analysis with time series and metrics
    calculate_pri(tickers, weights)→ PRI composite score (used by the API)
    calculate_srs(tickers)         → Systemic Risk Scores per asset
    run_stress_test(tickers, ...)  → Stress scenario simulation
"""

import numpy as np
import pandas as pd
import sys
import os

# Add the project root to the Python path so we can import from data/.
# os.path.dirname(__file__) gives us the "backend/" folder.
# ".." goes up one level to the project root "srx-platform/".
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from data.market_data import get_returns, get_close_prices


# =============================================================================
# CONSTANTS
# =============================================================================

# Number of trading days in a year (used to convert daily stats to annual).
TRADING_DAYS_PER_YEAR = 252

# Default rolling window for rolling volatility (in trading days).
# 21 trading days ≈ 1 calendar month.
ROLLING_WINDOW_DAYS = 21

# Base value for the PRI index time series.
# The index starts at 100 and goes up or down from there, just like
# a stock index. If it's at 105, the portfolio gained 5%. At 92, it lost 8%.
PRI_BASE_VALUE = 100.0


# =============================================================================
# WEIGHT VALIDATION
# =============================================================================

def validate_weights(portfolio: dict) -> dict:
    """
    Validate and normalize portfolio weights.

    This function checks that:
      1. The portfolio is not empty
      2. All weights are positive numbers
      3. Weights sum to 1.0 (normalizes them if they don't)
      4. All ticker symbols are uppercase strings

    Parameters:
        portfolio: A dictionary mapping ticker symbols to weights.
                   Example: {"SPY": 0.40, "TLT": 0.30, "GLD": 0.30}

    Returns:
        A dictionary with:
          "valid": True/False — whether the portfolio is usable
          "portfolio": The cleaned and normalized portfolio dictionary
          "tickers": List of uppercase ticker symbols
          "weights": numpy array of normalized weights
          "warnings": List of any warnings (e.g., "Weights were normalized")
          "error": Error message if the portfolio is invalid
    """
    warnings = []

    # ---- Check 1: Portfolio is not empty ----
    if not portfolio or len(portfolio) == 0:
        return {
            "valid": False,
            "error": (
                "Portfolio is empty. Please provide at least one ticker and weight.\n"
                "Example: {\"SPY\": 0.60, \"TLT\": 0.40}"
            ),
        }

    # ---- Check 2: Standardize ticker symbols to uppercase ----
    # This prevents bugs where "spy" and "SPY" would be treated as different assets.
    cleaned = {}
    for ticker, weight in portfolio.items():
        upper_ticker = ticker.strip().upper()

        # Make sure weight is a number.
        try:
            weight = float(weight)
        except (ValueError, TypeError):
            return {
                "valid": False,
                "error": (
                    f"Weight for '{ticker}' is not a valid number: {weight}\n"
                    f"Weights must be positive numbers like 0.25 or 0.5."
                ),
            }

        cleaned[upper_ticker] = weight

    # ---- Check 3: All weights must be positive ----
    for ticker, weight in cleaned.items():
        if weight <= 0:
            return {
                "valid": False,
                "error": (
                    f"Weight for '{ticker}' is {weight}, but weights must be positive.\n"
                    f"If you don't want to include {ticker}, remove it from the portfolio."
                ),
            }

    # ---- Check 4: Normalize weights to sum to 1.0 ----
    tickers = list(cleaned.keys())
    raw_weights = np.array([cleaned[t] for t in tickers])
    weight_sum = raw_weights.sum()

    if weight_sum <= 0:
        return {
            "valid": False,
            "error": "All weights are zero or negative. At least one weight must be positive.",
        }

    # Check if weights already sum to 1.0 (with a small tolerance for rounding).
    if abs(weight_sum - 1.0) > 0.001:
        warnings.append(
            f"Weights summed to {weight_sum:.4f}, not 1.0. "
            f"They have been normalized (each divided by {weight_sum:.4f})."
        )

    # Normalize so they sum to exactly 1.0.
    normalized_weights = raw_weights / weight_sum

    # Rebuild the portfolio dictionary with normalized weights.
    normalized_portfolio = {
        ticker: round(float(w), 6) for ticker, w in zip(tickers, normalized_weights)
    }

    return {
        "valid": True,
        "portfolio": normalized_portfolio,
        "tickers": tickers,
        "weights": normalized_weights,
        "warnings": warnings,
    }


# =============================================================================
# MAX DRAWDOWN
# =============================================================================

def compute_max_drawdown(price_series: pd.Series) -> dict:
    """
    Calculate the maximum drawdown of a price or index series.

    What is a drawdown?
        A drawdown measures the decline from a historical peak.
        If a portfolio hit $120 at its peak, then fell to $90, the drawdown
        from that peak is ($120 - $90) / $120 = 25%.

    What is MAX drawdown?
        The largest peak-to-trough decline over the entire time period.
        This tells you: "What was the worst loss you would have experienced
        if you bought at the worst possible time and sold at the worst?"

    Parameters:
        price_series: A pandas Series of prices or index values over time.
                      Example: the PRI time series starting at 100.

    Returns:
        A dictionary with:
          "max_drawdown_pct": The worst drawdown as a negative percentage
          "peak_date": Date of the peak before the worst drawdown
          "trough_date": Date of the bottom of the worst drawdown
          "peak_value": The price/index value at the peak
          "trough_value": The price/index value at the trough
          "recovery_date": Date when the index recovered to the peak (or None)
    """
    try:
        if price_series.empty or len(price_series) < 2:
            return {
                "max_drawdown_pct": 0.0,
                "peak_date": None,
                "trough_date": None,
                "peak_value": None,
                "trough_value": None,
                "recovery_date": None,
            }

        # Step 1: Calculate the running maximum (the highest value seen so far).
        # cummax() gives us, for each date, the highest value from the start up to that date.
        running_max = price_series.cummax()

        # Step 2: Calculate drawdown at each point.
        # Drawdown = (current value - peak value) / peak value
        # This will be 0 at peaks and negative during declines.
        drawdown = (price_series - running_max) / running_max

        # Step 3: Find the worst (most negative) drawdown.
        max_drawdown = drawdown.min()
        trough_idx = drawdown.idxmin()

        # Step 4: Find the peak that preceded this trough.
        # The peak is the date of the running maximum at the trough point.
        peak_value_at_trough = running_max.loc[trough_idx]
        # Find the first date where the price was at that peak.
        peak_candidates = price_series.loc[:trough_idx]
        peak_idx = peak_candidates[peak_candidates == peak_value_at_trough].index[0]

        # Step 5: Check if the series recovered to the peak after the trough.
        post_trough = price_series.loc[trough_idx:]
        recovered = post_trough[post_trough >= peak_value_at_trough]
        recovery_date = None
        if len(recovered) > 0:
            recovery_date = recovered.index[0]
            # Format the date safely.
            if hasattr(recovery_date, "strftime"):
                recovery_date = recovery_date.strftime("%Y-%m-%d")
            else:
                recovery_date = str(recovery_date)[:10]

        # Format dates safely (handles both datetime and string indexes).
        def safe_date(d):
            if hasattr(d, "strftime"):
                return d.strftime("%Y-%m-%d")
            return str(d)[:10]

        return {
            "max_drawdown_pct": round(float(max_drawdown) * 100, 2),
            "peak_date": safe_date(peak_idx),
            "trough_date": safe_date(trough_idx),
            "peak_value": round(float(peak_value_at_trough), 4),
            "trough_value": round(float(price_series.loc[trough_idx]), 4),
            "recovery_date": recovery_date,
        }

    except Exception as error:
        print(
            f"  WARNING: Max drawdown calculation encountered an issue: {error}\n"
            f"  Returning zero drawdown. This usually means the price series is too short."
        )
        return {
            "max_drawdown_pct": 0.0,
            "peak_date": None,
            "trough_date": None,
            "peak_value": None,
            "trough_value": None,
            "recovery_date": None,
        }


# =============================================================================
# PRI TIME SERIES BUILDER
# =============================================================================

def build_pri_timeseries(
    portfolio: dict,
    period: str = "2y",
    rolling_window: int = ROLLING_WINDOW_DAYS,
) -> dict:
    """
    Build a complete Portfolio Risk Index (PRI) analysis with time series.

    This is the most comprehensive portfolio analysis function. It:
      1. Validates the portfolio weights
      2. Downloads returns for all tickers
      3. Computes weighted daily portfolio returns
      4. Builds a PRI index starting at 100
      5. Computes rolling volatility
      6. Calculates summary metrics (annualized vol, cumulative return, max drawdown)

    Parameters:
        portfolio: Dictionary of ticker → weight mappings.
                   Example: {"SPY": 0.40, "HYG": 0.20, "TLT": 0.20,
                             "GLD": 0.10, "BTC-USD": 0.10}
        period: Historical period ("1y", "2y", "5y").
        rolling_window: Number of trading days for rolling volatility.
                        21 days ≈ 1 month. 63 days ≈ 3 months.

    Returns:
        A dictionary with:
          "pri_series": DataFrame with columns [date, pri, daily_return,
                        rolling_vol_annual] — the full time series
          "summary": Dictionary of summary metrics
          "portfolio": The validated and normalized portfolio
          "error": Error message if something went wrong (only present on failure)
    """
    try:
        # ---- Step 1: Validate the portfolio ----
        validation = validate_weights(portfolio)

        if not validation["valid"]:
            return {"error": validation["error"]}

        tickers = validation["tickers"]
        weights = validation["weights"]
        clean_portfolio = validation["portfolio"]

        # Print any warnings (e.g., weights were normalized).
        for warning in validation.get("warnings", []):
            print(f"  WARNING: {warning}")

        # ---- Step 2: Download returns ----
        print(f"\n  Building PRI for portfolio: {clean_portfolio}")
        returns = get_returns(tickers, period)

        if returns.empty:
            return {
                "error": (
                    "Could not download market data for the portfolio.\n"
                    "Check your internet connection and ticker symbols."
                )
            }

        # Check which tickers we actually got data for.
        available_tickers = [t for t in tickers if t in returns.columns]
        missing_tickers = [t for t in tickers if t not in returns.columns]

        if len(available_tickers) == 0:
            return {
                "error": (
                    f"None of the tickers returned data: {tickers}\n"
                    "Check that these are valid ticker symbols on finance.yahoo.com."
                )
            }

        if missing_tickers:
            print(
                f"  WARNING: No data for {missing_tickers}. "
                f"Proceeding with {available_tickers} and re-normalizing weights."
            )
            # Re-index and re-normalize weights for available tickers only.
            idx = [tickers.index(t) for t in available_tickers]
            weights = np.array([weights[i] for i in idx])
            weights = weights / weights.sum()
            tickers = available_tickers
            clean_portfolio = {
                t: round(float(w), 6) for t, w in zip(tickers, weights)
            }

        # Keep only the columns we have weights for.
        returns = returns[tickers]

        # ---- Step 3: Compute weighted daily portfolio returns ----
        # For each day: portfolio_return = sum(weight_i * return_i)
        # np.dot does this multiplication and sum in one step.
        portfolio_returns = returns.dot(weights)

        # Name the series so it shows up nicely in DataFrames.
        portfolio_returns.name = "daily_return"

        # ---- Step 4: Build the PRI index starting at 100 ----
        # The PRI index works like a stock price index:
        #   Day 0: PRI = 100
        #   Day 1: PRI = 100 * (1 + return_day1)
        #   Day 2: PRI = Day1_value * (1 + return_day2)
        #   ... and so on (cumulative product).
        pri_values = PRI_BASE_VALUE * (1 + portfolio_returns).cumprod()
        pri_values.name = "pri"

        # ---- Step 5: Compute rolling volatility ----
        # Rolling volatility = standard deviation of returns over a window,
        # annualized by multiplying by sqrt(252).
        # This shows how risk changes over time.
        rolling_vol = (
            portfolio_returns.rolling(window=rolling_window).std()
            * np.sqrt(TRADING_DAYS_PER_YEAR)
        )
        rolling_vol.name = "rolling_vol_annual"

        # ---- Step 6: Build the output DataFrame ----
        pri_df = pd.DataFrame({
            "pri": pri_values,
            "daily_return": portfolio_returns,
            "rolling_vol_annual": rolling_vol,
        })

        # Add a clean date column (for JSON/API compatibility).
        if hasattr(pri_df.index, "strftime"):
            pri_df["date"] = pri_df.index.strftime("%Y-%m-%d")
        else:
            pri_df["date"] = pri_df.index.astype(str).str[:10]

        # Reorder columns for readability.
        pri_df = pri_df[["date", "pri", "daily_return", "rolling_vol_annual"]]

        # ---- Step 7: Compute summary metrics ----

        # Annualized volatility: daily std dev × sqrt(252).
        annualized_vol = portfolio_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)

        # Cumulative return: how much the portfolio gained or lost total.
        # If PRI went from 100 to 115, cumulative return = +15%.
        final_pri = pri_values.iloc[-1]
        cumulative_return = (final_pri / PRI_BASE_VALUE) - 1.0

        # Annualized return: what the yearly average return would be.
        num_trading_days = len(portfolio_returns)
        if num_trading_days > 0:
            annualized_return = (
                (1 + cumulative_return) ** (TRADING_DAYS_PER_YEAR / num_trading_days) - 1
            )
        else:
            annualized_return = 0.0

        # Sharpe ratio (simplified, assuming risk-free rate ≈ 0 for simplicity).
        # Sharpe = annualized_return / annualized_volatility.
        # Higher is better. Above 1.0 is generally considered good.
        if annualized_vol > 0:
            sharpe_ratio = annualized_return / annualized_vol
        else:
            sharpe_ratio = 0.0

        # Max drawdown.
        drawdown_info = compute_max_drawdown(pri_values)

        # Current rolling volatility (most recent value).
        current_rolling_vol = rolling_vol.dropna()
        if not current_rolling_vol.empty:
            current_vol = float(current_rolling_vol.iloc[-1])
        else:
            current_vol = float(annualized_vol)

        summary = {
            "annualized_volatility_pct": round(float(annualized_vol) * 100, 2),
            "cumulative_return_pct": round(float(cumulative_return) * 100, 2),
            "annualized_return_pct": round(float(annualized_return) * 100, 2),
            "sharpe_ratio": round(float(sharpe_ratio), 4),
            "max_drawdown_pct": drawdown_info["max_drawdown_pct"],
            "max_drawdown_peak_date": drawdown_info["peak_date"],
            "max_drawdown_trough_date": drawdown_info["trough_date"],
            "max_drawdown_recovery_date": drawdown_info["recovery_date"],
            "current_rolling_vol_pct": round(current_vol * 100, 2),
            "pri_start_value": PRI_BASE_VALUE,
            "pri_end_value": round(float(final_pri), 4),
            "total_trading_days": num_trading_days,
            "start_date": pri_df["date"].iloc[0],
            "end_date": pri_df["date"].iloc[-1],
        }

        return {
            "pri_series": pri_df,
            "summary": summary,
            "portfolio": clean_portfolio,
        }

    except Exception as error:
        return {
            "error": (
                f"PRI time series calculation failed: {error}\n"
                f"\n"
                f"Possible fixes:\n"
                f"  1. Check that all ticker symbols are valid\n"
                f"  2. Check your internet connection\n"
                f"  3. Try a shorter period (e.g., '1y')\n"
                f"  4. Make sure the portfolio dictionary is formatted correctly\n"
                f"     Example: {{\"SPY\": 0.60, \"TLT\": 0.40}}"
            )
        }


# =============================================================================
# PRI COMPOSITE SCORE (used by the API and dashboard)
# =============================================================================

def calculate_pri(
    tickers: list,
    weights: list = None,
    period: str = "2y",
) -> dict:
    """
    Calculate the Portfolio Risk Index (PRI) composite score.

    The PRI is a single number from 0 to 100 that represents overall
    portfolio risk. It combines four sub-scores:

      1. Volatility Score (35% weight):
         How much do prices swing day to day?
         Based on annualized portfolio volatility.

      2. Correlation Score (25% weight):
         Do all holdings move together? High correlation = poor diversification.

      3. Concentration Score (15% weight):
         Is the portfolio too concentrated in a few assets?
         Uses the Herfindahl-Hirschman Index (HHI).

      4. Tail Risk Score (25% weight):
         How bad are the worst-case daily losses?
         Based on the 5th percentile of daily returns (Value at Risk).

    Risk levels:
        0-20:   Very Low
        20-40:  Low
        40-60:  Moderate
        60-80:  High
        80-100: Extreme

    Parameters:
        tickers: List of ticker symbols, e.g. ["SPY", "TLT", "GLD"]
        weights: Portfolio weights (must sum to 1.0). If None, equal weight.
        period:  Historical period to analyze ("1y", "2y", "5y").

    Returns:
        A dictionary with the PRI score, sub-scores, and portfolio details.
        Also includes the full time series summary from build_pri_timeseries().
    """
    try:
        # ---- Validate inputs ----
        if not tickers or len(tickers) == 0:
            return {"error": "No tickers provided. Please provide at least one ticker symbol."}

        # Standardize tickers to uppercase.
        tickers = [t.strip().upper() for t in tickers]

        # If no weights given, use equal weights.
        if weights is None:
            weights = [1.0 / len(tickers)] * len(tickers)

        # Make sure weights and tickers match in length.
        if len(weights) != len(tickers):
            return {
                "error": (
                    f"Mismatch: you gave {len(tickers)} tickers but {len(weights)} weights. "
                    f"These must be the same length."
                )
            }

        # Build a portfolio dictionary for validation.
        portfolio_dict = {t: w for t, w in zip(tickers, weights)}
        validation = validate_weights(portfolio_dict)

        if not validation["valid"]:
            return {"error": validation["error"]}

        tickers = validation["tickers"]
        weights = validation["weights"]

        # ---- Download return data ----
        returns = get_returns(tickers, period)

        if returns.empty:
            return {"error": "Could not download market data. Check your internet and ticker symbols."}

        # Only keep tickers that we actually got data for.
        available = [t for t in tickers if t in returns.columns]
        if len(available) == 0:
            return {"error": "None of the ticker symbols returned valid data."}

        if len(available) < len(tickers):
            missing = set(tickers) - set(available)
            print(f"  WARNING: No data for {missing}. Proceeding with {available}.")
            # Re-index weights to match available tickers.
            idx = [tickers.index(t) for t in available]
            weights = np.array([weights[i] for i in idx])
            weights = weights / weights.sum()
            tickers = available

        returns = returns[tickers]

        # ---- 1. Volatility Score (0-100) ----
        # Annualized portfolio volatility using the covariance matrix.
        cov_matrix = returns.cov() * TRADING_DAYS_PER_YEAR
        portfolio_variance = np.dot(weights, np.dot(cov_matrix.values, weights))
        portfolio_volatility = np.sqrt(max(portfolio_variance, 0))

        # Map volatility to a 0-100 score.
        # 0% vol → 0 score, 60%+ vol → 100 score.
        volatility_score = min(100.0, (portfolio_volatility / 0.60) * 100)

        # ---- 2. Correlation Score (0-100) ----
        # Average pairwise correlation between all holdings.
        corr_matrix = returns.corr()
        if len(tickers) > 1:
            upper_triangle = np.triu(corr_matrix.values, k=1)
            mask = np.triu(np.ones_like(corr_matrix.values, dtype=bool), k=1)
            avg_correlation = upper_triangle[mask].mean()
            # Map: -1 correlation → 0, +1 correlation → 100.
            correlation_score = max(0.0, min(100.0, (avg_correlation + 1) / 2 * 100))
        else:
            correlation_score = 0.0

        # ---- 3. Concentration Score (0-100) ----
        # Herfindahl-Hirschman Index (HHI).
        hhi = np.sum(weights ** 2)
        n = len(tickers)
        if n > 1:
            min_hhi = 1.0 / n
            concentration_score = (hhi - min_hhi) / (1.0 - min_hhi) * 100
        else:
            concentration_score = 100.0
        concentration_score = max(0.0, min(100.0, concentration_score))

        # ---- 4. Tail Risk Score (0-100) ----
        # 5th percentile of daily portfolio returns (Value at Risk).
        portfolio_returns = returns.dot(weights)
        var_5 = np.percentile(portfolio_returns, 5)
        tail_risk_score = min(100.0, (abs(var_5) / 0.05) * 100)

        # ---- Combine into PRI composite score ----
        pri = (
            0.35 * volatility_score +
            0.25 * correlation_score +
            0.15 * concentration_score +
            0.25 * tail_risk_score
        )
        pri = round(max(0.0, min(100.0, pri)), 2)

        # Risk level label.
        if pri < 20:
            risk_level = "Very Low"
        elif pri < 40:
            risk_level = "Low"
        elif pri < 60:
            risk_level = "Moderate"
        elif pri < 80:
            risk_level = "High"
        else:
            risk_level = "Extreme"

        # ---- Also build the full time series for richer output ----
        portfolio_dict = {t: float(w) for t, w in zip(tickers, weights)}
        timeseries_result = build_pri_timeseries(portfolio_dict, period)

        # Extract summary metrics if the time series built successfully.
        timeseries_summary = {}
        if "summary" in timeseries_result:
            timeseries_summary = timeseries_result["summary"]

        return {
            # PRI composite score (backward compatible — dashboard uses these).
            "pri": pri,
            "risk_level": risk_level,
            "volatility_score": round(volatility_score, 2),
            "correlation_score": round(correlation_score, 2),
            "concentration_score": round(concentration_score, 2),
            "tail_risk_score": round(tail_risk_score, 2),
            "portfolio_volatility_annual": round(portfolio_volatility * 100, 2),
            "tickers": tickers,
            "weights": [round(w, 4) for w in weights.tolist()],
            # New fields from the time series analysis.
            "cumulative_return_pct": timeseries_summary.get("cumulative_return_pct", None),
            "annualized_return_pct": timeseries_summary.get("annualized_return_pct", None),
            "sharpe_ratio": timeseries_summary.get("sharpe_ratio", None),
            "max_drawdown_pct": timeseries_summary.get("max_drawdown_pct", None),
            "max_drawdown_peak_date": timeseries_summary.get("max_drawdown_peak_date", None),
            "max_drawdown_trough_date": timeseries_summary.get("max_drawdown_trough_date", None),
            "current_rolling_vol_pct": timeseries_summary.get("current_rolling_vol_pct", None),
            "pri_start_value": timeseries_summary.get("pri_start_value", None),
            "pri_end_value": timeseries_summary.get("pri_end_value", None),
        }

    except Exception as error:
        return {
            "error": (
                f"PRI calculation failed: {error}\n"
                f"Possible fixes:\n"
                f"  - Make sure all ticker symbols are valid\n"
                f"  - Check your internet connection\n"
                f"  - Try with fewer tickers"
            )
        }


# =============================================================================
# SYSTEMIC RISK SCORE (SRS) — per-asset
# =============================================================================

def calculate_srs(
    tickers: list = None,
    market_ticker: str = "SPY",
    period: str = "2y",
) -> dict:
    """
    Calculate the Systemic Risk Score (SRS) for each asset.

    The SRS measures how much systemic danger an individual asset poses.
    It combines:
      1. Beta (40%): How much does the asset move with the market?
      2. Volatility (30%): How much does the asset's price swing?
      3. Tail contribution (30%): How bad is this asset during market crashes?

    Parameters:
        tickers: List of ticker symbols to score.
        market_ticker: The market benchmark (default: SPY = S&P 500).
        period: Historical period.

    Returns:
        A dictionary with SRS scores for each ticker.
    """
    try:
        if tickers is None:
            tickers = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "HYG", "GLD", "VNQ"]

        # Standardize to uppercase.
        tickers = [t.strip().upper() for t in tickers]
        market_ticker = market_ticker.strip().upper()

        # Make sure market_ticker is included in the download.
        all_tickers = list(set(tickers + [market_ticker]))
        returns = get_returns(all_tickers, period)

        if returns.empty:
            return {"error": "Could not download market data for SRS calculation."}

        if market_ticker not in returns.columns:
            return {"error": f"Market benchmark '{market_ticker}' has no data."}

        market_returns = returns[market_ticker]
        market_variance = market_returns.var()

        scores = {}

        for ticker in tickers:
            if ticker not in returns.columns:
                scores[ticker] = {"srs": None, "error": f"No data for {ticker}"}
                continue

            asset_returns = returns[ticker]

            # ---- Beta: sensitivity to market moves ----
            if market_variance > 0:
                covariance = asset_returns.cov(market_returns)
                beta = covariance / market_variance
            else:
                beta = 1.0

            beta_score = min(100.0, max(0.0, abs(beta) / 2.0 * 100))

            # ---- Volatility score ----
            annual_vol = asset_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
            vol_score = min(100.0, (annual_vol / 0.60) * 100)

            # ---- Tail contribution ----
            market_threshold = np.percentile(market_returns, 5)
            worst_market_days = market_returns <= market_threshold
            if worst_market_days.sum() > 0:
                avg_loss_on_bad_days = asset_returns[worst_market_days].mean()
                tail_score = min(100.0, (abs(avg_loss_on_bad_days) / 0.05) * 100)
            else:
                tail_score = 50.0

            # ---- Combine into SRS ----
            srs = 0.40 * beta_score + 0.30 * vol_score + 0.30 * tail_score
            srs = round(max(0.0, min(100.0, srs)), 2)

            if srs < 20:
                risk_level = "Very Low"
            elif srs < 40:
                risk_level = "Low"
            elif srs < 60:
                risk_level = "Moderate"
            elif srs < 80:
                risk_level = "High"
            else:
                risk_level = "Extreme"

            scores[ticker] = {
                "srs": srs,
                "risk_level": risk_level,
                "beta": round(beta, 4),
                "beta_score": round(beta_score, 2),
                "volatility_annual_pct": round(annual_vol * 100, 2),
                "volatility_score": round(vol_score, 2),
                "tail_score": round(tail_score, 2),
            }

        return {"scores": scores, "market_benchmark": market_ticker}

    except Exception as error:
        return {
            "error": (
                f"SRS calculation failed: {error}\n"
                f"Check your ticker symbols and internet connection."
            )
        }


# =============================================================================
# STRESS TESTING (delegates to stress_engine.py)
# =============================================================================

def run_stress_test(
    tickers: list,
    weights: list = None,
    scenario: str = "2008_crisis",
    custom_shock_pct: float = None,
    period: str = "2y",
) -> dict:
    """
    Run a stress test on a portfolio.

    This function delegates to backend/stress_engine.py, which contains
    the full stress testing logic with five scenarios, projected PRI,
    stressed volatility, worst-asset identification, and more.

    This wrapper exists so that main.py can continue importing
    run_stress_test from portfolio_engine without any changes.

    Available scenarios:
      "2008_crisis":      2008 Financial Crisis
      "covid_crash":      COVID-19 Crash (March 2020)
      "rate_shock":       Interest Rate Shock
      "liquidity_freeze": Liquidity Freeze
      "crypto_contagion": Crypto-Led Risk Contagion
      "custom":           Custom uniform shock (set custom_shock_pct)

    Parameters:
        tickers: List of portfolio tickers.
        weights: Portfolio weights (must sum to 1.0). If None, equal weight.
        scenario: Which stress scenario to run.
        custom_shock_pct: For "custom" scenario, the shock (e.g., -30 for -30%).
        period: Historical period for baseline data.

    Returns:
        Dictionary with stressed portfolio value, per-asset impacts, severity,
        plus new fields: projected_drawdown_pct, stressed_volatility_pct,
        stressed_pri, worst_asset, and more.
    """
    # Import here to avoid circular import issues.
    from backend.stress_engine import run_stress_test as _run_stress_test
    return _run_stress_test(tickers, weights, scenario, custom_shock_pct, period)


# =============================================================================
# EXAMPLE USAGE — Run this file directly to test it
# =============================================================================

if __name__ == "__main__":
    """
    Run this file directly to test all portfolio engine functions:
        cd ~/Desktop/srx-platform
        source venv/bin/activate
        python3 -m backend.portfolio_engine
    """

    print("=" * 70)
    print("SRX PLATFORM — Portfolio Engine Test")
    print("=" * 70)

    # Define a test portfolio.
    test_portfolio = {
        "SPY": 0.40,
        "HYG": 0.20,
        "TLT": 0.20,
        "GLD": 0.10,
        "BTC-USD": 0.10,
    }

    # ---- Test 1: Weight Validation ----
    print("\n--- TEST 1: validate_weights() ---\n")
    validation = validate_weights(test_portfolio)
    if validation["valid"]:
        print(f"  Portfolio is valid.")
        print(f"  Tickers: {validation['tickers']}")
        print(f"  Weights: {[round(w, 4) for w in validation['weights']]}")
        if validation["warnings"]:
            for w in validation["warnings"]:
                print(f"  Warning: {w}")
    else:
        print(f"  INVALID: {validation['error']}")

    # Also test with bad weights that don't sum to 1.
    print("\n  Testing with weights that sum to 2.0 (should normalize):")
    bad_portfolio = {"SPY": 1.0, "TLT": 0.5, "GLD": 0.5}
    bad_validation = validate_weights(bad_portfolio)
    if bad_validation["valid"]:
        print(f"  Normalized portfolio: {bad_validation['portfolio']}")
        for w in bad_validation["warnings"]:
            print(f"  Warning: {w}")

    # ---- Test 2: Build PRI Time Series ----
    print("\n\n--- TEST 2: build_pri_timeseries() ---\n")
    result = build_pri_timeseries(test_portfolio, period="1y")

    if "error" in result:
        print(f"  ERROR: {result['error']}")
    else:
        pri_df = result["pri_series"]
        summary = result["summary"]

        print(f"  Time series shape: {pri_df.shape[0]} rows x {pri_df.shape[1]} columns")
        print(f"\n  First 5 rows:")
        print(pri_df.head().to_string(index=False))
        print(f"\n  Last 5 rows:")
        print(pri_df.tail().to_string(index=False))

        print(f"\n  Summary Metrics:")
        print(f"    Annualized Volatility:   {summary['annualized_volatility_pct']:.2f}%")
        print(f"    Cumulative Return:       {summary['cumulative_return_pct']:.2f}%")
        print(f"    Annualized Return:       {summary['annualized_return_pct']:.2f}%")
        print(f"    Sharpe Ratio:            {summary['sharpe_ratio']:.4f}")
        print(f"    Max Drawdown:            {summary['max_drawdown_pct']:.2f}%")
        print(f"    Max DD Peak Date:        {summary['max_drawdown_peak_date']}")
        print(f"    Max DD Trough Date:      {summary['max_drawdown_trough_date']}")
        print(f"    Current Rolling Vol:     {summary['current_rolling_vol_pct']:.2f}%")
        print(f"    PRI Start:               {summary['pri_start_value']}")
        print(f"    PRI End:                 {summary['pri_end_value']:.4f}")

    # ---- Test 3: Max Drawdown (standalone) ----
    print("\n\n--- TEST 3: compute_max_drawdown() ---\n")
    if "error" not in result:
        dd = compute_max_drawdown(result["pri_series"].set_index("date")["pri"])
        print(f"  Max Drawdown:   {dd['max_drawdown_pct']:.2f}%")
        print(f"  Peak Date:      {dd['peak_date']}")
        print(f"  Trough Date:    {dd['trough_date']}")
        print(f"  Peak Value:     {dd['peak_value']}")
        print(f"  Trough Value:   {dd['trough_value']}")
        print(f"  Recovery Date:  {dd['recovery_date']}")

    # ---- Test 4: PRI Composite Score ----
    print("\n\n--- TEST 4: calculate_pri() (composite score) ---\n")
    tickers = list(test_portfolio.keys())
    weights = list(test_portfolio.values())
    pri_result = calculate_pri(tickers, weights, period="1y")

    if "error" in pri_result:
        print(f"  ERROR: {pri_result['error']}")
    else:
        print(f"  PRI Score:           {pri_result['pri']} / 100")
        print(f"  Risk Level:          {pri_result['risk_level']}")
        print(f"  Volatility Score:    {pri_result['volatility_score']}")
        print(f"  Correlation Score:   {pri_result['correlation_score']}")
        print(f"  Concentration Score: {pri_result['concentration_score']}")
        print(f"  Tail Risk Score:     {pri_result['tail_risk_score']}")
        print(f"  Max Drawdown:        {pri_result['max_drawdown_pct']}%")
        print(f"  Sharpe Ratio:        {pri_result['sharpe_ratio']}")

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
