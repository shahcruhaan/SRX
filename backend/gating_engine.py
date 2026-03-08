"""
gating_engine.py — Dynamic Gating Logic for the SRX Platform

FILE LOCATION: Save this file as:
    ~/Desktop/srx-platform/backend/gating_engine.py

ARCHITECTURAL DECISION:
    This is a NEW DEDICATED FILE for the gating logic. Previously, gating
    lived inside clearinghouse_simulation.py. It now has its own module
    because gating is used by THREE different parts of the platform:
      1. pricing_engine.py — adjusts premiums based on the gate state
      2. dashboard.py — displays the gate level and restrictions
      3. clearinghouse_simulation.py — triggers contingent capital calls

    Having gating in its own file means any module can import it without
    pulling in the entire clearinghouse simulation.

    The old evaluate_gating() in clearinghouse_simulation.py still works —
    it now delegates to this module, so main.py and the dashboard don't
    need any changes.

WHAT THIS MODULE DOES:
    Takes the current SRS (Systemic Risk Score) and returns the platform's
    operational risk state, including:
      - Gate level (0–3)
      - Whether new contracts are allowed
      - Whether contingent capital is activated
      - The margin multiplier
      - A full description of active restrictions

GATING RULES (SRS-based):
    SRS ≤ 70:  Gate 0 — NORMAL
               Everything open. Standard margin requirements.

    SRS > 70:  Gate 1 — ELEVATED
               Margin requirements increased. Enhanced monitoring.

    SRS > 85:  Gate 2 — RESTRICTED
               New contracts blocked. Only risk-reducing trades.

    SRS > 95:  Gate 3 — CRITICAL
               Contingent capital calls triggered. Forced de-leveraging.

MAIN FUNCTIONS:
    evaluate_srs_gate(srs)          → Core SRS-based gating decision
    get_margin_multiplier(srs)      → Continuous margin multiplier from SRS
    get_gate_restrictions(level)    → Detailed restrictions for a gate level
    evaluate_gating(gsri_score, ..) → Backward-compatible wrapper for dashboard
"""

import numpy as np


# =============================================================================
# CONSTANTS
# =============================================================================

# SRS thresholds for each gate level.
# These are the boundaries where the platform changes its operational state.
GATE_THRESHOLD_ELEVATED = 70    # SRS > 70 → Gate 1
GATE_THRESHOLD_RESTRICTED = 85  # SRS > 85 → Gate 2
GATE_THRESHOLD_CRITICAL = 95    # SRS > 95 → Gate 3


# =============================================================================
# CORE SRS-BASED GATING
# =============================================================================

