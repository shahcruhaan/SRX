"""
clearinghouse_simulation.py — Default Waterfall and Dynamic Gating

FILE LOCATION: Save this file as:
    ~/Desktop/srx-platform/backend/clearinghouse_simulation.py

WHAT THIS MODULE DOES:

    1. DEFAULT WATERFALL SIMULATION:
       When a clearing member defaults (can't pay what they owe), the SRX
       clearinghouse absorbs losses through a 5-layer waterfall. Losses
       flow from Layer 1 down to Layer 5, and each layer absorbs what it
       can before passing the remainder to the next layer.

       The five layers, in order:

         Layer 1 — Defaulter Initial Margin:
                   Collateral the defaulting member posted up front.
                   This is the first line of defense and should absorb
                   most normal-sized losses.

         Layer 2 — Defaulter Default Fund Contribution:
                   The defaulter's share of the shared guarantee fund.
                   Burned before touching anyone else's money.

         Layer 3 — Defaulter Contingent Capital:
                   Additional callable capital from the defaulter (if any).
                   A buffer before mutualized losses begin.

         Layer 4 — Mutualized Default Fund:
                   The combined default fund contributions of all
                   NON-defaulting members. This is where losses start
                   to affect innocent parties.

         Layer 5 — SRX Clearinghouse Capital:
                   The clearinghouse's own equity / "skin in the game."
                   If this is breached, the system has failed.

       If all five layers are exhausted, the remaining loss is
       "unabsorbed" — a catastrophic failure requiring external
       intervention (government bailout, wind-down, etc.).

    2. STRESS TEST BY EVENT MAGNITUDE:
       run_stress_test(event_magnitude) takes a hypothetical loss amount
       (e.g., $100M, $500M, $1B) and runs it through the waterfall,
       reporting the status of each layer.

    3. DYNAMIC GATING:
       Automatic restrictions that activate when systemic risk gets too high.
       Four gate levels (0-3) progressively restrict platform activity.

MAIN FUNCTIONS:
    define_waterfall_layers()       → Build the 5-layer waterfall config
    process_waterfall()             → Run a loss through the waterfall layers
    run_stress_test(event_magnitude)→ Full stress test with status reporting
    simulate_default_waterfall()    → API-compatible (backward compat for dashboard)
    build_waterfall_chart_data()    → Data formatted for Plotly visualization
    evaluate_gating()               → Dynamic gating logic (backward compat)

BACKWARD COMPATIBILITY:
    simulate_default_waterfall() and evaluate_gating() are imported by:
      - backend/main.py (the /waterfall and /gating endpoints)
      - frontend/dashboard.py (renders waterfall chart and gating status)
    All return keys are preserved.
"""

import numpy as np
import pandas as pd


# =============================================================================
# CONSTANTS — Default waterfall layer sizes
# =============================================================================

# These are the default dollar amounts for each waterfall layer.
# In a real system, these would be calculated from member positions and
# margin models. Here they represent a mid-sized clearinghouse.

DEFAULT_LAYER_SIZES = {
    "defaulter_initial_margin": 200_000_000,       # $200M
    "defaulter_default_fund": 50_000_000,           # $50M
    "defaulter_contingent_capital": 30_000_000,     # $30M
    "mutualized_default_fund": 500_000_000,         # $500M
    "srx_clearinghouse_capital": 150_000_000,       # $150M
}


# =============================================================================
# WATERFALL LAYER DEFINITIONS
# =============================================================================

