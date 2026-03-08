"""
stress_engine.py — Stress Testing Engine for the SRX Platform

FILE LOCATION: Save this file as:
    ~/Desktop/srx-platform/backend/stress_engine.py

ARCHITECTURAL DECISION:
    This is a NEW SEPARATE FILE rather than adding code to portfolio_engine.py.
    Why? portfolio_engine.py is already 1,062 lines with PRI, SRS, and the
    basic stress test. The new stress engine adds ~500 lines of scenario logic,
    projected PRI recomputation, and detailed analytics. Keeping it separate
    makes both files easier to read, test, and maintain.

    The old run_stress_test() function in portfolio_engine.py is kept as a
    thin wrapper that calls this module, so main.py and the dashboard continue
    to work without any changes.

WHAT THIS MODULE DOES:
    1. Defines five detailed stress scenarios:
       - 2008 Financial Crisis
       - 2020 COVID Crash
       - Interest Rate Shock
       - Liquidity Freeze
       - Crypto-Led Risk Contagion

    2. For each scenario:
       - Applies asset-class-specific shocks to the portfolio
       - Recomputes a projected (stressed) PRI
       - Estimates projected drawdown, portfolio loss, stressed volatility
       - Identifies the worst contributing asset

    3. Returns results as both a dictionary and a DataFrame.

SCENARIOS IN DETAIL:
    2008_crisis:     Banks collapse, equities -38%, credit -25%, real estate -35%
    covid_crash:     Sudden pandemic shock, equities -34%, fast indiscriminate sell-off
    rate_shock:      Central banks hike rates aggressively, bonds hammered, equities hurt
    liquidity_freeze: Markets seize up, everything drops, illiquid assets hit hardest
    crypto_contagion: Crypto collapse spills into risk assets, stablecoins break peg

MAIN FUNCTIONS:
    get_scenario_definitions()        → Returns all scenario configs
    classify_asset(ticker)            → Maps a ticker to its asset class
    apply_scenario_shocks(portfolio, scenario) → Core shock application
    run_stress_test(tickers, weights, scenario, ...) → Full stress test (API-compatible)
    run_all_scenarios(portfolio)       → Runs all 5 scenarios at once
"""

import numpy as np
import pandas as pd
import sys
import os

# Add the project root to the path so we can import from data/ and backend/.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from data.market_data import get_returns


# =============================================================================
# CONSTANTS
# =============================================================================

TRADING_DAYS_PER_YEAR = 252


# =============================================================================
# SCENARIO DEFINITIONS
# =============================================================================

