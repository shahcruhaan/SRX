"""
dashboard.py — SRX Platform | Institutional Dashboard (Dark Mode)

Run:  streamlit run frontend/dashboard.py
Self-contained. No backend server required.
"""

import sys, os
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

from backend.portfolio_engine import calculate_pri, calculate_srs
from backend.gsri_engine import calculate_gsri
from backend.pricing_engine import price_protection
from backend.stress_engine import run_stress_test
from backend.clearinghouse_simulation import simulate_default_waterfall
from backend.gating_engine import evaluate_gating
from backend.historical_validation import compute_walkforward_gsri, CRISIS_ERAS, SHOCK_MULTIPLIER

# =============================================================================
# CONFIG
# =============================================================================

st.set_page_config(
    page_title="SRX | Systemic Risk Exchange",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =============================================================================
# PALETTE — single dark theme, no toggles
# =============================================================================

BG      = "#0f131a"
SIDEBAR = "#131820"
CARD    = "#1b2231"
BORDER  = "#2d3748"
TX1     = "#f1f5f9"   # primary text
TX2     = "#94a3b8"   # secondary text
TX3     = "#64748b"   # muted text
DIV     = "#1e293b"
GRID    = "#1e293b"

# Risk status — the only non-neutral colors in the entire UI
SAFE     = "#4a7c59"
ELEVATED = "#c49032"
CRITICAL = "#b83232"
NEUTRAL  = "#7c8a98"

# Chart series
LINE = "#8494a7"
FILL = "rgba(132,148,167,0.06)"
SUB1, SUB2, SUB3, SUB4 = "#5c7fa0", "#8a7e6a", "#7a6888", "#5c8a72"

# =============================================================================
# CSS — clean, single-palette, no conditionals
# =============================================================================

st.markdown(f"""<style>
/* Base */
.stApp {{ background-color:{BG}; color:{TX1}; }}
section[data-testid="stSidebar"] {{ background-color:{SIDEBAR}; border-right:1px solid {BORDER}; }}

/* All text inherits */
.stApp p, .stApp span, .stApp li,
.stApp [data-testid="stMarkdownContainer"],
.stApp [data-testid="stMarkdownContainer"] p,
.stApp [data-testid="stMarkdownContainer"] span {{ color:{TX1} !important; }}

/* Sidebar text */
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] h4,
section[data-testid="stSidebar"] h5 {{ color:{TX1} !important; }}

section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] span {{ color:{TX2} !important; }}

section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * {{ color:{TX3} !important; }}

section[data-testid="stSidebar"] hr {{ border-color:{BORDER} !important; }}

/* Headers */
h1 {{ color:{TX1} !important; font-weight:600 !important; letter-spacing:-0.01em; }}
h2 {{ color:{TX1} !important; font-weight:500 !important; }}
h3 {{ color:{TX2} !important; font-weight:500 !important; font-size:1.05rem !important; }}

/* Metrics */
[data-testid="stMetric"] {{ background-color:{CARD}; border:1px solid {BORDER}; border-radius:6px; padding:14px 16px; }}
[data-testid="stMetricValue"] {{ color:{TX1} !important; font-family:'IBM Plex Mono','SF Mono','Fira Code','Consolas',monospace; font-weight:600; }}
[data-testid="stMetricLabel"] {{ color:{TX3} !important; font-size:0.82rem; text-transform:uppercase; letter-spacing:0.04em; }}

/* Buttons */
.stButton > button {{ background-color:{DIV}; color:{TX2}; border:1px solid {BORDER}; font-weight:500; border-radius:5px; }}
.stButton > button:hover {{ background-color:#283548; color:{TX1}; }}

/* Misc */
hr {{ border-color:{DIV} !important; }}
.stDataFrame {{ border-radius:6px; overflow:hidden; }}
.stRadio > div {{ gap:0.25rem; }}
.stExpander {{ border-color:{BORDER} !important; }}
.stExpander summary span {{ color:{TX1} !important; }}

/* Methodology box */
.method-box {{ background-color:{CARD}; border:1px solid {BORDER}; border-radius:6px; padding:20px 24px; margin:8px 0 20px 0; line-height:1.65; }}
.method-box h4 {{ color:{TX2} !important; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.08em; margin:0 0 14px 0; padding-bottom:10px; border-bottom:1px solid {BORDER}; }}
.method-box .def-term {{ color:#cbd5e1 !important; font-weight:600; font-family:'IBM Plex Mono','SF Mono','Fira Code','Consolas',monospace; font-size:0.85rem; }}
.method-box .def-desc {{ color:{TX2} !important; font-size:0.85rem; }}
.method-box p {{ color:{TX2} !important; }}

/* Gate banner */
.gate-banner {{ padding:20px; border-radius:6px; text-align:center; margin:10px 0; }}
.gate-banner h1 {{ margin:0 !important; font-size:1.4rem !important; color:white !important; }}
.gate-banner p {{ margin:5px 0 0 0; font-size:0.9rem; color:rgba(255,255,255,0.85) !important; }}

/* Narrative */
.narrative {{ color:{TX3} !important; font-style:italic; font-size:0.9rem; margin:-4px 0 18px 0; line-height:1.5; }}
</style>""", unsafe_allow_html=True)


# =============================================================================
# CHART HELPER
# =============================================================================

def _cl(height=420, **kw):
    d = dict(
        template="plotly_dark", height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TX2, size=11),
        margin=dict(l=48, r=24, t=32, b=48),
        legend=dict(orientation="h", y=-0.14, font=dict(size=10, color=TX2)),
        xaxis=dict(gridcolor=GRID, gridwidth=1),
        yaxis=dict(gridcolor=GRID, gridwidth=1),
    )
    d.update(kw)
    return d