def define_waterfall_layers(
    defaulter_initial_margin: float = None,
    defaulter_default_fund: float = None,
    defaulter_contingent_capital: float = None,
    mutualized_default_fund: float = None,
    srx_clearinghouse_capital: float = None,
) -> list:
    """
    Build the ordered list of waterfall layers with their balances.

    Each layer is a dictionary with:
      - layer: Layer number (1–5)
      - name: Human-readable name
      - short_name: Abbreviation for charts
      - description: What this layer represents
      - available: Dollar amount available in this layer

    Parameters:
        Each parameter overrides the default size for that layer.
        If None, uses the defaults from DEFAULT_LAYER_SIZES.

    Returns:
        A list of 5 layer dictionaries, in waterfall order.
    """
    return [
        {
            "layer": 1,
            "name": "Defaulter Initial Margin",
            "short_name": "DIM",
            "description": (
                "Collateral posted by the defaulting member when they entered "
                "their positions. This is the first loss buffer and should "
                "absorb most normal-sized defaults."
            ),
            "available": (
                defaulter_initial_margin
                if defaulter_initial_margin is not None
                else DEFAULT_LAYER_SIZES["defaulter_initial_margin"]
            ),
        },
        {
            "layer": 2,
            "name": "Defaulter Default Fund Contribution",
            "short_name": "DDF",
            "description": (
                "The defaulting member's share of the shared guarantee fund. "
                "Burned before touching any other member's contributions."
            ),
            "available": (
                defaulter_default_fund
                if defaulter_default_fund is not None
                else DEFAULT_LAYER_SIZES["defaulter_default_fund"]
            ),
        },
        {
            "layer": 3,
            "name": "Defaulter Contingent Capital",
            "short_name": "DCC",
            "description": (
                "Additional callable capital from the defaulter. This is money "
                "the defaulter agreed to provide on demand but hadn't yet posted."
            ),
            "available": (
                defaulter_contingent_capital
                if defaulter_contingent_capital is not None
                else DEFAULT_LAYER_SIZES["defaulter_contingent_capital"]
            ),
        },
        {
            "layer": 4,
            "name": "Mutualized Default Fund",
            "short_name": "MDF",
            "description": (
                "The combined default fund contributions of all non-defaulting "
                "members. When losses reach this layer, innocent members begin "
                "to absorb losses — a critical escalation point."
            ),
            "available": (
                mutualized_default_fund
                if mutualized_default_fund is not None
                else DEFAULT_LAYER_SIZES["mutualized_default_fund"]
            ),
        },
        {
            "layer": 5,
            "name": "SRX Clearinghouse Capital",
            "short_name": "SRX",
            "description": (
                "The clearinghouse's own equity and reserves. If this layer is "
                "breached, the entire clearinghouse structure has failed and "
                "external intervention is required."
            ),
            "available": (
                srx_clearinghouse_capital
                if srx_clearinghouse_capital is not None
                else DEFAULT_LAYER_SIZES["srx_clearinghouse_capital"]
            ),
        },
    ]


# =============================================================================
# CORE WATERFALL PROCESSING
# =============================================================================

def process_waterfall(layers: list, loss_amount: float) -> dict:
    """
    Run a loss through the waterfall layers in order.

    For each layer, this function:
      1. Checks how much capacity the layer has
      2. Absorbs as much of the remaining loss as possible
      3. Determines the layer's status:
         - INTACT: No loss reached this layer
         - PARTIALLY DEPLETED: Some but not all capacity used
         - EXHAUSTED: Entire layer wiped out
      4. Passes any remaining loss to the next layer

    Parameters:
        layers: List of layer dictionaries from define_waterfall_layers().
        loss_amount: Total dollar loss to absorb.

    Returns:
        Dictionary with:
          - layers: Updated layer list with absorption details
          - total_capacity: Sum of all layer capacities
          - total_absorbed: How much was actually absorbed
          - unabsorbed_loss: Loss remaining after all layers
          - breach: True if loss exceeds total capacity
          - outcome: Human-readable outcome summary
          - outcome_detail: Detailed explanation
    """
    try:
        if loss_amount < 0:
            return {"error": "Loss amount cannot be negative."}

        remaining_loss = float(loss_amount)
        total_capacity = sum(layer["available"] for layer in layers)
        processed_layers = []

        for layer in layers:
            available = float(layer["available"])

            # How much can this layer absorb?
            absorbed = min(remaining_loss, available)
            remaining_loss -= absorbed
            ending_balance = available - absorbed

            # Determine status.
            if absorbed == 0:
                status = "INTACT"
            elif absorbed < available:
                status = "PARTIALLY DEPLETED"
            else:
                status = "EXHAUSTED"

            # Depletion percentage (how much of this layer was used).
            if available > 0:
                depletion_pct = (absorbed / available) * 100
            else:
                depletion_pct = 0.0 if absorbed == 0 else 100.0

            processed_layers.append({
                "layer": layer["layer"],
                "name": layer["name"],
                "short_name": layer.get("short_name", f"L{layer['layer']}"),
                "description": layer.get("description", ""),
                "available": round(available, 2),
                "absorbed": round(absorbed, 2),
                "ending_balance": round(ending_balance, 2),
                "remaining_loss_after": round(remaining_loss, 2),
                "status": status,
                "depletion_pct": round(depletion_pct, 2),
                "exhausted": status == "EXHAUSTED",
            })

        # Determine overall outcome.
        total_absorbed = loss_amount - remaining_loss

        if remaining_loss > 0:
            outcome = "BREACH — Loss exceeds all waterfall layers"
            outcome_detail = (
                f"${remaining_loss:,.2f} of loss cannot be absorbed by the waterfall. "
                f"This would require external intervention such as a government "
                f"bailout, emergency capital raise, or controlled wind-down."
            )
        else:
            # Find the deepest layer that absorbed losses.
            last_used_layers = [l for l in processed_layers if l["absorbed"] > 0]
            if last_used_layers:
                last_used = last_used_layers[-1]
                outcome = f"CONTAINED at Layer {last_used['layer']} ({last_used['name']})"
                if last_used["layer"] <= 3:
                    outcome_detail = (
                        "Loss was fully absorbed by the defaulter's own resources. "
                        "No other members were affected."
                    )
                elif last_used["layer"] == 4:
                    outcome_detail = (
                        "Loss reached the mutualized default fund. Non-defaulting "
                        "members absorbed some losses, but the clearinghouse survived."
                    )
                else:
                    outcome_detail = (
                        "Loss penetrated to clearinghouse capital. The system survived "
                        "but is severely weakened. Capital must be replenished immediately."
                    )
            else:
                outcome = "NO LOSS — Nothing to absorb"
                outcome_detail = "The loss amount was zero."

        return {
            "loss_amount": round(loss_amount, 2),
            "total_capacity": round(total_capacity, 2),
            "total_absorbed": round(total_absorbed, 2),
            "unabsorbed_loss": round(remaining_loss, 2),
            "breach": remaining_loss > 0,
            "layers": processed_layers,
            "outcome": outcome,
            "outcome_detail": outcome_detail,
            "deepest_layer_hit": max(
                (l["layer"] for l in processed_layers if l["absorbed"] > 0),
                default=0,
            ),
        }

    except Exception as error:
        return {
            "error": (
                f"Waterfall processing failed: {error}\n"
                f"Make sure all layer amounts are positive numbers and the "
                f"loss amount is a non-negative number."
            )
        }