def get_scenario_definitions() -> dict:
    """
    Return all stress scenario definitions.

    Each scenario is a dictionary containing:
      - name: Human-readable name
      - description: What this scenario simulates
      - shocks: Asset-class-specific percentage shocks (as decimals)
      - vol_multiplier: How much to multiply current volatility
      - correlation_override: Forced correlation level during stress
      - recovery_days: Estimated trading days to recover

    The shocks are calibrated to match actual historical events where possible.
    """
    return {
        # ---- Scenario 1: 2008 Financial Crisis ----
        "2008_crisis": {
            "name": "2008 Financial Crisis",
            "description": (
                "A systemic banking crisis. Lehman Brothers collapses, credit markets "
                "freeze, equities fall ~38%, real estate crashes, and only government "
                "bonds rally as investors flee to safety."
            ),
            "shocks": {
                "equity": -0.38,
                "bond_govt": 0.15,       # Flight to safety — treasuries rally.
                "bond_corp": -0.25,      # Corporate bonds hammered.
                "bond_high_yield": -0.30, # Junk bonds crushed.
                "commodity": -0.25,
                "real_estate": -0.35,
                "crypto": -0.50,         # Hypothetical (crypto didn't exist in 2008).
                "currency_usd": 0.10,    # USD strengthens (safe haven).
                "default": -0.30,
            },
            "vol_multiplier": 3.5,      # Volatility triples during 2008.
            "correlation_override": 0.85, # Everything crashes together.
            "recovery_days": 350,        # ~1.4 years to recover.
        },

        # ---- Scenario 2: 2020 COVID Crash ----
        "covid_crash": {
            "name": "COVID-19 Crash (March 2020)",
            "description": (
                "A sudden pandemic-driven crash. Markets fall ~34% in just 23 trading "
                "days — the fastest drop from a record high in history. Every asset "
                "class sells off initially, including traditional safe havens."
            ),
            "shocks": {
                "equity": -0.34,
                "bond_govt": 0.08,       # Slight rally after initial panic.
                "bond_corp": -0.15,
                "bond_high_yield": -0.20,
                "commodity": -0.22,
                "real_estate": -0.28,
                "crypto": -0.40,         # Bitcoin dropped ~50% in March 2020.
                "currency_usd": 0.05,
                "default": -0.25,
            },
            "vol_multiplier": 4.0,      # VIX spiked above 80 in March 2020.
            "correlation_override": 0.90, # Indiscriminate selling.
            "recovery_days": 120,        # ~5 months to recover (V-shaped).
        },

        # ---- Scenario 3: Interest Rate Shock ----
        "rate_shock": {
            "name": "Interest Rate Shock",
            "description": (
                "Central banks raise rates aggressively to fight inflation. Bond "
                "prices collapse (rates and prices move inversely). Equities fall "
                "moderately as borrowing costs spike. Rate-sensitive sectors (real "
                "estate, utilities) are hit hardest."
            ),
            "shocks": {
                "equity": -0.18,
                "bond_govt": -0.22,      # Long-duration bonds hammered.
                "bond_corp": -0.20,
                "bond_high_yield": -0.25,
                "commodity": 0.05,       # Commodities often rise with inflation.
                "real_estate": -0.25,    # Rate-sensitive.
                "crypto": -0.15,
                "currency_usd": 0.08,    # Higher rates strengthen USD.
                "default": -0.15,
            },
            "vol_multiplier": 2.0,
            "correlation_override": 0.60,
            "recovery_days": 250,
        },

        # ---- Scenario 4: Liquidity Freeze ----
        "liquidity_freeze": {
            "name": "Liquidity Freeze",
            "description": (
                "Markets seize up — bid-ask spreads widen dramatically, counterparties "
                "refuse to trade, and assets cannot be sold at fair prices. Illiquid "
                "assets (high-yield bonds, real estate, small-caps, crypto) are hit "
                "hardest because they're the first markets to freeze."
            ),
            "shocks": {
                "equity": -0.22,
                "bond_govt": 0.05,       # Some flight to safety.
                "bond_corp": -0.18,
                "bond_high_yield": -0.35, # Illiquid — hit hardest.
                "commodity": -0.15,
                "real_estate": -0.30,    # Illiquid — hit hard.
                "crypto": -0.45,         # Extremely illiquid in stress.
                "currency_usd": 0.06,
                "default": -0.20,
            },
            "vol_multiplier": 3.0,
            "correlation_override": 0.75,
            "recovery_days": 200,
        },

        # ---- Scenario 5: Crypto-Led Risk Contagion ----
        "crypto_contagion": {
            "name": "Crypto-Led Risk Contagion",
            "description": (
                "A major crypto collapse (exchange failure, stablecoin de-peg, or "
                "regulatory crackdown) triggers contagion into traditional markets. "
                "Crypto falls 60%+, and the panic spreads to risk assets as leveraged "
                "positions unwind and margin calls cascade."
            ),
            "shocks": {
                "equity": -0.12,         # Moderate contagion to equities.
                "bond_govt": 0.03,       # Minimal flight to safety.
                "bond_corp": -0.08,
                "bond_high_yield": -0.15, # Risk-off hits junk bonds.
                "commodity": -0.05,
                "real_estate": -0.08,
                "crypto": -0.65,         # Core of the crisis.
                "currency_usd": 0.02,
                "default": -0.10,
            },
            "vol_multiplier": 2.5,
            "correlation_override": 0.55, # Contagion is partial, not total.
            "recovery_days": 180,
        },

        # ---- Custom scenario (uses custom_shock_pct for all assets) ----
        "custom": {
            "name": "Custom Shock",
            "description": "User-defined uniform shock applied to all assets.",
            "shocks": {},
            "vol_multiplier": 2.0,
            "correlation_override": 0.70,
            "recovery_days": 150,
        },
    }


