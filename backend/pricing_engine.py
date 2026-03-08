"""
pricing_engine.py — Crash Protection Pricing Engine for the SRX Platform

FILE LOCATION: Save this file as:
    ~/Desktop/srx-platform/backend/pricing_engine.py

WHAT THIS MODULE DOES:
    Prices "crash protection contracts" — hypothetical insurance policies that
    pay out when a portfolio loses more than a specified threshold.

    Think of it like car insurance, but for investment portfolios:
      - You pay a premium (the price of protection)
      - If your portfolio crashes beyond a threshold, the contract pays you
      - The premium depends on how risky the portfolio is and how stressed
        the overall market is

PRICING FORMULA:
    ProtectionPremium = Notional × BaseRate × SRSMultiplier
                        × PortfolioRiskAdjustment × LiquidityAdjustment

    Where:
      BaseRate:               1% of notional (starting point)
      SRSMultiplier:          If SRS ≤ 50: 1.0  |  If SRS > 50: (SRS / 50)^2
      PortfolioRiskAdjustment: PRI_vol / GSRI_vol (capped at 3x)
      LiquidityAdjustment:    Manual factor (default 1.0, higher = more illiquid)

MAIN FUNCTIONS:
    compute_srs_multiplier()         → SRS-based non-linear multiplier
    compute_portfolio_risk_adjustment() → PRI vol vs GSRI vol ratio
    compute_premium()                → Core pricing calculation
    estimate_payout_profile()        → Payout at different drawdown levels
    price_protection()               → Full API-compatible pricing (backward compat)
    price_protection_grid()          → Grid of prices across levels/durations

BACKWARD COMPATIBILITY:
    price_protection() and price_protection_grid() are imported by:
      - backend/main.py (the /price endpoint)
      - frontend/dashboard.py (reads premium_dollars, premium_bps, etc.)
    All return keys are preserved.
"""

import numpy as np
import pandas as pd
import sys
import os

# Add the project root to the path so we can import from data/ and backend/.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from data.market_data import get_returns
from backend.gsri_engine import calculate_gsri


# =============================================================================
# CONSTANTS
# =============================================================================

# Trading days in a year (for annualizing daily statistics).
TRADING_DAYS_PER_YEAR = 252

# Base rate: the starting point for the premium as a fraction of notional.
# 1% = 0.01. This represents the "actuarial fair" cost of protection in
# calm markets with average risk.
BASE_RATE = 0.01

# Risk loading factor: added on top of the actuarial premium to account
# for model uncertainty and a profit margin for the protection seller.
# 1.25 = 25% loading.
RISK_LOADING = 1.25

# Minimum premium floor as a fraction of notional.
# Even if all multipliers say the risk is very low, the premium won't
# go below this floor. 10 bps = 0.001.
MIN_PREMIUM_FRACTION = 0.001

# Maximum cap for the portfolio risk adjustment multiplier.
# Prevents the premium from exploding for extremely volatile portfolios.
MAX_PORTFOLIO_RISK_MULTIPLIER = 3.0


# =============================================================================
# HELPER: SRS Multiplier
# =============================================================================