# =============================================================================
# STRESS TEST BY EVENT MAGNITUDE
# =============================================================================

def run_stress_test(
    event_magnitude: float,
    defaulter_initial_margin: float = None,
    defaulter_default_fund: float = None,
    defaulter_contingent_capital: float = None,
    mutualized_default_fund: float = None,
    srx_clearinghouse_capital: float = None,
) -> dict:
    """
    Run a stress test with a hypothetical loss event.

    This is the main stress testing function for the clearinghouse.
    You give it a loss amount (e.g., $100M, $500M, $1B) and it shows
    how each waterfall layer would be affected.

    Parameters:
        event_magnitude: Total loss in dollars.
                         Examples: 100_000_000 ($100M), 500_000_000 ($500M),
                                   1_000_000_000 ($1B)
        Remaining params: Override default layer sizes if desired.

    Returns:
        Dictionary containing:
          - waterfall_result: Full waterfall processing output
          - summary_df: pandas DataFrame summary of all layers
          - chart_data: Data formatted for Plotly visualization
          - event_magnitude: The input loss amount
          - event_label: Human-readable label (e.g., "$500M")
    """
    try:
        if event_magnitude < 0:
            return {"error": "Event magnitude cannot be negative."}

        # ---- Build the waterfall layers ----
        layers = define_waterfall_layers(
            defaulter_initial_margin=defaulter_initial_margin,
            defaulter_default_fund=defaulter_default_fund,
            defaulter_contingent_capital=defaulter_contingent_capital,
            mutualized_default_fund=mutualized_default_fund,
            srx_clearinghouse_capital=srx_clearinghouse_capital,
        )

        # ---- Run the waterfall ----
        result = process_waterfall(layers, event_magnitude)

        if "error" in result:
            return result

        # ---- Build summary DataFrame ----
        summary_rows = []
        for layer in result["layers"]:
            summary_rows.append({
                "Layer": f"L{layer['layer']}",
                "Name": layer["name"],
                "Available ($)": layer["available"],
                "Absorbed ($)": layer["absorbed"],
                "Ending Balance ($)": layer["ending_balance"],
                "Depletion (%)": layer["depletion_pct"],
                "Status": layer["status"],
            })

        summary_df = pd.DataFrame(summary_rows)

        # ---- Build Plotly chart data ----
        chart_data = build_waterfall_chart_data(result)

        # ---- Human-readable event label ----
        if event_magnitude >= 1_000_000_000:
            event_label = f"${event_magnitude / 1_000_000_000:.1f}B"
        elif event_magnitude >= 1_000_000:
            event_label = f"${event_magnitude / 1_000_000:.0f}M"
        elif event_magnitude >= 1_000:
            event_label = f"${event_magnitude / 1_000:.0f}K"
        else:
            event_label = f"${event_magnitude:,.2f}"

        # ---- Console output for stress test reporting ----
        print(f"\n{'=' * 65}")
        print(f"  DEFAULT WATERFALL STRESS TEST — {event_label} LOSS EVENT")
        print(f"{'=' * 65}")
        print(f"  {'Layer':<6} {'Name':<35} {'Available':>14} {'Absorbed':>14} {'Status'}")
        print(f"  {'-'*4}   {'-'*33}   {'-'*12}   {'-'*12}   {'-'*20}")

        for layer in result["layers"]:
            status_icon = {
                "INTACT": "🟢",
                "PARTIALLY DEPLETED": "🟡",
                "EXHAUSTED": "🔴",
            }.get(layer["status"], "⚪")

            print(
                f"  L{layer['layer']:<4} {layer['name']:<35} "
                f"${layer['available']:>12,.0f} "
                f"${layer['absorbed']:>12,.0f}   "
                f"{status_icon} {layer['status']}"
            )

        print(f"  {'-'*4}   {'-'*33}   {'-'*12}   {'-'*12}   {'-'*20}")
        print(f"  {'':6} {'TOTAL':<35} ${result['total_capacity']:>12,.0f} ${result['total_absorbed']:>12,.0f}")

        if result["breach"]:
            print(f"\n  🔴 BREACH: ${result['unabsorbed_loss']:,.0f} unabsorbed")
        else:
            print(f"\n  🟢 CONTAINED at Layer {result['deepest_layer_hit']}")
        print(f"{'=' * 65}\n")

        return {
            "waterfall_result": result,
            "summary_df": summary_df,
            "chart_data": chart_data,
            "event_magnitude": event_magnitude,
            "event_label": event_label,
        }

    except Exception as error:
        return {
            "error": (
                f"Clearinghouse stress test failed: {error}\n"
                f"Make sure event_magnitude is a positive number.\n"
                f"Examples: 100_000_000 (100M), 500_000_000 (500M), 1_000_000_000 (1B)"
            )
        }