# =============================================================================
# ASSET CLASSIFICATION
# =============================================================================

def classify_asset(ticker: str) -> str:
    """
    Map a ticker symbol to its asset class.

    This classification determines which shock percentage is applied to
    each asset during a stress scenario.

    Parameters:
        ticker: Uppercase ticker symbol (e.g., "SPY", "BTC-USD").

    Returns:
        A string like "equity", "bond_govt", "crypto", etc.
        Returns "default" for unrecognized tickers.
    """
    # Dictionary mapping known tickers to asset classes.
    asset_type_map = {
        # Equities
        "SPY": "equity", "QQQ": "equity", "IWM": "equity",
        "EFA": "equity", "EEM": "equity", "DIA": "equity",
        "VOO": "equity", "VTI": "equity", "XLF": "equity",
        "XLK": "equity", "XLE": "equity", "XLV": "equity",
        # Government bonds
        "TLT": "bond_govt", "IEF": "bond_govt", "SHY": "bond_govt",
        "BND": "bond_govt", "AGG": "bond_govt", "GOVT": "bond_govt",
        # Corporate bonds
        "LQD": "bond_corp", "VCIT": "bond_corp",
        # High-yield bonds
        "HYG": "bond_high_yield", "JNK": "bond_high_yield",
        "USHY": "bond_high_yield",
        # Commodities
        "GLD": "commodity", "SLV": "commodity", "USO": "commodity",
        "DBC": "commodity", "GSG": "commodity",
        # Real estate
        "VNQ": "real_estate", "IYR": "real_estate", "XLRE": "real_estate",
        # Crypto
        "BTC-USD": "crypto", "ETH-USD": "crypto", "SOL-USD": "crypto",
        "DOGE-USD": "crypto",
        # USD / Currency
        "UUP": "currency_usd", "FXE": "currency_usd", "DXY": "currency_usd",
    }

    return asset_type_map.get(ticker.strip().upper(), "default")


# =============================================================================
# CORE SHOCK APPLICATION
# =============================================================================