def evaluate_srs_gate(
    srs: float,
    portfolio_pri: float = None,
    recent_volatility_pct: float = None,
) -> dict:
    """
    Evaluate the platform's operational gate level based on the current SRS.

    This is the core gating function. It applies the SRS-based rules:
      SRS ≤ 70:  Gate 0 (Normal)
      SRS > 70:  Gate 1 (Elevated) — margins increased
      SRS > 85:  Gate 2 (Restricted) — new contracts blocked
      SRS > 95:  Gate 3 (Critical) — contingent capital calls

    Escalation overrides:
      If portfolio_pri > 80, escalate by one level.
      If recent_volatility_pct > 50, escalate by one level.
      These ensure that even if the broad SRS is moderate, an extremely
      risky portfolio or extreme volatility still triggers protections.

    Parameters:
        srs: Current Systemic Risk Score (0–100).
             This is the primary input. It comes from gsri_engine.py's
             compute_srs_series() or calculate_gsri()["srs_current"].
        portfolio_pri: Optional — the portfolio's PRI score (0–100).
                       If provided and > 80, escalates the gate by 1 level.
        recent_volatility_pct: Optional — recent annualized volatility (%).
                               If provided and > 50%, escalates by 1 level.

    Returns:
        Dictionary with:
          - gate_level: Int 0–3
          - risk_state: Human-readable state name
          - margin_multiplier: How much to multiply margin requirements
          - new_contracts_allowed: Bool — can new positions be opened?
          - contingent_capital_activated: Bool — are emergency capital calls live?
          - redemptions_allowed: Bool — can members withdraw?
          - forced_deleveraging: Bool — is forced position reduction active?
          - actions: List of active restrictions/actions
          - description: Overall situation description
          - color: Color code for UI display
          - srs_input: The SRS value used
          - escalation_applied: Whether PRI or vol overrides increased the level
    """
    try:
        srs = float(srs)
        srs = max(0.0, min(100.0, srs))

        # ---- Determine base gate level from SRS ----
        if srs <= GATE_THRESHOLD_ELEVATED:
            gate_level = 0
        elif srs <= GATE_THRESHOLD_RESTRICTED:
            gate_level = 1
        elif srs <= GATE_THRESHOLD_CRITICAL:
            gate_level = 2
        else:
            gate_level = 3

        base_level = gate_level
        escalation_reasons = []

        # ---- Apply escalation overrides ----
        if portfolio_pri is not None and portfolio_pri > 80 and gate_level < 3:
            gate_level += 1
            escalation_reasons.append(
                f"Portfolio PRI ({portfolio_pri:.1f}) exceeds 80 — escalated by 1 level"
            )

        if recent_volatility_pct is not None and recent_volatility_pct > 50 and gate_level < 3:
            gate_level += 1
            escalation_reasons.append(
                f"Recent volatility ({recent_volatility_pct:.1f}%) exceeds 50% — escalated by 1 level"
            )

        # Clamp to 0–3.
        gate_level = max(0, min(3, gate_level))

        # ---- Get the full restrictions for this level ----
        restrictions = get_gate_restrictions(gate_level)

        # ---- Compute the continuous margin multiplier ----
        margin_info = get_margin_multiplier(srs)

        # Use the higher of the level-based or continuous multiplier.
        final_margin = max(restrictions["margin_multiplier"], margin_info["multiplier"])

        # ---- Build the result ----
        result = {
            # Core gating state.
            "gate_level": gate_level,
            "risk_state": restrictions["risk_state"],
            "margin_multiplier": round(final_margin, 4),
            "new_contracts_allowed": restrictions["new_contracts_allowed"],
            "contingent_capital_activated": restrictions["contingent_capital_activated"],
            "redemptions_allowed": restrictions["redemptions_allowed"],
            "forced_deleveraging": restrictions["forced_deleveraging"],

            # Details.
            "actions": restrictions["actions"],
            "description": restrictions["description"],
            "color": restrictions["color"],

            # Inputs and diagnostics.
            "srs_input": round(srs, 2),
            "pri_input": round(portfolio_pri, 2) if portfolio_pri is not None else None,
            "volatility_input": (
                round(recent_volatility_pct, 2) if recent_volatility_pct is not None else None
            ),
            "base_gate_level": base_level,
            "escalation_applied": gate_level > base_level,
            "escalation_reasons": escalation_reasons,
            "margin_detail": margin_info,

            # Backward-compatible aliases (used by the dashboard).
            "level": gate_level,
            "label": restrictions["risk_state"],
        }

        return result

    except Exception as error:
        return {
            "error": (
                f"Gating evaluation failed: {error}\n"
                f"Make sure srs is a number between 0 and 100."
            )
        }


# =============================================================================
# MARGIN MULTIPLIER (continuous)
# =============================================================================