# =============================================================================
# ENGINE WRAPPERS — cached direct calls
# =============================================================================

@st.cache_data(ttl=300, show_spinner=False)
def _gsri(period="2y", rolling_window=60):
    try:
        return calculate_gsri(period=period, rolling_window=rolling_window)
    except Exception as e:
        return {"error": str(e)}

@st.cache_data(ttl=300, show_spinner=False)
def _pri(tk, wt=None, period="2y"):
    try:
        tl = [x.strip().upper() for x in tk.split(",") if x.strip()]
        wl = [float(w.strip()) for w in wt.split(",")] if wt and wt.strip() else None
        return calculate_pri(tl, wl, period)
    except Exception as e:
        return {"error": str(e)}

@st.cache_data(ttl=300, show_spinner=False)
def _srs(tk, period="2y"):
    try:
        return calculate_srs([x.strip().upper() for x in tk.split(",") if x.strip()], period=period)
    except Exception as e:
        return {"error": str(e)}

@st.cache_data(ttl=300, show_spinner=False)
def _stress(tk, wt=None, sc="2008_crisis", cs=None, period="2y"):
    try:
        tl = [x.strip().upper() for x in tk.split(",") if x.strip()]
        wl = [float(w.strip()) for w in wt.split(",")] if wt and wt.strip() else None
        return run_stress_test(tl, wl, sc, cs, period)
    except Exception as e:
        return {"error": str(e)}

@st.cache_data(ttl=300, show_spinner=False)
def _price(tk, wt=None, notional=1e6, plvl=20.0, dur=90, period="2y"):
    try:
        tl = [x.strip().upper() for x in tk.split(",") if x.strip()]
        wl = [float(w.strip()) for w in wt.split(",")] if wt and wt.strip() else None
        return price_protection(tl, wl, notional, plvl, dur, period)
    except Exception as e:
        return {"error": str(e)}

def _waterfall(**kw):
    try:
        return simulate_default_waterfall(**kw)
    except Exception as e:
        return {"error": str(e)}

def _gating(gsri=None, pri_val=None):
    try:
        if gsri is None:
            r = calculate_gsri()
            if "error" in r:
                return r
            gsri = r["current_gsri"]
        return evaluate_gating(gsri, pri_val)
    except Exception as e:
        return {"error": str(e)}

def _err(r):
    if isinstance(r, dict) and "error" in r:
        st.error(r["error"])
        return True
    return False


# =============================================================================
# SIDEBAR
# =============================================================================