def apply_scenario_shocks(
    portfolio: dict,
    scenario: str = "2008_crisis",
    custom_shock_pct: float = None,
) -> dict:
    """
    Apply scenario-specific shocks to each asset in a portfolio.

    This is the core function that maps each ticker to its asset class,
    looks up the appropriate shock percentage from the scenario definition,
    and calculates the weighted impact on the total portfolio.

    Parameters:
        portfolio: Dictionary of {ticker: weight}, e.g. {"SPY": 0.40, "TLT": 0.20}
                   Weights must be positive (normalized if they don't sum to 1).
        scenario: Name of the stress scenario (e.g., "2008_crisis").
        custom_shock_pct: For "custom" scenario, the uniform shock (e.g., -25.0).

    Returns:
        Dictionary with per-asset impacts and total portfolio shock.
    """
    try:
        scenarios = get_scenario_definitions()

        if scenario not in scenarios:
            return {
                "error": (
                    f"Unknown scenario '{scenario}'.\n"
                    f"Available scenarios: {list(scenarios.keys())}"
                )
            }

        scenario_def = scenarios[scenario]
        shocks = scenario_def["shocks"]

        # Standardize and normalize portfolio.
        tickers = [t.strip().upper() for t in portfolio.keys()]
        raw_weights = np.array([float(portfolio[t]) for t in portfolio.keys()])

        if raw_weights.sum() <= 0:
            return {"error": "Portfolio weights must sum to a positive number."}

        weights = raw_weights / raw_weights.sum()

        # Apply shocks to each asset.
        asset_results = []
        total_portfolio_shock = 0.0

        for i, ticker in enumerate(tickers):
            if scenario == "custom":
                # Custom: apply the same shock to everything.
                shock = (custom_shock_pct if custom_shock_pct is not None else -20.0) / 100.0
            else:
                # Look up the asset class and find the corresponding shock.
                asset_class = classify_asset(ticker)
                shock = shocks.get(asset_class, shocks.get("default", -0.20))

            # Weighted impact = this asset's weight × its shock.
            weighted_impact = weights[i] * shock
            total_portfolio_shock += weighted_impact

            asset_results.append({
                "ticker": ticker,
                "asset_class": classify_asset(ticker),
                "weight": round(float(weights[i]), 4),
                "shock_pct": round(shock * 100, 2),
                "weighted_impact_pct": round(weighted_impact * 100, 2),
            })

        return {
            "scenario": scenario,
            "scenario_name": scenario_def["name"],
            "total_shock_pct": round(total_portfolio_shock * 100, 2),
            "asset_results": asset_results,
            "vol_multiplier": scenario_def["vol_multiplier"],
            "correlation_override": scenario_def["correlation_override"],
            "recovery_days": scenario_def["recovery_days"],
        }

    except Exception as error:
        return {"error": f"Shock application failed: {error}"}


# =============================================================================
# FULL STRESS TEST (API-compatible)
# =============================================================================