# =============================================================================
# CHART DATA BUILDER
# =============================================================================

def build_waterfall_chart_data(waterfall_result: dict) -> dict:
    """
    Format waterfall results for Plotly visualization.

    Returns data structured for a stacked horizontal bar chart where:
      - Each layer is a bar segment
      - Green = remaining capacity, Red = absorbed, Gray = exhausted portion

    Parameters:
        waterfall_result: Output from process_waterfall().

    Returns:
        Dictionary with chart-ready data arrays.
    """
    try:
        layers = waterfall_result.get("layers", [])

        labels = []
        absorbed_values = []
        remaining_values = []
        colors = []

        for layer in layers:
            labels.append(f"L{layer['layer']}: {layer['short_name']}")
            absorbed_values.append(layer["absorbed"])
            remaining_values.append(layer["ending_balance"])

            if layer["status"] == "EXHAUSTED":
                colors.append("#EF553B")      # Red
            elif layer["status"] == "PARTIALLY DEPLETED":
                colors.append("#FFA726")      # Orange
            else:
                colors.append("#66BB6A")      # Green

        return {
            "labels": labels,
            "absorbed": absorbed_values,
            "remaining": remaining_values,
            "colors": colors,
            "total_loss": waterfall_result.get("loss_amount", 0),
            "total_capacity": waterfall_result.get("total_capacity", 0),
            "breach": waterfall_result.get("breach", False),
        }

    except Exception as error:
        return {"error": f"Chart data build failed: {error}"}


# =============================================================================
# API FUNCTION: simulate_default_waterfall (backward compatible)
# =============================================================================