with st.sidebar:
    st.markdown("## ◆ &nbsp;SRX Platform")
    st.caption("Systemic Risk Exchange")
    st.markdown("---")

    page = st.radio(
        "Navigation",
        ["Overview", "Portfolio Risk Index", "GSRI & SRS", "Stress Testing",
         "Protection Pricing", "Default Waterfall", "Dynamic Gating",
         "Historical Validation"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown("##### Portfolio")
    tk_in = st.text_input("Tickers", value="SPY,HYG,TLT,GLD,BTC-USD")
    wt_in = st.text_input("Weights", value="0.40,0.20,0.20,0.10,0.10")
    period = st.selectbox("Period", ["1y", "2y", "5y"], index=1)

    st.markdown("---")
    st.markdown("##### Pricing")
    notional = st.number_input("Notional ($)", min_value=10_000, max_value=100_000_000,
                                value=1_000_000, step=100_000, format="%d")
    plvl = st.slider("Protection Level (%)", 5, 50, 20)
    dur = st.selectbox("Duration (days)", [30, 60, 90, 180, 365], index=2)
    liq = st.slider("Liquidity Adj.", 0.5, 2.0, 1.0, step=0.05)

    st.markdown("---")
    st.markdown("##### Stress Scenario")
    scn = st.selectbox(
        "Scenario",
        ["2008_crisis", "covid_crash", "rate_shock", "liquidity_freeze",
         "crypto_contagion", "custom"],
        format_func=lambda x: {
            "2008_crisis": "2008 Financial Crisis",
            "covid_crash": "COVID-19 Crash",
            "rate_shock": "Interest Rate Shock",
            "liquidity_freeze": "Liquidity Freeze",
            "crypto_contagion": "Crypto Contagion",
            "custom": "Custom Shock",
        }.get(x, x),
    )
    cshock = st.number_input("Custom Shock (%)", -90.0, 0.0, -25.0) if scn == "custom" else None

    st.markdown("---")

    # Refresh button — clears CSV cache + Streamlit cache
    if st.button("Refresh Market Data"):
        # Clear CSV file cache
        import glob
        cache_dir = os.path.join(_root, "data", "cache")
        csv_files = glob.glob(os.path.join(cache_dir, "*.csv"))
        for f in csv_files:
            try:
                os.remove(f)
            except OSError:
                pass
        # Clear Streamlit's in-memory cache
        st.cache_data.clear()
        st.success(f"Cleared {len(csv_files)} cached files. Data will re-download.")
        st.rerun()

    st.caption("Research prototype. Not financial advice.")

tks = ",".join([s.strip().upper() for s in tk_in.split(",") if s.strip()])
wts = wt_in.strip() if wt_in.strip() else None


# =============================================================================
# PAGE 1: OVERVIEW
# =============================================================================

if page == "Overview":
    st.markdown("# Executive Overview")
    st.markdown(
        '<p class="narrative">Real-time systemic risk assessment across portfolio, '
        'market, and clearinghouse dimensions.</p>',
        unsafe_allow_html=True,
    )

    st.markdown("""<div class="method-box">
        <h4>Systemic Risk Exchange &nbsp;|&nbsp; Platform Methodology</h4>
        <p><span class="def-term">PRI</span> <span class="def-desc">
        (Portfolio Risk Index): Normalized time series starting at 100,
        tracking portfolio value and risk profile.</span></p>
        <p><span class="def-term">SRS</span> <span class="def-desc">
        (Systemic Risk Score): 0–100 measuring real-time stress across
        volatility, liquidity, and correlation.</span></p>
        <p><span class="def-term">GSRI</span> <span class="def-desc">
        (Global Systemic Risk Index): Institutional benchmark of global
        financial stability.</span></p>
        <p><span class="def-term">Premium</span> <span class="def-desc">
        : Model-implied cost to insure the current notional against
        systemic shocks.</span></p>
    </div>""", unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        with st.spinner("GSRI..."):
            gd = _gsri(period=period)
        if not _err(gd):
            st.metric("GSRI", f"{gd['current_gsri']:.1f}", gd["risk_level"],
                       help="Aggregate systemic risk benchmark.")

    with c2:
        sv = gd.get("srs_current", 0) if isinstance(gd, dict) and "srs_current" in gd else 0
        st.metric("SRS", f"{sv:.1f}", "Systemic Risk Score",
                   help="0–70 Normal. 70–85 Elevated. 85+ Critical.")

    with c3:
        with st.spinner("PRI..."):
            pd2 = _pri(tks, wts, period)
        if not _err(pd2):
            st.metric("PRI", f"{pd2['pri']:.1f}", pd2["risk_level"],
                       help="Portfolio-specific composite risk.")

    with c4:
        with st.spinner("Gating..."):
            gt = _gating()
        if not _err(gt):
            st.metric("Gate", f"Level {gt['level']}", gt["label"],
                       help="SRS-based dynamic gating.")

    st.markdown("---")

    if isinstance(gd, dict) and "gsri_history" in gd:
        hdf = pd.DataFrame(gd["gsri_history"])
        if not hdf.empty:
            st.markdown("### Global Systemic Risk Index — Historical")
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=hdf["date"], y=hdf["gsri"], mode="lines", name="GSRI",
                line=dict(color=LINE, width=2), fill="tozeroy", fillcolor=FILL,
            ))
            for cn, cl in [("correlation", SUB1), ("volatility", SUB2),
                           ("credit", SUB3), ("tail", SUB4)]:
                if cn in hdf.columns:
                    fig.add_trace(go.Scatter(
                        x=hdf["date"], y=hdf[cn], mode="lines", name=cn.title(),
                        line=dict(width=1, dash="dot", color=cl), opacity=0.45,
                    ))
            fig.add_hline(y=30, line_dash="dot", line_color=SAFE,
                          annotation_text="Low", annotation_font_size=10,
                          annotation_font_color=TX3)
            fig.add_hline(y=55, line_dash="dot", line_color=ELEVATED,
                          annotation_text="Elevated", annotation_font_size=10,
                          annotation_font_color=TX3)
            fig.add_hline(y=75, line_dash="dot", line_color=CRITICAL,
                          annotation_text="Critical", annotation_font_size=10,
                          annotation_font_color=TX3)
            fig.update_layout(**_cl(420, yaxis_title="Score"))
            st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# PAGE 2: PORTFOLIO RISK INDEX
# =============================================================================

elif page == "Portfolio Risk Index":
    st.markdown("# Portfolio Risk Index (PRI)")
    st.markdown(
        '<p class="narrative">Composite risk assessment across volatility, '
        'correlation, concentration, and tail risk.</p>',
        unsafe_allow_html=True,
    )

    if st.button("Calculate PRI", type="primary"):
        with st.spinner("Computing..."):
            r = _pri(tks, wts, period)

        if not _err(r):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("PRI Score", f"{r['pri']:.1f} / 100", r["risk_level"])
            c2.metric("Annualized Vol.", f"{r['portfolio_volatility_annual']:.1f}%")
            c3.metric("Max Drawdown", f"{r.get('max_drawdown_pct', 'N/A')}%")
            c4.metric("Sharpe Ratio", f"{r.get('sharpe_ratio', 'N/A')}")

            st.markdown("---")
            col_l, col_r = st.columns([3, 2])

            with col_l:
                st.markdown("### Risk Components")
                cats = ["Volatility", "Correlation", "Concentration", "Tail Risk"]
                vals = [r["volatility_score"], r["correlation_score"],
                        r["concentration_score"], r["tail_risk_score"]]
                fig = go.Figure(data=go.Scatterpolar(
                    r=vals + [vals[0]], theta=cats + [cats[0]],
                    fill="toself", fillcolor="rgba(132,148,167,0.10)",
                    line=dict(color=LINE, width=2),
                ))
                fig.update_layout(
                    **_cl(380),
                    polar=dict(
                        radialaxis=dict(visible=True, range=[0, 100],
                                        gridcolor=GRID, color=TX2),
                        angularaxis=dict(color=TX2),
                        bgcolor="rgba(0,0,0,0)",
                    ),
                )
                st.plotly_chart(fig, use_container_width=True)

            with col_r:
                st.markdown("### Composition")
                st.dataframe(
                    pd.DataFrame({
                        "Ticker": r["tickers"],
                        "Weight": [f"{w*100:.1f}%" for w in r["weights"]],
                    }),
                    hide_index=True, use_container_width=True,
                )
                if r.get("cumulative_return_pct") is not None:
                    st.markdown("### Performance")
                    st.write(f"Cumulative Return: **{r['cumulative_return_pct']:.2f}%**")
                    st.write(f"Annualized Return: **{r.get('annualized_return_pct', 'N/A')}%**")

    st.markdown("---")
    st.markdown("### Systemic Risk Scores — Per Asset")
    st.markdown(
        '<p class="narrative">Individual asset systemic risk contribution.</p>',
        unsafe_allow_html=True,
    )

    if st.button("Calculate SRS"):
        with st.spinner("Computing..."):
            sr = _srs(tks, period)
        if not _err(sr):
            scores = sr.get("scores", {})
            rows = [
                {"Ticker": tk, "SRS": d["srs"], "Level": d["risk_level"],
                 "Beta": d["beta"], "Vol%": d["volatility_annual_pct"]}
                for tk, d in scores.items() if d.get("srs") is not None
            ]
            if rows:
                sdf = pd.DataFrame(rows).sort_values("SRS", ascending=False)
                fig = px.bar(
                    sdf, x="Ticker", y="SRS", color="SRS",
                    color_continuous_scale=[
                        [0, SAFE], [0.5, NEUTRAL],
                        [0.75, ELEVATED], [1.0, CRITICAL],
                    ],
                    range_color=[0, 100], text="SRS",
                )
                fig.update_layout(**_cl(380))
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(sdf, hide_index=True, use_container_width=True)


# =============================================================================
# PAGE 3: GSRI & SRS
# =============================================================================

elif page == "GSRI & SRS":
    st.markdown("# Global Systemic Risk Index (GSRI)")
    st.markdown(
        '<p class="narrative">Equity volatility, credit stress, treasury dynamics, '
        'crypto volatility, cross-asset correlation.</p>',
        unsafe_allow_html=True,
    )

    rw = st.slider("Rolling Window (trading days)", 20, 120, 60, step=10)

    if st.button("Calculate GSRI", type="primary"):
        with st.spinner("Computing..."):
            r = _gsri(period=period, rolling_window=rw)

        if not _err(r):
            col_l, col_r = st.columns([1, 2])

            with col_l:
                st.metric("Current GSRI", f"{r['current_gsri']:.1f}")
                st.info(r["risk_level"])
                st.metric("Current SRS", f"{r.get('srs_current', 0):.1f}")

                st.markdown("**GSRI Sub-Scores**")
                for n, v in r.get("sub_scores", {}).items():
                    st.progress(min(v / 100, 1.0),
                                text=f"{n.replace('_', ' ').title()}: {v:.1f}")

                sc = r.get("srs_components", {})
                if sc:
                    st.markdown("**SRS Components**")
                    for n, v in sc.items():
                        st.progress(min(v / 100, 1.0),
                                    text=f"{n.replace('_', ' ').title()}: {v:.1f}")

            with col_r:
                hdf = pd.DataFrame(r.get("gsri_history", []))
                if not hdf.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=hdf["date"], y=hdf["gsri"], mode="lines",
                        name="GSRI", line=dict(color=LINE, width=2.5),
                    ))
                    for cn, cl in [("correlation", SUB1), ("volatility", SUB2),
                                   ("credit", SUB3), ("tail", SUB4)]:
                        if cn in hdf.columns:
                            fig.add_trace(go.Scatter(
                                x=hdf["date"], y=hdf[cn], mode="lines",
                                name=cn.title(),
                                line=dict(width=1, dash="dot", color=cl),
                                opacity=0.45,
                            ))
                    fig.add_hline(y=30, line_dash="dot", line_color=SAFE)
                    fig.add_hline(y=55, line_dash="dot", line_color=ELEVATED)
                    fig.add_hline(y=75, line_dash="dot", line_color=CRITICAL)
                    fig.update_layout(**_cl(500, yaxis_title="Score"))
                    st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# PAGE 4: STRESS TESTING
