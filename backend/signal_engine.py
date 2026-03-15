"""
signal_engine.py — Systemic Risk Signal Detection Engine

FILE LOCATION: ~/Desktop/srx-platform/backend/signal_engine.py

PURPOSE:
    Transforms raw SRX metrics into actionable intelligence signals.
    Analyzes cross-asset indicators to detect regime shifts, liquidity
    deterioration, correlation spikes, and shock events in real-time.

    This module is a pure Python function with no Streamlit dependency.
    It can be tested independently and integrated into any frontend.

SIGNAL SCHEMA:
    Each signal is a dict with:
        id:        Unique hash (date + type) to prevent UI duplicates
        timestamp: ISO date string
        type:      Category name
        severity:  "Normal" | "Monitoring" | "Elevated" | "Critical"
        message:   1-sentence plain-English explanation
        metadata:  Dict of raw values that triggered the signal
"""

import hashlib
from datetime import datetime
import pandas as pd
import numpy as np


# =============================================================================
# SEVERITY LEVELS
# =============================================================================

NORMAL = "Normal"
MONITORING = "Monitoring"
ELEVATED = "Elevated"
CRITICAL = "Critical"


# =============================================================================
# SIGNAL DEFINITIONS
# =============================================================================

def _make_signal(sig_type: str, severity: str, message: str,
                 metadata: dict, timestamp=None) -> dict:
    """Create a signal dict with a unique ID based on date + type."""
    if timestamp is None:
        ts = datetime.now()
    elif isinstance(timestamp, str):
        ts = pd.to_datetime(timestamp).to_pydatetime()
    elif isinstance(timestamp, pd.Timestamp):
        ts = timestamp.to_pydatetime()
    else:
        ts = timestamp

    date_str = ts.strftime("%Y-%m-%d")
    sig_id = f"{date_str}_{sig_type.lower().replace(' ', '_')}"
    return {
        "id": sig_id,
        "timestamp": ts,
        "type": sig_type,
        "severity": severity,
        "message": message,
        "metadata": metadata,
    }


def _severity_for_gsri(gsri: float) -> str:
    """Map GSRI value to severity level."""
    if gsri >= 75:
        return CRITICAL
    elif gsri >= 50:
        return ELEVATED
    elif gsri >= 30:
        return MONITORING
    return NORMAL


# =============================================================================
# PRIMARY DRIVER DETECTION
# =============================================================================

_DRIVER_LABELS = {
    "correlation": "Cross-Asset Correlation",
    "volatility": "Volatility Regime",
    "liquidity": "Market Liquidity",
    "drawdown": "Tail Risk Momentum",
}

_DRIVER_WEIGHTS = {
    "volatility": 0.30,
    "correlation": 0.25,
    "drawdown": 0.25,
    "liquidity": 0.20,
}

_DRIVER_TIEBREAK = ["volatility", "correlation", "drawdown", "liquidity"]


def get_primary_driver(components: dict) -> str:
    """
    Identify which SRS component has the highest score.

    Tie-breaking: highest SRS methodology weight, then deterministic order.
    Always returns a single readable string.
    """
    # Map incoming component keys to canonical names
    key_map = {
        "correlation": "correlation",
        "cross_corr": "correlation",
        "C_t_correlation": "correlation",
        "volatility": "volatility",
        "equity_vol": "volatility",
        "V_t_volatility": "volatility",
        "liquidity": "liquidity",
        "L_t_liquidity": "liquidity",
        "drawdown": "drawdown",
        "tail": "drawdown",
        "M_t_drawdown": "drawdown",
        "credit_stress": "liquidity",  # credit stress proxies liquidity
    }

    canonical = {}
    for key, value in components.items():
        canon = key_map.get(key)
        if canon is not None:
            val = float(value) if value is not None else 0.0
            # Keep the highest score if multiple keys map to the same canonical
            canonical[canon] = max(canonical.get(canon, 0.0), val)

    if not canonical:
        return "Volatility Regime"  # safe default

    max_score = max(canonical.values())

    # Find all components tied at the max
    tied = [k for k, v in canonical.items() if v == max_score]

    if len(tied) == 1:
        return _DRIVER_LABELS[tied[0]]

    # Tie-break by SRS weight
    tied.sort(key=lambda k: _DRIVER_WEIGHTS.get(k, 0), reverse=True)
    best_weight = _DRIVER_WEIGHTS.get(tied[0], 0)
    still_tied = [k for k in tied if _DRIVER_WEIGHTS.get(k, 0) == best_weight]

    if len(still_tied) == 1:
        return _DRIVER_LABELS[still_tied[0]]

    # Final deterministic fallback
    for k in _DRIVER_TIEBREAK:
        if k in still_tied:
            return _DRIVER_LABELS[k]

    return _DRIVER_LABELS[tied[0]]