def compute_srs_multiplier(srs: float) -> dict:
    """
    Compute the SRS-based multiplier for the protection premium.

    The logic uses a non-linear (quadratic) scale:
      - If SRS ≤ 50: multiplier = 1.0  (normal conditions, no surcharge)
      - If SRS > 50: multiplier = (SRS / 50)^2  (accelerating surcharge)

    Why quadratic?
        Systemic risk doesn't increase linearly. The jump from SRS 70 to 80
        is far more dangerous than 30 to 40. The quadratic curve charges
        disproportionately more as SRS rises above 50, reflecting the
        non-linear nature of systemic crises.

    Examples:
        SRS = 30 → multiplier = 1.00  (no surcharge)
        SRS = 50 → multiplier = 1.00  (boundary — no surcharge)
        SRS = 60 → multiplier = 1.44  (+44%)
        SRS = 75 → multiplier = 2.25  (+125%)
        SRS = 90 → multiplier = 3.24  (+224%)
        SRS = 100→ multiplier = 4.00  (+300%)

    Parameters:
        srs: Current Systemic Risk Score (0–100).

    Returns:
        Dictionary with the multiplier and explanatory details.
    """
    try:
        srs = max(0.0, min(100.0, float(srs)))

        if srs <= 50.0:
            multiplier = 1.0
            explanation = "SRS is at or below 50 — no systemic risk surcharge applied."
        else:
            multiplier = (srs / 50.0) ** 2
            surcharge_pct = (multiplier - 1.0) * 100
            explanation = (
                f"SRS is {srs:.1f} (above 50) — "
                f"quadratic surcharge of +{surcharge_pct:.0f}% applied."
            )

        return {
            "multiplier": round(multiplier, 4),
            "srs_input": round(srs, 2),
            "explanation": explanation,
        }

    except Exception as error:
        print(f"  WARNING: SRS multiplier calculation failed: {error}. Using 1.0.")
        return {"multiplier": 1.0, "srs_input": 0.0, "explanation": "Defaulted to 1.0"}


# =============================================================================
# HELPER: Portfolio Risk Adjustment
# =============================================================================

def compute_portfolio_risk_adjustment(
    pri_volatility_pct: float,
    gsri_volatility_pct: float,
) -> dict:
    """
    Compute the portfolio risk adjustment based on volatility comparison.

    Logic:
        If the portfolio's volatility (from PRI) is higher than the market's
        overall volatility (from GSRI), the portfolio is riskier than average
        and should pay a higher premium.

        Adjustment = PRI_volatility / GSRI_volatility
        Capped at 3.0x to prevent runaway premiums.
        Floored at 0.5x to ensure a minimum charge.

    Examples:
        PRI vol = 15%, GSRI vol = 15% → adjustment = 1.00 (average risk)
        PRI vol = 25%, GSRI vol = 15% → adjustment = 1.67 (+67% premium)
        PRI vol = 10%, GSRI vol = 15% → adjustment = 0.67 (-33% premium, but floored at 0.5)

    Parameters:
        pri_volatility_pct:  Portfolio annualized volatility as a percentage (e.g., 15.0).
        gsri_volatility_pct: GSRI/market annualized volatility as a percentage (e.g., 12.0).

    Returns:
        Dictionary with the adjustment factor and explanation.
    """
    try:
        pri_vol = max(0.01, float(pri_volatility_pct))
        gsri_vol = max(0.01, float(gsri_volatility_pct))

        raw_adjustment = pri_vol / gsri_vol

        # Clamp to [0.5, MAX_PORTFOLIO_RISK_MULTIPLIER].
        adjustment = max(0.5, min(MAX_PORTFOLIO_RISK_MULTIPLIER, raw_adjustment))

        if adjustment > 1.0:
            explanation = (
                f"Portfolio vol ({pri_vol:.1f}%) exceeds market vol ({gsri_vol:.1f}%) — "
                f"premium increased by {(adjustment - 1) * 100:.0f}%."
            )
        elif adjustment < 1.0:
            explanation = (
                f"Portfolio vol ({pri_vol:.1f}%) is below market vol ({gsri_vol:.1f}%) — "
                f"premium reduced by {(1 - adjustment) * 100:.0f}%."
            )
        else:
            explanation = (
                f"Portfolio vol ({pri_vol:.1f}%) matches market vol ({gsri_vol:.1f}%) — "
                f"no adjustment."
            )

        return {
            "adjustment": round(adjustment, 4),
            "pri_volatility_pct": round(pri_vol, 2),
            "gsri_volatility_pct": round(gsri_vol, 2),
            "raw_ratio": round(raw_adjustment, 4),
            "was_capped": raw_adjustment > MAX_PORTFOLIO_RISK_MULTIPLIER,
            "was_floored": raw_adjustment < 0.5,
            "explanation": explanation,
        }

    except Exception as error:
        print(f"  WARNING: Portfolio risk adjustment failed: {error}. Using 1.0.")
        return {
            "adjustment": 1.0, "pri_volatility_pct": 0, "gsri_volatility_pct": 0,
            "raw_ratio": 1.0, "was_capped": False, "was_floored": False,
            "explanation": "Defaulted to 1.0",
        }