def run_stress_test(
    tickers: list,
    weights: list = None,
    scenario: str = "2008_crisis",
    custom_shock_pct: float = None,
    period: str = "2y",
) -> dict:
    """
    Run a full stress test on a portfolio.

    This is the main stress testing function. It:
      1. Applies scenario shocks to each asset
      2. Downloads historical return data
      3. Computes the portfolio's current (pre-stress) risk metrics
      4. Estimates stressed (post-shock) risk metrics:
         - Projected portfolio loss (dollar and percentage)
         - Projected drawdown
         - Stressed volatility
         - Worst contributing asset
      5. Recomputes a projected PRI (stressed risk score)

    Parameters:
        tickers: List of ticker symbols.
        weights: List of weights (must match tickers in length). If None, equal weight.
        scenario: Stress scenario name.
        custom_shock_pct: For "custom" scenario, uniform shock percentage.
        period: Historical period for baseline calculations.

    Returns:
        A dictionary with complete stress test results.

    BACKWARD COMPATIBILITY:
        This function returns the same keys as the original run_stress_test()
        in portfolio_engine.py:
          - scenario, portfolio_shock_pct, severity, starting_value,
            stressed_value, asset_impacts
        Plus new keys:
          - projected_drawdown_pct, stressed_volatility_pct, worst_asset,
            pre_stress_metrics, scenario_name, scenario_description,
            estimated_recovery_days, stress_details_df
    """
    try:
        # ---- Validate inputs ----
        if not tickers or len(tickers) == 0:
            return {"error": "No tickers provided. Please provide at least one ticker symbol."}

        tickers = [t.strip().upper() for t in tickers]

        # Default to equal weights if none provided.
        if weights is None:
            weights = [1.0 / len(tickers)] * len(tickers)

        if len(weights) != len(tickers):
            return {
                "error": (
                    f"Mismatch: {len(tickers)} tickers but {len(weights)} weights. "
                    f"These must be the same length."
                )
            }

        # Normalize weights.
        weights = np.array([float(w) for w in weights])
        if weights.sum() <= 0:
            return {"error": "Weights must sum to a positive number."}
        weights = weights / weights.sum()

        # Build portfolio dict for the shock application function.
        portfolio = {t: float(w) for t, w in zip(tickers, weights)}

        # ---- Step 1: Apply scenario shocks ----
        shock_result = apply_scenario_shocks(portfolio, scenario, custom_shock_pct)

        if "error" in shock_result:
            return shock_result

        portfolio_shock_pct = shock_result["total_shock_pct"]
        vol_multiplier = shock_result["vol_multiplier"]
        corr_override = shock_result["correlation_override"]
        recovery_days = shock_result["recovery_days"]

        # ---- Step 2: Download historical data for baseline metrics ----
        returns = get_returns(tickers, period)

        # Pre-stress metrics (computed from historical data).
        pre_stress_vol = 0.0
        pre_stress_return = 0.0
        pre_stress_drawdown = 0.0

        if not returns.empty:
            available = [t for t in tickers if t in returns.columns]

            if available:
                # Reindex weights for available tickers.
                avail_idx = [tickers.index(t) for t in available]
                avail_weights = np.array([weights[i] for i in avail_idx])
                avail_weights = avail_weights / avail_weights.sum()

                # Portfolio returns.
                port_returns = returns[available].dot(avail_weights)

                # Pre-stress annualized volatility.
                pre_stress_vol = float(port_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))

                # Pre-stress cumulative return.
                cum_return = (1 + port_returns).cumprod()
                pre_stress_return = float(cum_return.iloc[-1] - 1) * 100

                # Pre-stress max drawdown.
                running_max = cum_return.cummax()
                drawdown = (cum_return - running_max) / running_max
                pre_stress_drawdown = float(drawdown.min()) * 100

        # ---- Step 3: Compute stressed metrics ----

        # Stressed volatility: current vol × scenario's vol multiplier.
        stressed_vol = pre_stress_vol * vol_multiplier

        # Projected drawdown: the scenario shock IS the projected drawdown,
        # adjusted by the correlation factor. Higher correlation means the
        # entire portfolio moves together, amplifying losses.
        drawdown_amplifier = 1.0 + (corr_override - 0.5) * 0.3
        projected_drawdown = portfolio_shock_pct * drawdown_amplifier

        # Starting portfolio value (normalized to $100 for easy interpretation).
        starting_value = 100.0
        stressed_value = round(starting_value + portfolio_shock_pct, 2)

        # ---- Step 4: Find the worst contributing asset ----
        asset_impacts = shock_result["asset_results"]
        worst_asset_data = min(asset_impacts, key=lambda x: x["weighted_impact_pct"])
        worst_asset = {
            "ticker": worst_asset_data["ticker"],
            "asset_class": worst_asset_data["asset_class"],
            "weight": worst_asset_data["weight"],
            "shock_pct": worst_asset_data["shock_pct"],
            "weighted_impact_pct": worst_asset_data["weighted_impact_pct"],
            "contribution_to_loss_pct": round(
                (worst_asset_data["weighted_impact_pct"] / portfolio_shock_pct * 100)
                if portfolio_shock_pct != 0 else 0, 2
            ),
        }

        # ---- Step 5: Compute projected (stressed) PRI ----
        # The PRI is a 0-100 risk score. Under stress:
        # - Volatility score spikes (stressed vol)
        # - Correlation score spikes (forced higher correlation)
        # - Tail risk score spikes (the scenario IS a tail event)
        # - Concentration score stays the same (weights don't change)

        # Volatility sub-score: map stressed vol to 0-100.
        vol_score = min(100.0, (stressed_vol / 0.60) * 100)

        # Correlation sub-score: use the scenario's forced correlation.
        corr_score = max(0.0, min(100.0, (corr_override + 1) / 2 * 100))

        # Concentration sub-score (unchanged from pre-stress).
        hhi = np.sum(weights ** 2)
        n = len(tickers)
        if n > 1:
            min_hhi = 1.0 / n
            conc_score = (hhi - min_hhi) / (1.0 - min_hhi) * 100
        else:
            conc_score = 100.0
        conc_score = max(0.0, min(100.0, conc_score))

        # Tail risk sub-score: based on the projected drawdown.
        tail_score = min(100.0, (abs(projected_drawdown) / 5.0) * 100)

        # Combine into stressed PRI.
        stressed_pri = (
            0.35 * vol_score +
            0.25 * corr_score +
            0.15 * conc_score +
            0.25 * tail_score
        )
        stressed_pri = round(max(0.0, min(100.0, stressed_pri)), 2)

        if stressed_pri < 20:
            stressed_risk_level = "Very Low"
        elif stressed_pri < 40:
            stressed_risk_level = "Low"
        elif stressed_pri < 60:
            stressed_risk_level = "Moderate"
        elif stressed_pri < 80:
            stressed_risk_level = "High"
        else:
            stressed_risk_level = "Extreme"

        # ---- Step 6: Severity classification ----
        abs_shock = abs(portfolio_shock_pct)
        if abs_shock < 10:
            severity = "Mild"
        elif abs_shock < 20:
            severity = "Moderate"
        elif abs_shock < 35:
            severity = "Severe"
        else:
            severity = "Catastrophic"

        # ---- Step 7: Build the details DataFrame ----
        details_df = pd.DataFrame(asset_impacts)

        # ---- Build the complete result ----
        scenarios = get_scenario_definitions()
        scenario_def = scenarios.get(scenario, {})

        return {
            # ---- Backward-compatible keys (used by main.py and dashboard) ----
            "scenario": scenario,
            "portfolio_shock_pct": portfolio_shock_pct,
            "severity": severity,
            "starting_value": starting_value,
            "stressed_value": stressed_value,
            "asset_impacts": asset_impacts,

            # ---- New keys ----
            "scenario_name": scenario_def.get("name", scenario),
            "scenario_description": scenario_def.get("description", ""),
            "projected_drawdown_pct": round(projected_drawdown, 2),
            "stressed_volatility_pct": round(stressed_vol * 100, 2),
            "stressed_pri": stressed_pri,
            "stressed_risk_level": stressed_risk_level,
            "worst_asset": worst_asset,
            "estimated_recovery_days": recovery_days,
            "pre_stress_metrics": {
                "annualized_volatility_pct": round(pre_stress_vol * 100, 2),
                "cumulative_return_pct": round(pre_stress_return, 2),
                "max_drawdown_pct": round(pre_stress_drawdown, 2),
            },
            "stressed_pri_components": {
                "volatility_score": round(vol_score, 2),
                "correlation_score": round(corr_score, 2),
                "concentration_score": round(conc_score, 2),
                "tail_risk_score": round(tail_score, 2),
            },
            "stress_details_df": details_df.to_dict(orient="records"),
        }

    except Exception as error:
        return {
            "error": (
                f"Stress test failed: {error}\n"
                f"\n"
                f"Possible fixes:\n"
                f"  1. Make sure your tickers are valid symbols\n"
                f"  2. Check your internet connection\n"
                f"  3. Make sure weights are positive numbers\n"
                f"  4. Try a valid scenario name: 2008_crisis, covid_crash, "
                f"rate_shock, liquidity_freeze, crypto_contagion, custom"
            )
        }