# =============================================================================
# GSRI TREND DETECTION
# =============================================================================

def get_gsri_trend(history_df) -> str:
    """
    Determine the short-term GSRI trend based on 5-day change.

    Returns: "Increasing", "Decreasing", or "Stable".
    """
    if not isinstance(history_df, pd.DataFrame):
        return "Stable"

    if "gsri" not in history_df.columns or len(history_df) < 6:
        return "Stable"

    change = _n_day_change(history_df["gsri"], 5)

    if change > 2:
        return "Increasing"
    elif change < -2:
        return "Decreasing"
    return "Stable"


# =============================================================================
# TREND HELPERS — vectorized pandas operations
# =============================================================================

def _n_day_change(series: pd.Series, n: int) -> float:
    """Compute the change over the last n values. Returns 0 if not enough data."""
    if len(series) < n + 1:
        return 0.0
    return float(series.iloc[-1] - series.iloc[-(n + 1)])


def _n_day_pct_change(series: pd.Series, n: int) -> float:
    """Compute the percentage change over the last n values."""
    if len(series) < n + 1:
        return 0.0
    past = series.iloc[-(n + 1)]
    if past == 0 or np.isnan(past):
        return 0.0
    return float((series.iloc[-1] - past) / past * 100)


# =============================================================================
# MAIN FUNCTION
# =============================================================================