# =============================================================================
# CORE PREMIUM CALCULATION
# =============================================================================

def compute_premium(
    notional: float,
    srs: float = 50.0,
    pri_volatility_pct: float = 15.0,
    gsri_volatility_pct: float = 15.0,
    liquidity_adjustment: float = 1.0,
    protection_level_pct: float = 20.0,
    duration_days: int = 90,
) -> dict:
    """
    Compute the crash protection premium using the actuarial formula.

    Formula:
        Premium = Notional × BaseRate × SRSMultiplier
                  × PortfolioRiskAdjustment × LiquidityAdjustment
                  × RiskLoading × DurationFactor × ProtectionDepthFactor

    Parameters:
        notional:             Dollar value of the portfolio (e.g., 1,000,000).
        srs:                  Current Systemic Risk Score (0–100).
        pri_volatility_pct:   Portfolio annualized volatility (%, from PRI).
        gsri_volatility_pct:  Market annualized volatility (%, from GSRI).
        liquidity_adjustment: Manual liquidity factor (default 1.0).
                              Set higher (e.g., 1.3) for illiquid portfolios.
                              Set lower (e.g., 0.8) for very liquid ones.
        protection_level_pct: Strike / drawdown threshold (%).
                              E.g., 20.0 means the contract triggers at -20%.
        duration_days:        How many calendar days the protection lasts.

    Returns:
        A dictionary with the premium, breakdown of each multiplier, and details.
    """
    try:
        # ---- Validate inputs ----
        if notional <= 0:
            return {"error": "Notional must be a positive number."}

        if protection_level_pct <= 0 or protection_level_pct > 100:
            return {"error": "Protection level must be between 0 and 100 percent."}

        if duration_days <= 0:
            return {"error": "Duration must be a positive number of days."}

        if liquidity_adjustment <= 0:
            return {"error": "Liquidity adjustment must be a positive number."}

        # ---- Step 1: SRS Multiplier ----
        srs_result = compute_srs_multiplier(srs)
        srs_multiplier = srs_result["multiplier"]

        # ---- Step 2: Portfolio Risk Adjustment ----
        risk_result = compute_portfolio_risk_adjustment(pri_volatility_pct, gsri_volatility_pct)
        portfolio_adjustment = risk_result["adjustment"]

        # ---- Step 3: Duration Factor ----
        # Longer protection costs more. Scaled as sqrt(duration / 90) so that
        # doubling the duration doesn't double the price (risk doesn't scale linearly).
        duration_factor = max(0.5, np.sqrt(duration_days / 90.0))

        # ---- Step 4: Protection Depth Factor ----
        # Deeper protection (lower strike) costs less per unit because
        # extreme crashes are rarer. A -10% trigger is more likely than -30%.
        # Factor = (20 / protection_level)^0.5 — normalized so 20% strike = 1.0.
        depth_factor = (20.0 / max(1.0, protection_level_pct)) ** 0.5

        # ---- Step 5: Compute premium ----
        premium = (
            notional
            * BASE_RATE
            * srs_multiplier
            * portfolio_adjustment
            * liquidity_adjustment
            * RISK_LOADING
            * duration_factor
            * depth_factor
        )

        # Apply floor.
        min_premium = notional * MIN_PREMIUM_FRACTION
        was_floored = premium < min_premium
        premium = max(premium, min_premium)

        # ---- Step 6: Derived metrics ----
        premium_pct = (premium / notional) * 100
        premium_bps = premium_pct * 100
        max_payout = notional * (protection_level_pct / 100.0)

        annual_factor = 365.0 / duration_days
        annualized_premium = premium * annual_factor
        annualized_bps = premium_bps * annual_factor

        # Implied loss ratio: if the crash happens, payout / premium.
        if premium > 0:
            implied_loss_ratio = max_payout / premium
        else:
            implied_loss_ratio = 0.0

        return {
            "premium_dollars": round(premium, 2),
            "premium_pct": round(premium_pct, 4),
            "premium_bps": round(premium_bps, 2),
            "annualized_premium_dollars": round(annualized_premium, 2),
            "annualized_premium_bps": round(annualized_bps, 2),
            "notional": notional,
            "max_payout_dollars": round(max_payout, 2),
            "implied_loss_ratio": round(implied_loss_ratio, 2),
            "was_floored": was_floored,
            "multiplier_breakdown": {
                "base_rate": BASE_RATE,
                "srs_multiplier": srs_multiplier,
                "portfolio_risk_adjustment": portfolio_adjustment,
                "liquidity_adjustment": round(liquidity_adjustment, 4),
                "risk_loading": RISK_LOADING,
                "duration_factor": round(duration_factor, 4),
                "depth_factor": round(depth_factor, 4),
                "combined_multiplier": round(
                    srs_multiplier * portfolio_adjustment * liquidity_adjustment
                    * RISK_LOADING * duration_factor * depth_factor, 4
                ),
            },
            "srs_detail": srs_result,
            "portfolio_risk_detail": risk_result,
        }

    except Exception as error:
        return {"error": f"Premium computation failed: {error}"}