# =============================================================================

elif page == "Stress Testing":
    st.markdown("# Stress Testing")
    st.markdown(
        '<p class="narrative">Scenario analysis projecting portfolio impact '
        'under market dislocations.</p>',
        unsafe_allow_html=True,
    )

    if st.button("Run Stress Test", type="primary"):
        with st.spinner("Running..."):
            r = _stress(tks, wts, scn, cshock, period)

        if not _err(r):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Portfolio Shock", f"{r['portfolio_shock_pct']:.1f}%")
            c2.metric("Stressed Value", f"${r['stressed_value']:.2f}")
            c3.metric("Severity", r["severity"])
            sp = r.get("stressed_pri")
            if sp is not None:
                c4.metric("Stressed PRI", f"{sp:.1f}",
                           r.get("stressed_risk_level", ""))

            st.markdown("---")
            idf = pd.DataFrame(r["asset_impacts"])
            fig = go.Figure(go.Waterfall(
                name="Impact", orientation="v",
                x=idf["ticker"], y=idf["weighted_impact_pct"],
                text=[f"{v:+.2f}%" for v in idf["weighted_impact_pct"]],
                textposition="outside",
                connector=dict(line=dict(color=GRID, width=1)),
                increasing=dict(marker=dict(color=SAFE)),
                decreasing=dict(marker=dict(color=CRITICAL)),
            ))
            fig.update_layout(**_cl(400, title="Per-Asset Contribution",
                                    yaxis_title="Impact (%)"))
            st.plotly_chart(fig, use_container_width=True)

            col_l, col_r = st.columns(2)
            with col_l:
                st.markdown("**Scenario Details**")
                st.write(f"Scenario: {r.get('scenario_name', r['scenario'])}")
                st.write(f"Recovery: {r.get('estimated_recovery_days', 'N/A')} days")
                sv2 = r.get("stressed_volatility_pct")
                if sv2:
                    st.write(f"Stressed Volatility: {sv2:.1f}%")
            with col_r:
                w = r.get("worst_asset")
                if w:
                    st.markdown("**Worst Contributing Asset**")
                    st.write(f"**{w['ticker']}** ({w['shock_pct']:+.1f}%)")
                    st.write(f"Loss contribution: "
                             f"{w.get('contribution_to_loss_pct', 'N/A')}%")

            st.dataframe(idf, hide_index=True, use_container_width=True)