def get_margin_multiplier(srs: float) -> dict:
    """
    Calculate a continuous margin multiplier based on the SRS.

    Unlike the discrete gate levels (which jump at 70/85/95), the margin
    multiplier increases smoothly as SRS rises. This ensures that margins
    gradually tighten even within a gate level.

    Formula:
        SRS ≤ 50:  multiplier = 1.0 (no increase)
        SRS 50–70: multiplier = 1.0 + (SRS - 50) / 50 × 0.25
                   (linear ramp from 1.0 to 1.10)
        SRS 70–85: multiplier = 1.10 + (SRS - 70) / 15 × 0.40
                   (steeper ramp from 1.10 to 1.50)
        SRS 85–95: multiplier = 1.50 + (SRS - 85) / 10 × 0.50
                   (steep ramp from 1.50 to 2.00)
        SRS > 95:  multiplier = 2.0 + (SRS - 95) / 5 × 1.0
                   (aggressive ramp from 2.0 to 3.0)

    Parameters:
        srs: Current Systemic Risk Score (0–100).

    Returns:
        Dictionary with the multiplier and the SRS zone.
    """
    try:
        srs = max(0.0, min(100.0, float(srs)))

        if srs <= 50:
            multiplier = 1.0
            zone = "Normal — no margin increase"
        elif srs <= 70:
            multiplier = 1.0 + (srs - 50) / 50 * 0.25
            zone = "Pre-caution — slight margin increase"
        elif srs <= 85:
            multiplier = 1.10 + (srs - 70) / 15 * 0.40
            zone = "Elevated — margins tightening"
        elif srs <= 95:
            multiplier = 1.50 + (srs - 85) / 10 * 0.50
            zone = "Restricted — margins significantly increased"
        else:
            multiplier = 2.0 + (srs - 95) / 5 * 1.0
            zone = "Critical — emergency margin levels"

        return {
            "multiplier": round(multiplier, 4),
            "srs": round(srs, 2),
            "zone": zone,
            "increase_pct": round((multiplier - 1.0) * 100, 1),
        }

    except Exception as error:
        return {"multiplier": 1.0, "srs": 0, "zone": "Error — defaulted to 1.0", "increase_pct": 0}


# =============================================================================
# GATE LEVEL RESTRICTIONS
# =============================================================================

def get_gate_restrictions(level: int) -> dict:
    """
    Get the full set of restrictions for a given gate level.

    Parameters:
        level: Gate level (0, 1, 2, or 3).

    Returns:
        Dictionary with all restrictions and their descriptions.
    """
    configs = {
        # ---- Gate 0: Normal ----
        0: {
            "risk_state": "Normal",
            "color": "green",
            "margin_multiplier": 1.0,
            "new_contracts_allowed": True,
            "contingent_capital_activated": False,
            "redemptions_allowed": True,
            "forced_deleveraging": False,
            "description": (
                "All operations running normally. SRS is within acceptable bounds. "
                "Standard margin requirements apply."
            ),
            "actions": [],
        },

        # ---- Gate 1: Elevated ----
        1: {
            "risk_state": "Elevated",
            "color": "yellow",
            "margin_multiplier": 1.25,
            "new_contracts_allowed": True,
            "contingent_capital_activated": False,
            "redemptions_allowed": True,
            "forced_deleveraging": False,
            "description": (
                "Systemic risk is elevated (SRS > 70). Margin requirements increased. "
                "Enhanced monitoring is active. All trading still permitted."
            ),
            "actions": [
                "Margin requirements increased by 25% (minimum)",
                "Enhanced real-time risk monitoring activated",
                "Risk reports generated every hour instead of daily",
                "Member risk notifications sent",
                "Stress test frequency increased",
            ],
        },

        # ---- Gate 2: Restricted ----
        2: {
            "risk_state": "Restricted",
            "color": "orange",
            "margin_multiplier": 1.50,
            "new_contracts_allowed": False,
            "contingent_capital_activated": False,
            "redemptions_allowed": True,
            "forced_deleveraging": False,
            "description": (
                "Systemic risk is high (SRS > 85). New protection contracts are BLOCKED. "
                "Only risk-reducing trades are permitted. Members may still redeem."
            ),
            "actions": [
                "Margin requirements increased by 50% (minimum)",
                "NEW protection contracts are BLOCKED",
                "Only risk-reducing trades permitted",
                "Continuous real-time risk monitoring",
                "Member risk notifications sent every 30 minutes",
                "Regulatory notifications sent",
                "Emergency risk committee on standby",
            ],
        },

        # ---- Gate 3: Critical ----
        3: {
            "risk_state": "Critical",
            "color": "red",
            "margin_multiplier": 2.0,
            "new_contracts_allowed": False,
            "contingent_capital_activated": True,
            "redemptions_allowed": False,
            "forced_deleveraging": True,
            "description": (
                "SYSTEMIC CRISIS (SRS > 95). Contingent capital calls ACTIVATED. "
                "Redemptions frozen. Forced de-leveraging in progress. "
                "All available emergency measures deployed."
            ),
            "actions": [
                "Margin requirements DOUBLED (minimum)",
                "All new contracts BLOCKED",
                "CONTINGENT CAPITAL CALLS ACTIVATED — members must post additional capital",
                "Redemptions FROZEN (minimum 48-hour hold)",
                "Forced de-leveraging of over-exposed positions",
                "Emergency risk committee CONVENED",
                "Regulator notifications sent with full position data",
                "Default waterfall pre-staged for potential member failure",
                "Cross-platform communication with other clearinghouses",
            ],
        },
    }

    level = max(0, min(3, int(level)))
    return configs[level]