def generate_systemic_signals(
    current_gsri: float,
    current_srs: float,
    components: dict,
    history_df: pd.DataFrame,
    shock_multiplier_active: bool,
) -> list:
    """
    Analyze cross-asset metrics to produce a list of actionable alerts.

    Parameters:
        current_gsri: Latest GSRI value (0-100).
        current_srs: Latest SRS value (0-100).
        components: Dict with keys like "correlation", "volatility",
                    "credit_stress", "tail" (each 0-100 scores).
        history_df: DataFrame with at least columns ["date", "gsri",
                    "correlation", "volatility", "credit", "tail", "shock"].
                    Minimum 5 rows for trend analysis.
        shock_multiplier_active: Whether the 1.25x shock is currently firing.

    Returns:
        List of signal dicts, sorted by severity (Critical first).
    """
    signals = []

    # Derive timestamp from the most recent date in market data
    if isinstance(history_df, pd.DataFrame) and len(history_df) > 0:
        if "date" in history_df.columns:
            last_date = history_df["date"].iloc[-1]
        elif hasattr(history_df.index, 'dtype') and np.issubdtype(history_df.index.dtype, np.datetime64):
            last_date = history_df.index[-1]
        else:
            last_date = datetime.now()
        market_ts = pd.to_datetime(last_date).to_pydatetime()
    else:
        market_ts = datetime.now()

    corr_score = components.get("correlation", 0)
    vol_score = components.get("volatility", 0)
    credit_score = components.get("credit_stress", 0)
    liq_score = components.get("V_t_liquidity", components.get("L_t_liquidity", 0))
    tail_score = components.get("tail", 0)

    # If we have SRS components with L_t, use that for liquidity
    # Otherwise approximate from the GSRI sub-scores
    if liq_score == 0 and "L_t_liquidity" in components:
        liq_score = components["L_t_liquidity"]

    has_history = isinstance(history_df, pd.DataFrame) and len(history_df) >= 5

    # ---- 1. SHOCK MULTIPLIER ACTIVATION ----
    if shock_multiplier_active:
        signals.append(_make_signal(
            sig_type="Shock Multiplier Activation",
            severity=CRITICAL,
            message=(
                "SHOCK DETECTED: Rapid drawdown/volatility acceleration "
                "triggered the 1.25× systemic multiplier. Immediate hedging "
                "review required."
            ),
            metadata={
                "gsri": current_gsri,
                "srs": current_srs,
                "multiplier": 1.25,
            },
            timestamp=market_ts,
        ))

    # ---- 2. CORRELATION SPIKE ----
    if has_history and "correlation" in history_df.columns:
        corr_5d_change = _n_day_change(history_df["correlation"], 5)

        if corr_score > 60 and corr_5d_change > 15:
            signals.append(_make_signal(
                sig_type="Correlation Spike",
                severity=ELEVATED,
                message=(
                    "Systemic coupling detected: Diversification benefits are "
                    "evaporating as cross-asset correlations surge."
                ),
                metadata={
                    "correlation_score": corr_score,
                    "corr_change_5d": round(corr_5d_change, 1),
                },
                timestamp=market_ts,
            ))
        elif corr_score > 50:
            signals.append(_make_signal(
                sig_type="Correlation Elevated",
                severity=MONITORING,
                message=(
                    "Cross-asset correlations are rising. Diversification "
                    "effectiveness is declining."
                ),
                metadata={"correlation_score": corr_score},
                timestamp=market_ts,
            ))

    # ---- 3. LIQUIDITY DETERIORATION ----
    # Use liquidity from SRS components if available, otherwise use credit as proxy
    effective_liq = liq_score if liq_score > 0 else credit_score * 0.8

    if effective_liq > 65:
        signals.append(_make_signal(
            sig_type="Liquidity Deterioration",
            severity=ELEVATED,
            message=(
                "Market depth thinning: Price impact per unit of volume is "
                "rising, indicating emerging liquidity fragility."
            ),
            metadata={
                "liquidity_score": round(effective_liq, 1),
                "source": "L_t" if liq_score > 0 else "credit_proxy",
            },
            timestamp=market_ts,
        ))
    elif effective_liq > 45:
        signals.append(_make_signal(
            sig_type="Liquidity Watch",
            severity=MONITORING,
            message=(
                "Liquidity conditions are tightening. Amihud illiquidity "
                "ratio is above normal range."
            ),
            metadata={"liquidity_score": round(effective_liq, 1)},
            timestamp=market_ts,
        ))

    # ---- 4. VOLATILITY REGIME SHIFT ----
    if has_history and "volatility" in history_df.columns:
        vol_3d_change = _n_day_change(history_df["volatility"], 3)

        if abs(vol_3d_change) > 20:
            direction = "up" if vol_3d_change > 0 else "down"
            sev = ELEVATED if vol_3d_change > 0 else MONITORING
            signals.append(_make_signal(
                sig_type="Volatility Regime Shift",
                severity=sev,
                message=(
                    f"Volatility regime shift ({direction}): Market participants "
                    f"are repricing tail risk rapidly. "
                    f"3-day vol score change: {vol_3d_change:+.1f} pts."
                ),
                metadata={
                    "volatility_score": vol_score,
                    "vol_change_3d": round(vol_3d_change, 1),
                    "direction": direction,
                },
                timestamp=market_ts,
            ))

    # ---- 5. CREDIT STRESS ----
    if has_history and "credit" in history_df.columns:
        credit_5d_change = _n_day_change(history_df["credit"], 5)

        if credit_score > 60 and credit_5d_change > 10:
            signals.append(_make_signal(
                sig_type="Credit Stress Widening",
                severity=ELEVATED,
                message=(
                    "Credit spreads are widening: High-yield stress is rising "
                    "relative to safe-haven Treasuries, signaling risk repricing."
                ),
                metadata={
                    "credit_score": credit_score,
                    "credit_change_5d": round(credit_5d_change, 1),
                },
                timestamp=market_ts,
            ))

    # ---- 6. GSRI THRESHOLD CROSSINGS ----
    if has_history and "gsri" in history_df.columns and len(history_df) >= 2:
        prev_gsri = history_df["gsri"].iloc[-2]

        # Crossed into Elevated
        if current_gsri >= 50 and prev_gsri < 50:
            signals.append(_make_signal(
                sig_type="GSRI Elevated Breach",
                severity=ELEVATED,
                message=(
                    "GSRI has crossed into the Elevated zone (50+). "
                    "Hedging Entry Zone — portfolio protection is warranted."
                ),
                metadata={"gsri": current_gsri, "prev_gsri": round(prev_gsri, 1)},
                timestamp=market_ts,
            ))

        # Crossed into Critical
        if current_gsri >= 75 and prev_gsri < 75:
            signals.append(_make_signal(
                sig_type="GSRI Critical Breach",
                severity=CRITICAL,
                message=(
                    "GSRI has crossed into the Critical zone (75+). "
                    "Systemic failure conditions — emergency risk controls active."
                ),
                metadata={"gsri": current_gsri, "prev_gsri": round(prev_gsri, 1)},
                timestamp=market_ts,
            ))

    # ---- 7. DRAWDOWN ACCELERATION ----
    if has_history and "tail" in history_df.columns:
        tail_3d_change = _n_day_change(history_df["tail"], 3)

        if tail_score > 55 and tail_3d_change > 15:
            signals.append(_make_signal(
                sig_type="Drawdown Acceleration",
                severity=ELEVATED,
                message=(
                    "Drawdown is accelerating: Treasury volatility and duration "
                    "stress are intensifying across safe-haven assets."
                ),
                metadata={
                    "tail_score": tail_score,
                    "tail_change_3d": round(tail_3d_change, 1),
                },
                timestamp=market_ts,
            ))

    # ---- 8. OVERALL REGIME STATUS (always present) ----
    if current_gsri < 30 and not signals:
        signals.append(_make_signal(
            sig_type="System Normal",
            severity=NORMAL,
            message=(
                "All systemic indicators within normal range. "
                "No actionable signals detected."
            ),
            metadata={"gsri": current_gsri, "srs": current_srs},
            timestamp=market_ts,
        ))

    # Sort: Critical first, then Elevated, Monitoring, Normal
    severity_order = {CRITICAL: 0, ELEVATED: 1, MONITORING: 2, NORMAL: 3}
    signals.sort(key=lambda s: severity_order.get(s["severity"], 9))

    return signals