# =============================================================================
# PAGE 5: PROTECTION PRICING
# =============================================================================

elif page == "Protection Pricing":
    st.markdown("# Protection Pricing")
    st.markdown(
        '<p class="narrative">Model-implied crash protection premium based on '
        'notional, systemic stress, and portfolio risk.</p>',
        unsafe_allow_html=True,
    )

    if st.button("Price Protection", type="primary"):
        with st.spinner("Pricing..."):
            r = _price(tks, wts, notional, plvl, dur, period)

        if not _err(r):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Premium", f"${r['premium_dollars']:,.2f}",
                       help="Model-implied crash protection estimate.")
            c2.metric("Premium (bps)", f"{r['premium_bps']:.1f}")
            c3.metric("Max Payout", f"${r['max_payout_dollars']:,.2f}")
            c4.metric("Crash Probability",
                       f"{r['historical_crash_probability']*100:.2f}%")

            st.markdown("---")
            col_l, col_r = st.columns(2)

            with col_l:
                st.markdown("### Contract Specification")
                st.write(f"Notional: **${notional:,.0f}**")
                st.write(f"Protection Trigger: **-{plvl}%**")
                st.write(f"Duration: **{dur} days**")
                st.write(f"GSRI at Pricing: **{r['gsri_used']:.1f}**")
                su = r.get("srs_used")
                if su is not None:
                    st.write(f"SRS at Pricing: **{su:.1f}**")

            with col_r:
                st.markdown("### Premium Decomposition")
                mb = r.get("multiplier_breakdown", {})
                if mb:
                    st.dataframe(pd.DataFrame([
                        {"Component": "Base Rate",
                         "Value": f"{mb.get('base_rate', 0.01):.4f}"},
                        {"Component": "SRS Multiplier",
                         "Value": f"{mb.get('srs_multiplier', 1):.4f}x"},
                        {"Component": "Portfolio Risk Adj.",
                         "Value": f"{mb.get('portfolio_risk_adjustment', 1):.4f}x"},
                        {"Component": "Liquidity Adj.",
                         "Value": f"{mb.get('liquidity_adjustment', 1):.4f}x"},
                        {"Component": "Risk Loading",
                         "Value": f"{mb.get('risk_loading', 1.25):.4f}x"},
                        {"Component": "Duration Factor",
                         "Value": f"{mb.get('duration_factor', 1):.4f}x"},
                        {"Component": "Depth Factor",
                         "Value": f"{mb.get('depth_factor', 1):.4f}x"},
                        {"Component": "Combined",
                         "Value": f"{mb.get('combined_multiplier', 1):.4f}x"},
                    ]), hide_index=True, use_container_width=True)

            payout = r.get("payout_profile")
            if payout and "binary_payouts" in payout:
                st.markdown("---")
                st.markdown("### Payout Profile")
                pay_df = pd.DataFrame(payout["binary_payouts"])
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=[f"-{d}%" for d in pay_df["drawdown_pct"]],
                    y=pay_df["portfolio_loss_dollars"],
                    name="Portfolio Loss",
                    marker_color=CRITICAL, opacity=0.45,
                ))
                fig.add_trace(go.Bar(
                    x=[f"-{d}%" for d in pay_df["drawdown_pct"]],
                    y=pay_df["binary_payout_dollars"],
                    name="Insurance Payout",
                    marker_color=SAFE, opacity=0.7,
                ))
                fig.update_layout(**_cl(380, barmode="overlay",
                                        yaxis_title="Dollars ($)",
                                        xaxis_title="Drawdown"))
                st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# PAGE 6: DEFAULT WATERFALL
# =============================================================================