# =============================================================================
# BACKWARD-COMPATIBLE WRAPPER
# =============================================================================

def evaluate_gating(
    gsri_score: float,
    portfolio_pri: float = None,
    recent_volatility_pct: float = None,
) -> dict:
    """
    Backward-compatible gating function.

    This wraps evaluate_srs_gate() and maps the GSRI score to an approximate
    SRS score for the evaluation. The dashboard and main.py call this function
    with a GSRI score, so we convert GSRI → approximate SRS before applying
    the SRS-based gating rules.

    GSRI → SRS approximation:
        The GSRI and SRS measure different things but are correlated.
        In calm markets, SRS ≈ GSRI. In stressed markets, SRS tends to
        run slightly higher than GSRI because SRS includes liquidity and
        drawdown acceleration signals that GSRI doesn't.

        Conversion: SRS_approx = GSRI × 1.1 (clamped to 0–100)

    Parameters:
        gsri_score: Current GSRI (0–100). Mapped to approximate SRS.
        portfolio_pri: Optional PRI score for escalation.
        recent_volatility_pct: Optional volatility for escalation.

    Returns:
        Same structure as evaluate_srs_gate(), plus all backward-compatible keys
        that the dashboard expects (level, label, color, margin_multiplier,
        new_positions_allowed, redemptions_allowed, forced_deleveraging,
        actions, description, gsri_input).
    """
    try:
        # Convert GSRI to approximate SRS.
        gsri = float(gsri_score)
        approximate_srs = min(100.0, gsri * 1.1)

        # Run the SRS-based gating.
        result = evaluate_srs_gate(approximate_srs, portfolio_pri, recent_volatility_pct)

        if "error" in result:
            return result

        # Add backward-compatible keys that the dashboard reads.
        # The dashboard reads "new_positions_allowed" not "new_contracts_allowed".
        result["new_positions_allowed"] = result["new_contracts_allowed"]
        result["gsri_input"] = round(gsri, 2)

        return result

    except Exception as error:
        return {
            "error": (
                f"Gating evaluation failed: {error}\n"
                f"Make sure gsri_score is a number between 0 and 100."
            )
        }


# =============================================================================
# INTEGRATION HELPER — for pricing_engine.py
# =============================================================================