# =============================================================================
# RUN ALL SCENARIOS AT ONCE
# =============================================================================

def run_all_scenarios(
    portfolio: dict,
    period: str = "2y",
) -> dict:
    """
    Run all five stress scenarios on a portfolio and compare results.

    This is useful for getting a complete picture of portfolio vulnerability
    across different types of market crises.

    Parameters:
        portfolio: Dictionary of {ticker: weight}.
                   Example: {"SPY": 0.40, "TLT": 0.20, "HYG": 0.20,
                             "GLD": 0.10, "BTC-USD": 0.10}
        period: Historical period for baseline metrics.

    Returns:
        Dictionary with results for every scenario, plus a summary comparison.
    """
    try:
        tickers = [t.strip().upper() for t in portfolio.keys()]
        raw_weights = [float(w) for w in portfolio.values()]

        # Scenarios to run (exclude "custom" since it needs a shock value).
        scenario_names = [
            "2008_crisis",
            "covid_crash",
            "rate_shock",
            "liquidity_freeze",
            "crypto_contagion",
        ]

        all_results = {}
        summary_rows = []

        for scenario in scenario_names:
            result = run_stress_test(tickers, raw_weights, scenario, period=period)

            if "error" in result:
                all_results[scenario] = {"error": result["error"]}
                continue

            all_results[scenario] = result

            summary_rows.append({
                "scenario": result.get("scenario_name", scenario),
                "portfolio_shock_pct": result["portfolio_shock_pct"],
                "severity": result["severity"],
                "stressed_value": result["stressed_value"],
                "projected_drawdown_pct": result.get("projected_drawdown_pct", None),
                "stressed_volatility_pct": result.get("stressed_volatility_pct", None),
                "stressed_pri": result.get("stressed_pri", None),
                "worst_asset": result.get("worst_asset", {}).get("ticker", "N/A"),
                "recovery_days": result.get("estimated_recovery_days", None),
            })

        # Build a comparison DataFrame.
        summary_df = pd.DataFrame(summary_rows)

        # Find the worst scenario (largest portfolio loss).
        if summary_rows:
            worst_scenario = min(summary_rows, key=lambda x: x["portfolio_shock_pct"])
        else:
            worst_scenario = None

        return {
            "scenario_results": all_results,
            "summary_df": summary_df.to_dict(orient="records"),
            "worst_scenario": worst_scenario,
            "portfolio": portfolio,
        }

    except Exception as error:
        return {
            "error": (
                f"Multi-scenario stress test failed: {error}\n"
                f"Check your portfolio format: {{\"SPY\": 0.40, \"TLT\": 0.30, ...}}"
            )
        }