elif page == "Default Waterfall":
    st.markdown("# Default Waterfall Simulation")
    st.markdown(
        '<p class="narrative">Loss absorption through the five-layer SRX '
        'capital structure.</p>',
        unsafe_allow_html=True,
    )

    emag = st.number_input(
        "Event Magnitude ($)", min_value=0, max_value=10_000_000_000,
        value=500_000_000, step=50_000_000, format="%d",
        help="e.g. 500000000 = $500M",
    )

    with st.expander("Custom Layer Sizes"):
        l1, l2, l3 = st.columns(3)
        with l1:
            dm = st.number_input("Defaulter Margin", value=200_000_000,
                                  step=10_000_000, format="%d")
            ddf = st.number_input("Default Fund", value=50_000_000,
                                   step=5_000_000, format="%d")
        with l2:
            dcc = st.number_input("Contingent Capital", value=30_000_000,
                                   step=5_000_000, format="%d")
            mdf = st.number_input("Mutualized Fund", value=500_000_000,
                                   step=50_000_000, format="%d")
        with l3:
            sxc = st.number_input("SRX Capital", value=150_000_000,
                                   step=10_000_000, format="%d")

    if st.button("Run Waterfall", type="primary"):
        r = _waterfall(
            defaulter_margin=dm, defaulter_guarantee_fund=ddf,
            platform_capital=dcc + sxc, other_members_guarantee_fund=mdf,
            emergency_assessment_capacity=0, loss_amount=emag,
        )

        if not _err(r):
            if r["unabsorbed_loss"] > 0:
                st.error(f"BREACH — {r['outcome']}")
                st.warning(r["outcome_detail"])
            else:
                st.success(f"CONTAINED — {r['outcome']}")

            c1, c2, c3 = st.columns(3)
            c1.metric("Loss Event", f"${emag:,.0f}")
            c2.metric("Total Capacity",
                       f"${r.get('total_waterfall_capacity', 0):,.0f}")
            c3.metric("Unabsorbed", f"${r['unabsorbed_loss']:,.0f}")

            st.markdown("---")
            ldf = pd.DataFrame(r["layers"])
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=[f"L{x['layer']}: {x['name']}" for _, x in ldf.iterrows()],
                y=ldf["absorbed"], name="Loss Absorbed",
                marker_color=[CRITICAL if x["exhausted"] else ELEVATED
                              for _, x in ldf.iterrows()],
                text=[f"${v:,.0f}" for v in ldf["absorbed"]],
                textposition="outside",
            ))
            remaining = ldf["available"] - ldf["absorbed"]
            fig.add_trace(go.Bar(
                x=[f"L{x['layer']}: {x['name']}" for _, x in ldf.iterrows()],
                y=remaining, name="Remaining Capacity",
                marker_color=SAFE, opacity=0.3,
            ))
            fig.update_layout(**_cl(450, barmode="stack",
                                    title="Layer Depletion",
                                    yaxis_title="Amount ($)"))
            st.plotly_chart(fig, use_container_width=True)

            disp = ldf.copy()
            for cn in ["available", "absorbed", "remaining_loss_after"]:
                if cn in disp.columns:
                    disp[cn] = disp[cn].apply(lambda x: f"${x:,.2f}")
            st.dataframe(disp, hide_index=True, use_container_width=True)


# =============================================================================
# PAGE 7: DYNAMIC GATING
# =============================================================================

elif page == "Dynamic Gating":
    st.markdown("# Dynamic Gating")
    st.markdown(
        '<p class="narrative">Circuit breakers triggered by SRS thresholds '
        'to preserve clearinghouse integrity.</p>',
        unsafe_allow_html=True,
    )

    st.markdown("### Threshold Explorer")
    ms = st.slider("Simulated SRS", 0.0, 100.0, 50.0, step=1.0)
    mp2 = st.slider("Simulated PRI", 0.0, 100.0, 40.0, step=1.0)

    r = _gating(gsri=ms / 1.1, pri_val=mp2)

    if not _err(r):
        color_map = {
            "green": SAFE, "yellow": ELEVATED,
            "orange": ELEVATED, "red": CRITICAL,
        }
        gc = color_map.get(r.get("color", ""), "#555")
        st.markdown(
            f"<div class='gate-banner' style='background-color:{gc};'>"
            f"<h1>GATE LEVEL {r['level']}: {r['label'].upper()}</h1>"
            f"<p>{r['description']}</p></div>",
            unsafe_allow_html=True,
        )

        if r.get("actions"):
            st.markdown("### Active Restrictions")
            for action in r["actions"]:
                st.write(f"• {action}")

        st.markdown("---")
        st.markdown("### System Status")
        c1, c2, c3, c4 = st.columns(4)
        mpct = int((r["margin_multiplier"] - 1) * 100)
        c1.metric("Margin", f"{r['margin_multiplier']:.2f}x",
                   delta=f"+{mpct}%" if mpct > 0 else "Standard")
        c2.metric("Positions",
                   "Open" if r["new_positions_allowed"] else "Blocked")
        c3.metric("Redemptions",
                   "Open" if r["redemptions_allowed"] else "Delayed")
        c4.metric("De-leveraging",
                   "Active" if r["forced_deleveraging"] else "Inactive")

        st.markdown("---")
        st.markdown("### SRS Gauge")
        fig = go.Figure()
        fig.add_trace(go.Indicator(
            mode="gauge+number", value=ms,
            title={"text": "Systemic Risk Score",
                    "font": {"size": 13, "color": TX3}},
            number={"font": {"color": TX1}},
            gauge=dict(
                axis=dict(range=[0, 100], tickcolor="#475569"),
                bar=dict(color=NEUTRAL),
                steps=[
                    dict(range=[0, 70], color="#162016"),
                    dict(range=[70, 85], color="#252014"),
                    dict(range=[85, 95], color="#251a14"),
                    dict(range=[95, 100], color="#251414"),
                ],
                threshold=dict(line=dict(color=TX1, width=2), value=ms),
            ),
        ))
        fig.update_layout(**_cl(280))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.markdown("### Live Gating")
    if st.button("Check Live Gate Status"):
        with st.spinner("Calculating..."):
            lv = _gating()
        if not _err(lv):
            st.info(
                f"Gate Level: **{lv['level']} ({lv['label']})** "
                f"— GSRI: {lv.get('gsri_input', 'N/A')}"
            )
            if lv.get("actions"):
                for action in lv["actions"]:
                    st.write(f"• {action}")