# =============================================================================
# PAYOUT PROFILE
# =============================================================================

def estimate_payout_profile(
    notional: float,
    protection_level_pct: float = 20.0,
    drawdown_steps: list = None,
) -> dict:
    """
    Estimate the payout at different drawdown levels.

    This shows the contract holder what they would receive if the portfolio
    drops by various amounts. The contract pays $0 if the drop is less than
    the protection level, and the full notional-loss amount if it equals
    or exceeds the protection level.

    For a "binary" style contract (like the SRX prototype):
      - Drop < protection_level → payout = $0
      - Drop ≥ protection_level → payout = notional × protection_level_pct / 100

    We also show a "proportional" alternative where the payout scales with
    the amount of excess loss beyond the trigger.

    Parameters:
        notional:             Portfolio value in dollars.
        protection_level_pct: Strike / trigger level (%).
        drawdown_steps:       List of drawdown percentages to evaluate.
                              Default: [5, 10, 15, 20, 25, 30, 40, 50].

    Returns:
        Dictionary with binary and proportional payout profiles.
    """
    try:
        if drawdown_steps is None:
            drawdown_steps = [5, 10, 15, 20, 25, 30, 40, 50]

        binary_payouts = []
        proportional_payouts = []
        max_payout = notional * (protection_level_pct / 100.0)

        for dd in drawdown_steps:
            # Binary payout: all or nothing at the trigger.
            if dd >= protection_level_pct:
                binary_payout = max_payout
            else:
                binary_payout = 0.0

            # Proportional payout: scales with excess loss beyond the trigger.
            if dd >= protection_level_pct:
                excess_loss_pct = dd - protection_level_pct
                proportional_payout = notional * (excess_loss_pct / 100.0)
                # Cap at notional (can't pay more than the portfolio is worth).
                proportional_payout = min(proportional_payout, notional)
            else:
                proportional_payout = 0.0

            portfolio_loss = notional * (dd / 100.0)

            binary_payouts.append({
                "drawdown_pct": dd,
                "portfolio_loss_dollars": round(portfolio_loss, 2),
                "binary_payout_dollars": round(binary_payout, 2),
                "net_loss_after_payout": round(portfolio_loss - binary_payout, 2),
            })

            proportional_payouts.append({
                "drawdown_pct": dd,
                "portfolio_loss_dollars": round(portfolio_loss, 2),
                "proportional_payout_dollars": round(proportional_payout, 2),
                "net_loss_after_payout": round(portfolio_loss - proportional_payout, 2),
            })

        return {
            "protection_level_pct": protection_level_pct,
            "max_binary_payout_dollars": round(max_payout, 2),
            "binary_payouts": binary_payouts,
            "proportional_payouts": proportional_payouts,
        }

    except Exception as error:
        return {"error": f"Payout profile estimation failed: {error}"}