# =============================================================================
# EXAMPLE USAGE — Run this file directly to test
# =============================================================================

if __name__ == "__main__":
    """
    Run this file directly to test the stress engine:
        cd ~/Desktop/srx-platform
        source venv/bin/activate
        python3 -m backend.stress_engine
    """

    print("=" * 70)
    print("SRX PLATFORM — Stress Engine Test")
    print("=" * 70)

    # Define a test portfolio.
    test_portfolio = {
        "SPY": 0.40,
        "HYG": 0.20,
        "TLT": 0.20,
        "GLD": 0.10,
        "BTC-USD": 0.10,
    }

    all_passed = True

    # ---- Test 1: Asset Classification ----
    print("\n--- TEST 1: classify_asset() ---\n")
    test_tickers = ["SPY", "TLT", "HYG", "GLD", "BTC-USD", "UUP", "VNQ", "AAPL"]
    for t in test_tickers:
        print(f"  {t:>10} → {classify_asset(t)}")

    # ---- Test 2: Single Scenario ----
    print("\n\n--- TEST 2: run_stress_test() — 2008 Crisis ---\n")
    tickers = list(test_portfolio.keys())
    weights = list(test_portfolio.values())
    result = run_stress_test(tickers, weights, "2008_crisis", period="1y")

    if "error" in result:
        print(f"  ERROR: {result['error']}")
        all_passed = False
    else:
        print(f"  Scenario:              {result['scenario_name']}")
        print(f"  Portfolio Shock:       {result['portfolio_shock_pct']:.2f}%")
        print(f"  Stressed Value:        ${result['stressed_value']:.2f} (from $100)")
        print(f"  Severity:              {result['severity']}")
        print(f"  Projected Drawdown:    {result['projected_drawdown_pct']:.2f}%")
        print(f"  Stressed Volatility:   {result['stressed_volatility_pct']:.2f}%")
        print(f"  Stressed PRI:          {result['stressed_pri']:.2f} / 100 ({result['stressed_risk_level']})")
        print(f"  Est. Recovery:         {result['estimated_recovery_days']} trading days")
        print(f"\n  Worst Asset:")
        wa = result["worst_asset"]
        print(f"    Ticker:              {wa['ticker']}")
        print(f"    Asset Class:         {wa['asset_class']}")
        print(f"    Shock:               {wa['shock_pct']:.2f}%")
        print(f"    Loss Contribution:   {wa['contribution_to_loss_pct']:.1f}% of total loss")
        print(f"\n  Pre-Stress Metrics:")
        pre = result["pre_stress_metrics"]
        print(f"    Volatility:          {pre['annualized_volatility_pct']:.2f}%")
        print(f"    Cumulative Return:   {pre['cumulative_return_pct']:.2f}%")
        print(f"    Max Drawdown:        {pre['max_drawdown_pct']:.2f}%")
        print(f"\n  Per-Asset Impacts:")
        for impact in result["asset_impacts"]:
            print(
                f"    {impact['ticker']:>8} ({impact['asset_class']:>15}): "
                f"shock {impact['shock_pct']:>+7.2f}%  |  "
                f"weighted {impact['weighted_impact_pct']:>+7.2f}%"
            )

    # ---- Test 3: All Scenarios ----
    print("\n\n--- TEST 3: run_all_scenarios() ---\n")
    multi_result = run_all_scenarios(test_portfolio, period="1y")

    if "error" in multi_result:
        print(f"  ERROR: {multi_result['error']}")
        all_passed = False
    else:
        print("  Scenario Comparison:")
        print(f"  {'Scenario':<30} {'Shock':>8} {'Severity':<14} {'PRI':>6} {'Worst':>10} {'Recovery':>10}")
        print(f"  {'-'*28}  {'-'*6}  {'-'*12}  {'-'*4}  {'-'*8}  {'-'*8}")
        for row in multi_result["summary_df"]:
            print(
                f"  {row['scenario']:<30} "
                f"{row['portfolio_shock_pct']:>+7.2f}% "
                f"{row['severity']:<14} "
                f"{row.get('stressed_pri', 0):>5.1f} "
                f"{row.get('worst_asset', 'N/A'):>10} "
                f"{row.get('recovery_days', 0):>8}d"
            )

        if multi_result["worst_scenario"]:
            ws = multi_result["worst_scenario"]
            print(f"\n  Worst scenario: {ws['scenario']} ({ws['portfolio_shock_pct']:+.2f}%)")

    # ---- Test 4: Liquidity Freeze (new scenario) ----
    print("\n\n--- TEST 4: run_stress_test() — Liquidity Freeze ---\n")
    liq_result = run_stress_test(tickers, weights, "liquidity_freeze", period="1y")

    if "error" in liq_result:
        print(f"  ERROR: {liq_result['error']}")
        all_passed = False
    else:
        print(f"  Scenario:           {liq_result['scenario_name']}")
        print(f"  Portfolio Shock:    {liq_result['portfolio_shock_pct']:.2f}%")
        print(f"  Stressed PRI:       {liq_result['stressed_pri']:.2f}")
        print(f"  Severity:           {liq_result['severity']}")

    # ---- Test 5: Crypto Contagion (new scenario) ----
    print("\n\n--- TEST 5: run_stress_test() — Crypto Contagion ---\n")
    crypto_result = run_stress_test(tickers, weights, "crypto_contagion", period="1y")

    if "error" in crypto_result:
        print(f"  ERROR: {crypto_result['error']}")
        all_passed = False
    else:
        print(f"  Scenario:           {crypto_result['scenario_name']}")
        print(f"  Portfolio Shock:    {crypto_result['portfolio_shock_pct']:.2f}%")
        print(f"  Stressed PRI:       {crypto_result['stressed_pri']:.2f}")
        print(f"  Worst Asset:        {crypto_result['worst_asset']['ticker']} "
              f"({crypto_result['worst_asset']['shock_pct']:+.1f}%)")

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    if all_passed:
        print("STATUS: All tests passed. Stress engine is working.")
    else:
        print("STATUS: Some tests failed. Check error messages above.")
    print("=" * 70)