# =============================================================================
# UI HELPER
# =============================================================================

def get_severity_color(severity: str) -> dict:
    """
    Return color scheme for a severity level.
    Usable by any frontend (Streamlit, HTML, terminal).
    """
    return {
        CRITICAL:   {"bg": "#3d1212", "border": "#b83232", "text": "#f5a0a0", "icon": "🔴"},
        ELEVATED:   {"bg": "#3d2e12", "border": "#c49032", "text": "#f5d5a0", "icon": "🟠"},
        MONITORING: {"bg": "#12253d", "border": "#4a7ca0", "text": "#a0c8f5", "icon": "🔵"},
        NORMAL:     {"bg": "#123d1a", "border": "#4a7c59", "text": "#a0f5b0", "icon": "🟢"},
    }.get(severity, {"bg": "#1b2231", "border": "#2d3748", "text": "#94a3b8", "icon": "⚪"})


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Signal Engine — Unit Test")
    print("=" * 60)

    # Simulate a stressed market
    test_history = pd.DataFrame({
        "date": pd.date_range("2025-03-01", periods=10, freq="B"),
        "gsri": [25, 28, 32, 38, 45, 52, 58, 63, 68, 72],
        "correlation": [30, 32, 35, 40, 48, 55, 58, 62, 65, 70],
        "volatility": [20, 22, 25, 30, 40, 55, 58, 60, 62, 65],
        "credit": [15, 18, 22, 28, 35, 42, 48, 52, 55, 58],
        "tail": [10, 12, 15, 20, 28, 35, 40, 45, 50, 55],
        "shock": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.25, 1.25],
    })

    signals = generate_systemic_signals(
        current_gsri=72.0,
        current_srs=68.0,
        components={
            "correlation": 70.0,
            "volatility": 65.0,
            "credit_stress": 58.0,
            "tail": 55.0,
        },
        history_df=test_history,
        shock_multiplier_active=True,
    )

    print(f"\nGenerated {len(signals)} signals:\n")
    for s in signals:
        colors = get_severity_color(s["severity"])
        print(f"  {colors['icon']} [{s['severity']:>10}] {s['type']}")
        print(f"    {s['message']}")
        print(f"    meta: {s['metadata']}")
        print()

    # Test calm market
    calm_history = pd.DataFrame({
        "date": pd.date_range("2025-03-01", periods=10, freq="B"),
        "gsri": [18, 19, 20, 19, 18, 20, 21, 19, 18, 20],
        "correlation": [15, 16, 15, 14, 16, 15, 14, 15, 16, 15],
        "volatility": [12, 11, 13, 12, 11, 12, 13, 12, 11, 12],
        "credit": [8, 9, 8, 9, 8, 9, 8, 9, 8, 9],
        "tail": [5, 6, 5, 6, 5, 6, 5, 6, 5, 6],
        "shock": [1.0] * 10,
    })

    calm_signals = generate_systemic_signals(
        current_gsri=20.0, current_srs=15.0,
        components={"correlation": 15, "volatility": 12, "credit_stress": 9, "tail": 6},
        history_df=calm_history, shock_multiplier_active=False,
    )
    print(f"Calm market: {len(calm_signals)} signal(s)")
    for s in calm_signals:
        print(f"  {get_severity_color(s['severity'])['icon']} {s['type']}: {s['message']}")

    print(f"\n{'=' * 60}")
    print("PASSED")