# =============================================================================
# API FUNCTION: price_protection (backward compatible)
# =============================================================================

def price_protection(
    tickers: list,
    weights: list = None,
    notional: float = 1_000_000,
    protection_level_pct: float = 20.0,
    duration_days: int = 90,
    period: str = "2y",
) -> dict:
    """
    Price a crash protection contract for a portfolio — API-compatible version.

    This is the main function called by backend/main.py (the /price endpoint)
    and used by the dashboard. It:
      1. Downloads historical return data
      2. Computes portfolio volatility and historical crash probability
      3. Gets the current GSRI/SRS for the systemic risk multiplier
      4. Runs the actuarial pricing formula
      5. Generates a payout profile
      6. Returns everything the dashboard needs

    Parameters:
        tickers:              List of portfolio ticker symbols.
        weights:              Portfolio weights (must sum to 1). If None, equal weight.
        notional:             Dollar value being protected (e.g., 1,000,000).
        protection_level_pct: Crash threshold (%). E.g., 20.0 means payout if -20%.
        duration_days:        Calendar days the protection lasts.
        period:               Historical data period for probability estimation.

    Returns:
        A dictionary with the premium, multiplier breakdown, payout profile,
        and all keys the dashboard expects.
    """
    try:
        # ---- Validate inputs ----
        if not tickers:
            return {"error": "No tickers provided."}

        if notional <= 0:
            return {"error": "Notional (portfolio value) must be a positive number."}

        if protection_level_pct <= 0 or protection_level_pct > 100:
            return {"error": "Protection level must be between 0 and 100 percent."}

        if duration_days <= 0:
            return {"error": "Duration must be a positive number of days."}

        # Standardize tickers.
        tickers = [t.strip().upper() for t in tickers]

        # Set up weights.
        if weights is None:
            weights = [1.0 / len(tickers)] * len(tickers)
        weights = np.array([float(w) for w in weights])
        weights = weights / weights.sum()

        # ---- Download historical returns ----
        returns = get_returns(tickers, period)

        if returns.empty:
            return {"error": "Could not download data for pricing. Check your internet."}

        available = [t for t in tickers if t in returns.columns]
        if len(available) == 0:
            return {"error": "None of the tickers returned valid data."}

        # Reindex weights for available tickers.
        if len(available) < len(tickers):
            idx = [tickers.index(t) for t in available]
            weights = np.array([weights[i] for i in idx])
            weights = weights / weights.sum()
            tickers = available

        returns = returns[tickers]

        # ---- Compute portfolio returns and volatility ----
        portfolio_returns = returns.dot(weights)
        pri_vol = float(portfolio_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
        pri_vol_pct = pri_vol * 100

        # ---- Estimate historical crash probability ----
        protection_threshold = -protection_level_pct / 100.0
        trading_days_in_duration = max(5, int(duration_days * 252 / 365))

        historical_probability = 0.0
        if len(portfolio_returns) >= trading_days_in_duration + 5:
            rolling_cumulative = (
                (1 + portfolio_returns)
                .rolling(window=trading_days_in_duration)
                .apply(lambda x: x.prod() - 1, raw=True)
            )
            rolling_cumulative = rolling_cumulative.dropna()

            if not rolling_cumulative.empty:
                crash_count = (rolling_cumulative <= protection_threshold).sum()
                total_windows = len(rolling_cumulative)
                historical_probability = float(crash_count / total_windows)

        # ---- Get GSRI for systemic risk assessment ----
        gsri_result = calculate_gsri(period=period)
        if "error" in gsri_result:
            current_gsri = 50.0
            current_srs = 50.0
            gsri_vol_pct = pri_vol_pct  # Default to portfolio vol if GSRI fails.
        else:
            current_gsri = gsri_result["current_gsri"]
            current_srs = gsri_result.get("srs_current", current_gsri)
            # Use the GSRI volatility sub-score as a proxy for market vol.
            # The sub_scores["volatility"] is a 0-100 score; we convert back
            # to approximate volatility: score of 50 ≈ 15% vol.
            vol_score = gsri_result.get("sub_scores", {}).get("volatility", 50)
            gsri_vol_pct = max(1.0, vol_score * 0.30)

        # ---- Run the actuarial pricing formula ----
        pricing_result = compute_premium(
            notional=notional,
            srs=current_srs,
            pri_volatility_pct=pri_vol_pct,
            gsri_volatility_pct=gsri_vol_pct,
            liquidity_adjustment=1.0,
            protection_level_pct=protection_level_pct,
            duration_days=duration_days,
        )

        if "error" in pricing_result:
            return pricing_result

        # ---- Generate payout profile ----
        payout_profile = estimate_payout_profile(notional, protection_level_pct)

        # ---- Build the combined GSRI/SRS multiplier for backward compat ----
        # The old code used a single "gsri_multiplier". We now derive it from
        # the SRS multiplier so the dashboard still shows it correctly.
        srs_mult = pricing_result["multiplier_breakdown"]["srs_multiplier"]
        # Map to the old range: 0.5 to 2.0.
        gsri_multiplier = 0.5 + (current_gsri / 100.0) * 1.5

        return {
            # ---- Backward-compatible keys (dashboard reads these) ----
            "premium_dollars": pricing_result["premium_dollars"],
            "premium_bps": pricing_result["premium_bps"],
            "annualized_premium_dollars": pricing_result["annualized_premium_dollars"],
            "annualized_premium_bps": pricing_result["annualized_premium_bps"],
            "notional": notional,
            "protection_level_pct": protection_level_pct,
            "max_payout_dollars": pricing_result["max_payout_dollars"],
            "duration_days": duration_days,
            "historical_crash_probability": round(historical_probability, 6),
            "gsri_used": round(current_gsri, 2),
            "gsri_multiplier": round(gsri_multiplier, 4),
            "tickers": tickers,
            "weights": [round(w, 4) for w in weights.tolist()],
            "pricing_method": "Actuarial SRS-based pricing with portfolio risk adjustment",

            # ---- New keys ----
            "srs_used": round(current_srs, 2),
            "srs_multiplier": srs_mult,
            "portfolio_volatility_pct": round(pri_vol_pct, 2),
            "market_volatility_pct": round(gsri_vol_pct, 2),
            "portfolio_risk_adjustment": pricing_result["multiplier_breakdown"]["portfolio_risk_adjustment"],
            "liquidity_adjustment": pricing_result["multiplier_breakdown"]["liquidity_adjustment"],
            "premium_pct": pricing_result["premium_pct"],
            "implied_loss_ratio": pricing_result["implied_loss_ratio"],
            "multiplier_breakdown": pricing_result["multiplier_breakdown"],
            "payout_profile": payout_profile,
        }

    except Exception as error:
        return {
            "error": (
                f"Protection pricing failed: {error}\n"
                f"Check your inputs: tickers, notional, protection level, and duration."
            )
        }


# =============================================================================
# PRICING GRID — multiple protection levels at once
# =============================================================================

def price_protection_grid(
    tickers: list,
    weights: list = None,
    notional: float = 1_000_000,
    protection_levels: list = None,
    durations: list = None,
    period: str = "2y",
) -> dict:
    """
    Price protection at multiple levels and durations simultaneously.

    This generates a grid showing how premiums change as you vary the
    protection trigger level and the contract duration.

    Parameters:
        tickers:           Portfolio tickers.
        weights:           Portfolio weights.
        notional:          Portfolio value in dollars.
        protection_levels: List of trigger levels (%). Default: [10, 15, 20, 25, 30].
        durations:         List of durations (days). Default: [30, 60, 90, 180].
        period:            Historical period.

    Returns:
        A dictionary with a grid of prices.
    """
    try:
        if protection_levels is None:
            protection_levels = [10, 15, 20, 25, 30]

        if durations is None:
            durations = [30, 60, 90, 180]

        grid = []

        for level in protection_levels:
            for duration in durations:
                result = price_protection(
                    tickers=tickers,
                    weights=weights,
                    notional=notional,
                    protection_level_pct=level,
                    duration_days=duration,
                    period=period,
                )
                grid.append({
                    "protection_level_pct": level,
                    "duration_days": duration,
                    "premium_dollars": result.get("premium_dollars", None),
                    "premium_bps": result.get("premium_bps", None),
                    "crash_probability": result.get("historical_crash_probability", None),
                    "srs_multiplier": result.get("srs_multiplier", None),
                    "error": result.get("error", None),
                })

        return {"grid": grid, "notional": notional, "tickers": tickers}

    except Exception as error:
        return {"error": f"Pricing grid failed: {error}"}


# =============================================================================
# EXAMPLE USAGE — Run this file directly to test
# =============================================================================

if __name__ == "__main__":
    """
    Run this file directly to test the pricing engine:
        cd ~/Desktop/srx-platform
        source venv/bin/activate
        python3 -m backend.pricing_engine
    """

    print("=" * 70)
    print("SRX PLATFORM — Pricing Engine Test")
    print("=" * 70)

    all_passed = True

    # ---- Test 1: SRS Multiplier ----
    print("\n--- TEST 1: compute_srs_multiplier() ---\n")
    for srs_val in [0, 25, 50, 60, 75, 90, 100]:
        result = compute_srs_multiplier(srs_val)
        print(f"  SRS = {srs_val:>3} → multiplier = {result['multiplier']:.4f}")

    # ---- Test 2: Portfolio Risk Adjustment ----
    print("\n\n--- TEST 2: compute_portfolio_risk_adjustment() ---\n")
    test_cases = [
        (15.0, 15.0, "equal vol"),
        (25.0, 15.0, "PRI vol > GSRI vol"),
        (10.0, 15.0, "PRI vol < GSRI vol"),
        (45.0, 12.0, "very high PRI vol (should cap)"),
    ]
    for pri_v, gsri_v, label in test_cases:
        result = compute_portfolio_risk_adjustment(pri_v, gsri_v)
        cap_str = " [CAPPED]" if result["was_capped"] else ""
        print(f"  PRI={pri_v:.0f}%, GSRI={gsri_v:.0f}% ({label}): "
              f"adj={result['adjustment']:.4f}{cap_str}")

    # ---- Test 3: Core Premium Calculation ----
    print("\n\n--- TEST 3: compute_premium() ---\n")
    premium_result = compute_premium(
        notional=1_000_000,
        srs=65.0,
        pri_volatility_pct=18.0,
        gsri_volatility_pct=14.0,
        liquidity_adjustment=1.15,
        protection_level_pct=20.0,
        duration_days=90,
    )

    if "error" in premium_result:
        print(f"  ERROR: {premium_result['error']}")
        all_passed = False
    else:
        print(f"  Notional:           $1,000,000")
        print(f"  Premium:            ${premium_result['premium_dollars']:,.2f}")
        print(f"  Premium (bps):      {premium_result['premium_bps']:.2f}")
        print(f"  Max Payout:         ${premium_result['max_payout_dollars']:,.2f}")
        print(f"  Implied Loss Ratio: {premium_result['implied_loss_ratio']:.1f}x")
        print(f"\n  Multiplier Breakdown:")
        mb = premium_result["multiplier_breakdown"]
        print(f"    Base Rate:              {mb['base_rate']}")
        print(f"    SRS Multiplier:         {mb['srs_multiplier']:.4f}")
        print(f"    Portfolio Risk Adj:     {mb['portfolio_risk_adjustment']:.4f}")
        print(f"    Liquidity Adj:          {mb['liquidity_adjustment']:.4f}")
        print(f"    Risk Loading:           {mb['risk_loading']}")
        print(f"    Duration Factor:        {mb['duration_factor']:.4f}")
        print(f"    Depth Factor:           {mb['depth_factor']:.4f}")
        print(f"    Combined Multiplier:    {mb['combined_multiplier']:.4f}")

    # ---- Test 4: Payout Profile ----
    print("\n\n--- TEST 4: estimate_payout_profile() ---\n")
    payout = estimate_payout_profile(1_000_000, 20.0)

    if "error" in payout:
        print(f"  ERROR: {payout['error']}")
        all_passed = False
    else:
        print(f"  Protection Level: {payout['protection_level_pct']}%")
        print(f"  Max Binary Payout: ${payout['max_binary_payout_dollars']:,.2f}")
        print(f"\n  {'Drawdown':>10} {'Loss':>14} {'Binary Payout':>15} {'Net Loss':>14}")
        print(f"  {'-'*8}   {'-'*12}   {'-'*13}   {'-'*12}")
        for row in payout["binary_payouts"]:
            print(
                f"  {row['drawdown_pct']:>8}%   "
                f"${row['portfolio_loss_dollars']:>11,.2f}   "
                f"${row['binary_payout_dollars']:>12,.2f}   "
                f"${row['net_loss_after_payout']:>11,.2f}"
            )

    # ---- Test 5: Full API Pricing ----
    print("\n\n--- TEST 5: price_protection() (API function) ---\n")
    api_result = price_protection(
        tickers=["SPY", "HYG", "TLT", "GLD", "BTC-USD"],
        weights=[0.40, 0.20, 0.20, 0.10, 0.10],
        notional=1_000_000,
        protection_level_pct=20.0,
        duration_days=90,
        period="1y",
    )

    if "error" in api_result:
        print(f"  ERROR: {api_result['error']}")
        all_passed = False
    else:
        print(f"  Premium:             ${api_result['premium_dollars']:,.2f}")
        print(f"  Premium (bps):       {api_result['premium_bps']:.2f}")
        print(f"  Annualized Premium:  ${api_result['annualized_premium_dollars']:,.2f}")
        print(f"  Max Payout:          ${api_result['max_payout_dollars']:,.2f}")
        print(f"  Crash Probability:   {api_result['historical_crash_probability']*100:.2f}%")
        print(f"  GSRI Used:           {api_result['gsri_used']:.1f}")
        print(f"  SRS Used:            {api_result['srs_used']:.1f}")
        print(f"  GSRI Multiplier:     {api_result['gsri_multiplier']:.4f}")
        print(f"  SRS Multiplier:      {api_result['srs_multiplier']:.4f}")
        print(f"  Portfolio Vol:       {api_result['portfolio_volatility_pct']:.2f}%")
        print(f"  Market Vol:          {api_result['market_volatility_pct']:.2f}%")
        print(f"  Risk Adjustment:     {api_result['portfolio_risk_adjustment']:.4f}")
        print(f"  Pricing Method:      {api_result['pricing_method']}")

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    if all_passed:
        print("STATUS: All tests passed. Pricing engine is working.")
    else:
        print("STATUS: Some tests failed. Check error messages above.")
    print("=" * 70)