# =============================================================================
# PAGE 8: HISTORICAL CRISIS VALIDATION
# =============================================================================

elif page == "Historical Validation":
    st.markdown("# Historical Crisis Validation")
    st.markdown(
        '<p class="narrative">Walk-forward analysis with adaptive sensitivity calibration. '
        'Short windows detect shock regimes; long windows detect structural decay. '
        'Zero look-ahead bias.</p>',
        unsafe_allow_html=True,
    )

    hv_c1, hv_c2, hv_c3 = st.columns([2, 1, 1])
    with hv_c1:
        era_key = st.selectbox("Crisis Era", list(CRISIS_ERAS.keys()),
                                format_func=lambda k: CRISIS_ERAS[k]["label"])
    with hv_c2:
        hv_lookback = st.selectbox("Lookback Window", [20, 40, 60, 90, 120], index=2)
    with hv_c3:
        hv_benchmark = st.selectbox("Benchmark", ["SPY", "QQQ", "IWM", "EFA"], index=0)

    hv_tickers_raw = tks.split(",") if tks else None

    if st.button("Run Walk-Forward Analysis", type="primary"):
        with st.spinner("Computing walk-forward GSRI..."):
            hv_result = compute_walkforward_gsri(
                tickers=hv_tickers_raw, era_key=era_key,
                lookback=hv_lookback, benchmark=hv_benchmark,
            )

        if _err(hv_result):
            pass
        else:
            era = hv_result["era"]
            gsri_df = hv_result["gsri_series"]
            bm_prices = hv_result["benchmark_prices"]
            regime = hv_result["regime"]
            crash_ts = pd.to_datetime(era["crash_date"])
            bottom_ts = pd.to_datetime(era["bottom_date"])

            # ---- Regime banner ----
            regime_colors = {
                "Structural Decay": ELEVATED, "Exogenous Shock": CRITICAL,
                "Early Warning": SAFE, "Exogenous Shock (Reactive)": ELEVATED,
                "Below Threshold": NEUTRAL,
            }
            rc = regime_colors.get(regime["regime"], NEUTRAL)

            # Regime definitions for the tooltip
            regime_help = {
                "Structural Decay": (
                    "The GSRI crossed the Elevated threshold (50) more than 100 trading days "
                    "before the crash date. This indicates a slow, sustained buildup of systemic "
                    "fragility — rising cross-asset correlation, deteriorating liquidity, and "
                    "increasing concentration risk accumulating over months. "
                    "Analogous to the subprime credit buildup in 2007–2008."
                ),
                "Exogenous Shock": (
                    "The GSRI crossed Elevated within 10 days of the crash, driven by the "
                    "Shock Multiplier (1.25×) activating when volatility or drawdown doubled "
                    "within 5 trading days. This indicates a sudden, external dislocation — "
                    "the system went from calm to crisis faster than the lookback window "
                    "could detect through gradual buildup. Analogous to COVID-19 in March 2020."
                ),
                "Early Warning": (
                    "The GSRI reached Elevated between 10 and 100 days before the crash. "
                    "The signal provided actionable lead time for portfolio hedging."
                ),
                "Exogenous Shock (Reactive)": (
                    "The Shock Multiplier activated during the crash as volatility doubled "
                    "within 5 days, but the GSRI only crossed Elevated after the crash began. "
                    "The speed of the dislocation exceeded the lookback window's capacity "
                    "for advance warning, but the system correctly identified the break in real-time."
                ),
                "Below Threshold": (
                    "The GSRI did not reach the Elevated threshold (50) for this era and "
                    "lookback configuration. Try a shorter lookback window for faster sensitivity "
                    "or add more diverse tickers to increase cross-asset signal coverage."
                ),
            }

            help_text = regime_help.get(regime["regime"], "")
            st.markdown(
                f"<div class='gate-banner' style='background-color:{rc};'>"
                f"<h1>{regime['regime'].upper()}</h1>"
                f"<p>Lead time: {regime['lead_days']} trading days</p>"
                f"</div>", unsafe_allow_html=True,
            )
            # Help tooltip explaining what this regime means
            st.caption(
                f"ⓘ **What is {regime['regime']}?** — {help_text}"
            )

            # ---- Metrics ----
            pre_crash = gsri_df[gsri_df["date"] < crash_ts]
            pre_peak = pre_crash["gsri"].max() if not pre_crash.empty else 0
            overall_peak = gsri_df["gsri"].max()
            shock_fired = gsri_df["shock_multiplier"].max() > 1.0

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Pre-Crash Peak", f"{pre_peak:.1f}")
            mc2.metric("Overall Peak", f"{overall_peak:.1f}")
            mc3.metric("Lead Time", f"{regime['lead_days']}d")
            mc4.metric(
                "Shock ×1.25",
                "Fired" if shock_fired else "Inactive",
                help=(
                    "The Shock Multiplier activates when Volatility or Drawdown scores "
                    "double (increase by 100%+) within any rolling 5-day window. When active, "
                    "the final GSRI is multiplied by 1.25× to reflect the acceleration of "
                    "systemic stress. This ensures fast-moving events like COVID break past "
                    "the Elevated threshold even when longer lookback windows dilute the signal."
                ),
            )

            # ---- Crisis Narrative ----
            st.markdown("### Crisis Narrative")
            st.info(regime["narrative"])

            st.markdown("---")

            # ---- Dual-axis chart with RISK ZONE SHADING ----
            st.markdown("### GSRI vs. Benchmark Price")

            from plotly.subplots import make_subplots
            fig = make_subplots(specs=[[{"secondary_y": True}]])

            # Risk zone background shading on the secondary (GSRI) y-axis
            zone_defs = [
                (0, 30, "rgba(74,124,89,0.07)", "Normal"),
                (30, 50, "rgba(196,144,50,0.07)", "Monitoring"),
                (50, 75, "rgba(196,144,50,0.15)", "Elevated"),
                (75, 100, "rgba(184,50,50,0.12)", "Critical"),
            ]
            for y0, y1, color, label in zone_defs:
                fig.add_hrect(
                    y0=y0, y1=y1, fillcolor=color, line_width=0,
                    secondary_y=True,
                    annotation_text=label, annotation_position="right",
                    annotation_font_size=9, annotation_font_color=TX3,
                )

            # Benchmark price
            if not bm_prices.empty:
                fig.add_trace(go.Scatter(
                    x=bm_prices.index, y=bm_prices.values,
                    name=f"{hv_benchmark} Price", mode="lines",
                    line=dict(color="#6888a8", width=1.5),
                ), secondary_y=False)

            # GSRI
            fig.add_trace(go.Scatter(
                x=gsri_df["date"], y=gsri_df["gsri"],
                name="GSRI", mode="lines",
                line=dict(color="#d4a24e", width=2.5),
            ), secondary_y=True)

            # Shock multiplier markers
            shocked = gsri_df[gsri_df["shock_multiplier"] > 1.0]
            if not shocked.empty:
                fig.add_trace(go.Scatter(
                    x=shocked["date"], y=shocked["gsri"],
                    name="Shock ×1.25", mode="markers",
                    marker=dict(color=CRITICAL, size=6, symbol="triangle-up"),
                ), secondary_y=True)

            # Crisis lines
            for ts, color, label, ypos in [
                (crash_ts, CRITICAL, era["annotation"], 0.95),
                (bottom_ts, SAFE, "Market Bottom", 0.05),
            ]:
                fig.add_shape(type="line", x0=ts, x1=ts, y0=0, y1=1,
                              yref="paper", line=dict(color=color, width=1.5, dash="dash"))
                fig.add_annotation(x=ts, y=ypos, yref="paper", text=label,
                                    showarrow=False, font=dict(color=color, size=10),
                                    xanchor="left", xshift=5)

            fig.update_layout(
                **_cl(520, legend=dict(orientation="h", y=-0.12)),
                yaxis_title=f"{hv_benchmark} Price ($)",
                yaxis2_title="GSRI (0–100)",
            )
            fig.update_yaxes(range=[0, 100], secondary_y=True, gridcolor=GRID)
            st.plotly_chart(fig, use_container_width=True)

            # ---- Indicator Breakdown ----
            st.markdown("### Indicator Breakdown")
            fig2 = go.Figure()
            for col, (color, label) in {
                "volatility": ("#8a7e6a", "Volatility"),
                "correlation": ("#5c7fa0", "Correlation"),
                "liquidity": ("#7a6888", "Liquidity"),
                "drawdown": ("#5c8a72", "Drawdown"),
            }.items():
                fig2.add_trace(go.Scatter(
                    x=gsri_df["date"], y=gsri_df[col], name=label,
                    mode="lines", line=dict(color=color, width=1.5)))

            fig2.add_trace(go.Scatter(
                x=gsri_df["date"], y=gsri_df["gsri"], name="GSRI",
                mode="lines", line=dict(color="#d4a24e", width=2.5)))

            for ts, color in [(crash_ts, CRITICAL), (bottom_ts, SAFE)]:
                fig2.add_shape(type="line", x0=ts, x1=ts, y0=0, y1=1,
                              yref="paper", line=dict(color=color, width=1.5, dash="dash"))

            fig2.update_layout(**_cl(400, yaxis_title="Score (0–100)"))
            st.plotly_chart(fig2, use_container_width=True)

            # ---- Signal Snapshot ----
            st.markdown("### Signal Snapshot")
            snap = hv_result["signal_snapshots"]
            if not snap.empty:
                st.dataframe(snap, hide_index=True, use_container_width=True)

            # ---- Methodology ----
            st.markdown("---")
            th = hv_result["thresholds"]
            st.markdown(
                f"**Methodology**: {hv_lookback}-day lookback. "
                f"Thresholds — Vol: [{th['vol'][0]:.0%}, {th['vol'][1]:.0%}], "
                f"Corr: [{th['corr'][0]}, {th['corr'][1]}], "
                f"DD: [{th['dd'][0]:.0%}, {th['dd'][1]:.0%}]. "
                f"Shock multiplier: ×{SHOCK_MULTIPLIER} on 5-day doubling. "
                f"Tickers: {', '.join(hv_result['tickers_used'])}."
            )