def simulate_default_waterfall(
    defaulter_margin: float = 500_000,
    defaulter_guarantee_fund: float = 200_000,
    platform_capital: float = 1_000_000,
    other_members_guarantee_fund: float = 3_000_000,
    emergency_assessment_capacity: float = 2_000_000,
    loss_amount: float = 2_500_000,
) -> dict:
    """
    Simulate a default waterfall — API-compatible version.

    This function is called by backend/main.py (the /waterfall endpoint)
    and used by the dashboard. It maps the old parameter names to the
    new 5-layer waterfall structure.

    Parameter mapping (old → new):
        defaulter_margin → Layer 1 (Defaulter Initial Margin)
        defaulter_guarantee_fund → Layer 2 (Defaulter Default Fund)
        (no old equivalent) → Layer 3 (Defaulter Contingent Capital) = 0
        other_members_guarantee_fund → Layer 4 (Mutualized Default Fund)
        platform_capital + emergency_assessment → Layer 5 (SRX Capital)

    Parameters:
        defaulter_margin: Collateral posted by the defaulter ($).
        defaulter_guarantee_fund: Defaulter's guarantee fund share ($).
        platform_capital: Platform's own capital ($).
        other_members_guarantee_fund: Other members' combined GF ($).
        emergency_assessment_capacity: Extra callable amount ($).
        loss_amount: Total loss from the default ($).

    Returns:
        Dictionary with layers, outcome, and unabsorbed_loss.
        Same keys as the old version for dashboard compatibility.
    """
    try:
        if loss_amount < 0:
            return {"error": "Loss amount cannot be negative."}

        # Map old parameters to the 5-layer structure.
        # Layer 5 combines platform_capital and emergency_assessment since
        # the old version had these as separate layers but the new structure
        # has them under SRX Clearinghouse Capital.
        layers = define_waterfall_layers(
            defaulter_initial_margin=defaulter_margin,
            defaulter_default_fund=defaulter_guarantee_fund,
            defaulter_contingent_capital=0,  # Old API didn't have this.
            mutualized_default_fund=other_members_guarantee_fund,
            srx_clearinghouse_capital=platform_capital + emergency_assessment_capacity,
        )

        result = process_waterfall(layers, loss_amount)

        if "error" in result:
            return result

        # The dashboard expects these exact keys in the layers.
        # Rebuild to match the old format exactly.
        old_format_layers = []
        for layer in result["layers"]:
            # Skip Layer 3 (contingent capital) if it was zero,
            # since the old API didn't have it.
            if layer["layer"] == 3 and layer["available"] == 0:
                continue

            old_format_layers.append({
                "layer": layer["layer"] if layer["layer"] <= 3 else layer["layer"] - (1 if layers[2]["available"] == 0 else 0),
                "name": layer["name"],
                "available": layer["available"],
                "absorbed": layer["absorbed"],
                "remaining_loss_after": layer["remaining_loss_after"],
                "exhausted": layer["exhausted"],
            })

        # Re-number layers sequentially for the old format.
        for i, layer in enumerate(old_format_layers):
            layer["layer"] = i + 1

        return {
            "loss_amount": result["loss_amount"],
            "total_waterfall_capacity": result["total_capacity"],
            "layers": old_format_layers,
            "unabsorbed_loss": result["unabsorbed_loss"],
            "outcome": result["outcome"],
            "outcome_detail": result["outcome_detail"],
        }

    except Exception as error:
        return {
            "error": (
                f"Default waterfall simulation failed: {error}\n"
                f"Make sure all input values are positive numbers."
            )
        }


# =============================================================================
# DYNAMIC GATING (delegates to gating_engine.py)
# =============================================================================

def evaluate_gating(
    gsri_score: float,
    portfolio_pri: float = None,
    recent_volatility_pct: float = None,
) -> dict:
    """
    Determine the current gating level based on risk metrics.

    This function delegates to backend/gating_engine.py, which contains
    the full SRS-based gating logic with four gate levels, continuous
    margin multipliers, contingent capital activation, and integration
    helpers for the pricing engine and clearinghouse.

    This wrapper exists so that main.py can continue importing
    evaluate_gating from clearinghouse_simulation without any changes.

    Parameters:
        gsri_score: The current Global Systemic Risk Index (0–100).
        portfolio_pri: Optional — the portfolio's PRI score (0–100).
        recent_volatility_pct: Optional — recent annualized volatility (%).

    Returns:
        A dictionary with the gate level and applicable restrictions.
    """
    # Import here to avoid circular import issues.
    from backend.gating_engine import evaluate_gating as _evaluate_gating
    return _evaluate_gating(gsri_score, portfolio_pri, recent_volatility_pct)


# =============================================================================
# EXAMPLE USAGE — Run this file directly to test
# =============================================================================