def get_gating_premium_adjustment(srs: float) -> dict:
    """
    Get a premium adjustment factor based on the current gate state.

    This function is designed to be called by pricing_engine.py to
    adjust premiums based on the gating state. When the platform is
    in a higher gate state, premiums should increase because the
    system is under more stress.

    Premium adjustment logic:
        Gate 0 (Normal):     1.0x  — no adjustment
        Gate 1 (Elevated):   1.15x — 15% surcharge
        Gate 2 (Restricted): 1.40x — 40% surcharge
        Gate 3 (Critical):   2.00x — doubled (if new contracts were allowed)

    Note: At Gate 2 and Gate 3, new contracts are blocked, so this
    adjustment would only apply if the gate was overridden or if
    pricing existing renewals.

    Parameters:
        srs: Current Systemic Risk Score (0–100).

    Returns:
        Dictionary with the adjustment factor and gate state.
    """
    try:
        gate_result = evaluate_srs_gate(srs)

        if "error" in gate_result:
            return {"adjustment": 1.0, "gate_level": 0, "new_contracts_allowed": True}

        adjustments = {0: 1.0, 1: 1.15, 2: 1.40, 3: 2.0}
        level = gate_result["gate_level"]
        adjustment = adjustments.get(level, 1.0)

        return {
            "adjustment": round(adjustment, 4),
            "gate_level": level,
            "risk_state": gate_result["risk_state"],
            "new_contracts_allowed": gate_result["new_contracts_allowed"],
            "margin_multiplier": gate_result["margin_multiplier"],
            "description": (
                f"Gate {level} ({gate_result['risk_state']}): "
                f"premium adjustment {adjustment:.2f}x"
            ),
        }

    except Exception as error:
        return {"adjustment": 1.0, "gate_level": 0, "new_contracts_allowed": True}


# =============================================================================
# INTEGRATION HELPER — for clearinghouse_simulation.py
# =============================================================================

def should_activate_contingent_capital(srs: float) -> dict:
    """
    Determine whether contingent capital calls should be activated.

    This function is designed to be called by clearinghouse_simulation.py
    to decide whether to draw from Layer 3 (Defaulter Contingent Capital)
    proactively, rather than waiting for a default event.

    Parameters:
        srs: Current Systemic Risk Score (0–100).

    Returns:
        Dictionary with activation status and details.
    """
    try:
        gate_result = evaluate_srs_gate(srs)

        if "error" in gate_result:
            return {"activated": False, "gate_level": 0}

        activated = gate_result["contingent_capital_activated"]

        return {
            "activated": activated,
            "gate_level": gate_result["gate_level"],
            "risk_state": gate_result["risk_state"],
            "srs": round(float(srs), 2),
            "description": (
                "Contingent capital calls are ACTIVE. Members must post additional capital."
                if activated else
                "Contingent capital calls are not active at current risk levels."
            ),
        }

    except Exception as error:
        return {"activated": False, "gate_level": 0}


# =============================================================================
# EXAMPLE USAGE — Run this file directly to test
# =============================================================================

if __name__ == "__main__":
    """
    Run this file directly to test the gating engine:
        cd ~/Desktop/srx-platform
        source venv/bin/activate
        python3 -m backend.gating_engine
    """

    print("=" * 70)
    print("SRX PLATFORM — Gating Engine Test")
    print("=" * 70)

    all_passed = True

    # ---- Test 1: SRS-based gating at every threshold ----
    print("\n--- TEST 1: evaluate_srs_gate() at key SRS levels ---\n")
    print(f"  {'SRS':>5}  {'Gate':>5}  {'State':<12} {'Margin':>8}  "
          f"{'NewContr':>8}  {'ContCap':>8}  {'Redemp':>8}")
    print(f"  {'-'*3}    {'-'*3}   {'-'*10}   {'-'*6}    {'-'*6}    {'-'*6}    {'-'*6}")

    for srs in [0, 30, 50, 65, 70, 71, 80, 85, 86, 90, 95, 96, 100]:
        result = evaluate_srs_gate(srs)
        if "error" in result:
            print(f"  {srs:>5}  ERROR: {result['error']}")
            all_passed = False
        else:
            print(
                f"  {srs:>5}  "
                f"  {result['gate_level']:>3}   "
                f"{result['risk_state']:<12} "
                f"{result['margin_multiplier']:>7.2f}x  "
                f"{'✓' if result['new_contracts_allowed'] else '✗':>8}  "
                f"{'ACTIVE' if result['contingent_capital_activated'] else '—':>8}  "
                f"{'✓' if result['redemptions_allowed'] else '✗':>8}"
            )

    # ---- Test 2: Continuous margin multiplier ----
    print("\n\n--- TEST 2: get_margin_multiplier() across SRS range ---\n")
    for srs in [0, 25, 50, 60, 70, 75, 80, 85, 90, 95, 98, 100]:
        mm = get_margin_multiplier(srs)
        bar_len = int(mm["multiplier"] * 10)
        bar = "█" * bar_len
        print(f"  SRS={srs:>3}: {mm['multiplier']:.2f}x (+{mm['increase_pct']:>5.1f}%)  {bar}")

    # ---- Test 3: Escalation override ----
    print("\n\n--- TEST 3: Escalation with high PRI ---\n")
    base = evaluate_srs_gate(65)  # SRS 65 → normally Gate 0
    escalated = evaluate_srs_gate(65, portfolio_pri=85)  # PRI 85 → escalate to Gate 1

    print(f"  SRS=65, no PRI:     Gate {base['gate_level']} ({base['risk_state']})")
    print(f"  SRS=65, PRI=85:     Gate {escalated['gate_level']} ({escalated['risk_state']})")
    if escalated["escalation_applied"]:
        for reason in escalated["escalation_reasons"]:
            print(f"    Reason: {reason}")

    # ---- Test 4: Backward-compatible evaluate_gating() ----
    print("\n\n--- TEST 4: evaluate_gating() (backward compat) ---\n")
    for gsri in [20, 50, 70, 85]:
        compat = evaluate_gating(gsri)
        if "error" in compat:
            print(f"  GSRI={gsri}: ERROR — {compat['error']}")
            all_passed = False
        else:
            print(
                f"  GSRI={gsri:>3} (→SRS≈{gsri*1.1:.0f}): "
                f"Gate {compat['level']} ({compat['label']}), "
                f"margin={compat['margin_multiplier']:.2f}x, "
                f"new_pos={'✓' if compat['new_positions_allowed'] else '✗'}, "
                f"color={compat['color']}"
            )

    # ---- Test 5: Premium adjustment for pricing ----
    print("\n\n--- TEST 5: get_gating_premium_adjustment() ---\n")
    for srs in [30, 60, 75, 90, 97]:
        adj = get_gating_premium_adjustment(srs)
        print(
            f"  SRS={srs:>3}: premium adj={adj['adjustment']:.2f}x, "
            f"gate={adj['gate_level']}, "
            f"new_contracts={'✓' if adj['new_contracts_allowed'] else '✗'}"
        )

    # ---- Test 6: Contingent capital activation ----
    print("\n\n--- TEST 6: should_activate_contingent_capital() ---\n")
    for srs in [50, 70, 85, 95, 98]:
        cc = should_activate_contingent_capital(srs)
        status = "🔴 ACTIVE" if cc["activated"] else "🟢 Inactive"
        print(f"  SRS={srs:>3}: {status} (Gate {cc['gate_level']})")

    # ---- Test 7: Full Gate 3 detail ----
    print("\n\n--- TEST 7: Gate 3 full detail (SRS=97) ---\n")
    critical = evaluate_srs_gate(97)
    if "error" not in critical:
        print(f"  Gate Level:      {critical['gate_level']}")
        print(f"  Risk State:      {critical['risk_state']}")
        print(f"  Margin:          {critical['margin_multiplier']:.2f}x")
        print(f"  New Contracts:   {'Allowed' if critical['new_contracts_allowed'] else 'BLOCKED'}")
        print(f"  Contingent Cap:  {'ACTIVATED' if critical['contingent_capital_activated'] else 'Inactive'}")
        print(f"  Redemptions:     {'Allowed' if critical['redemptions_allowed'] else 'FROZEN'}")
        print(f"  Forced Delev:    {'ACTIVE' if critical['forced_deleveraging'] else 'Inactive'}")
        print(f"\n  Active Restrictions:")
        for action in critical["actions"]:
            print(f"    • {action}")

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    if all_passed:
        print("STATUS: All tests passed. Gating engine is working.")
    else:
        print("STATUS: Some tests failed. Check error messages above.")
    print("=" * 70)