if __name__ == "__main__":
    """
    Run this file directly to test the clearinghouse simulation:
        cd ~/Desktop/srx-platform
        source venv/bin/activate
        python3 -m backend.clearinghouse_simulation
    """

    print("=" * 70)
    print("SRX PLATFORM — Clearinghouse Simulation Test")
    print("=" * 70)

    all_passed = True

    # ---- Test 1: Waterfall Layer Definitions ----
    print("\n--- TEST 1: define_waterfall_layers() ---\n")
    layers = define_waterfall_layers()
    total = 0
    for layer in layers:
        print(f"  L{layer['layer']}: {layer['name']:<40} ${layer['available']:>14,.0f}")
        total += layer["available"]
    print(f"  {'':4} {'TOTAL CAPACITY':<40} ${total:>14,.0f}")

    # ---- Test 2: Small Loss (contained at Layer 1) ----
    print("\n\n--- TEST 2: run_stress_test($100M) — Small Loss ---")
    result_100m = run_stress_test(100_000_000)
    if "error" in result_100m:
        print(f"  ERROR: {result_100m['error']}")
        all_passed = False
    else:
        wr = result_100m["waterfall_result"]
        print(f"  Outcome: {wr['outcome']}")
        print(f"  Deepest layer hit: {wr['deepest_layer_hit']}")

    # ---- Test 3: Medium Loss (penetrates to mutualized fund) ----
    print("\n\n--- TEST 3: run_stress_test($500M) — Medium Loss ---")
    result_500m = run_stress_test(500_000_000)
    if "error" in result_500m:
        print(f"  ERROR: {result_500m['error']}")
        all_passed = False
    else:
        wr = result_500m["waterfall_result"]
        print(f"  Outcome: {wr['outcome']}")
        print(f"  Deepest layer hit: {wr['deepest_layer_hit']}")

    # ---- Test 4: Catastrophic Loss (breach) ----
    print("\n\n--- TEST 4: run_stress_test($1B) — Catastrophic Loss ---")
    result_1b = run_stress_test(1_000_000_000)
    if "error" in result_1b:
        print(f"  ERROR: {result_1b['error']}")
        all_passed = False
    else:
        wr = result_1b["waterfall_result"]
        print(f"  Outcome: {wr['outcome']}")
        if wr["breach"]:
            print(f"  Unabsorbed loss: ${wr['unabsorbed_loss']:,.0f}")

    # ---- Test 5: Summary DataFrame ----
    print("\n\n--- TEST 5: Summary DataFrame ($500M loss) ---\n")
    if "summary_df" in result_500m:
        print(result_500m["summary_df"].to_string(index=False))

    # ---- Test 6: Backward-compatible API function ----
    print("\n\n--- TEST 6: simulate_default_waterfall() (API compat) ---\n")
    api_result = simulate_default_waterfall(
        defaulter_margin=500_000,
        defaulter_guarantee_fund=200_000,
        platform_capital=1_000_000,
        other_members_guarantee_fund=3_000_000,
        emergency_assessment_capacity=2_000_000,
        loss_amount=2_500_000,
    )
    if "error" in api_result:
        print(f"  ERROR: {api_result['error']}")
        all_passed = False
    else:
        print(f"  Loss: ${api_result['loss_amount']:,.0f}")
        print(f"  Outcome: {api_result['outcome']}")
        print(f"  Unabsorbed: ${api_result['unabsorbed_loss']:,.0f}")
        print(f"  Layers: {len(api_result['layers'])}")
        for layer in api_result["layers"]:
            print(
                f"    L{layer['layer']}: {layer['name']:<40} "
                f"avail=${layer['available']:>12,.0f}  "
                f"absorbed=${layer['absorbed']:>12,.0f}  "
                f"{'EXHAUSTED' if layer['exhausted'] else 'OK'}"
            )

    # ---- Test 7: Dynamic Gating ----
    print("\n\n--- TEST 7: evaluate_gating() ---\n")
    for gsri in [15, 40, 60, 85]:
        gate = evaluate_gating(gsri)
        print(f"  GSRI={gsri:>3} → Gate Level {gate['level']} ({gate['label']}): "
              f"margin={gate['margin_multiplier']:.2f}x, "
              f"new_pos={'✓' if gate['new_positions_allowed'] else '✗'}, "
              f"redemp={'✓' if gate['redemptions_allowed'] else '✗'}")

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    if all_passed:
        print("STATUS: All tests passed. Clearinghouse simulation is working.")
    else:
        print("STATUS: Some tests failed. Check error messages above.")
    print("=" * 70)
