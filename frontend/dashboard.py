"""
dashboard.py — SRX Platform | Self-Contained Monolithic Dashboard

Runs entirely via:  streamlit run frontend/dashboard.py
No FastAPI / uvicorn backend required.

All engine logic is imported directly from the Python modules.
Compatible with Streamlit Community Cloud deployment.
"""

import sys
import os
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np

# =============================================================================
# PATH SETUP — ensure backend/ and data/ are importable from any working dir
# =============================================================================

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# =============================================================================
# DIRECT ENGINE IMPORTS — zero HTTP, zero requests
# =============================================================================

from backend.portfolio_engine import calculate_pri, calculate_srs
from backend.gsri_engine import calculate_gsri
from backend.pricing_engine import price_protection
from backend.stress_engine import run_stress_test
from backend.clearinghouse_simulation import simulate_default_waterfall
from backend.gating_engine import evaluate_gating

# =============================================================================
# PAGE CONFIG
# =============================================================================

st.set_page_config(
    page_title="SRX | Systemic Risk Exchange",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =============================================================================
# THEME ENGINE
# =============================================================================

if "theme" not in st.session_state:
    st.session_state.theme = "Dark"

THEMES = {
    "Dark": {
        "bg": "#0f131a", "sidebar_bg": "#131820", "card_bg": "#1b2231",
        "border": "#2d3748", "text_primary": "#f1f5f9", "text_secondary": "#94a3b8",
        "text_muted": "#64748b", "heading_1": "#f1f5f9", "heading_3": "#94a3b8",
        "btn_bg": "#1e293b", "btn_border": "#334155", "btn_hover": "#283548",
        "divider": "#1e293b", "method_bg": "#1b2231", "method_border": "#2d3748",
        "method_term": "#cbd5e1", "method_desc": "#94a3b8", "method_header": "#94a3b8",
        "chart_template": "plotly_dark", "chart_font": "#94a3b8", "chart_grid": "#1e293b",
        "gauge_zone_0": "#162016", "gauge_zone_1": "#252014",
        "gauge_zone_2": "#251a14", "gauge_zone_3": "#251414",
        "gauge_tick": "#475569", "gauge_needle": "#f1f5f9",
        "sidebar_text": "#f1f5f9", "sidebar_caption": "#94a3b8",
        "label_color": "#94a3b8", "input_text": "#f1f5f9",
    },
    "Light": {
        "bg": "#f8fafc", "sidebar_bg": "#f1f5f9", "card_bg": "#ffffff",
        "border": "#e2e8f0", "text_primary": "#0f172a", "text_secondary": "#475569",
        "text_muted": "#64748b", "heading_1": "#0f172a", "heading_3": "#475569",
        "btn_bg": "#e2e8f0", "btn_border": "#cbd5e1", "btn_hover": "#d4dbe6",
        "divider": "#e2e8f0", "method_bg": "#ffffff", "method_border": "#e2e8f0",
        "method_term": "#1e293b", "method_desc": "#475569", "method_header": "#64748b",
        "chart_template": "plotly_white", "chart_font": "#475569", "chart_grid": "#e2e8f0",
        "gauge_zone_0": "#e8f5e9", "gauge_zone_1": "#fff8e1",
        "gauge_zone_2": "#fff3e0", "gauge_zone_3": "#ffebee",
        "gauge_tick": "#94a3b8", "gauge_needle": "#0f172a",
        "sidebar_text": "#0f172a", "sidebar_caption": "#475569",
        "label_color": "#334155", "input_text": "#0f172a",
    },
}

th = THEMES[st.session_state.theme]

R = {
    "safe": "#4a7c59", "elevated": "#c49032", "critical": "#b83232",
    "neutral": "#7c8a98",
    "line": "#8494a7" if st.session_state.theme == "Dark" else "#5a6a7a",
    "fill": "rgba(132,148,167,0.06)" if st.session_state.theme == "Dark" else "rgba(90,106,122,0.06)",
    "sub1": "#5c7fa0", "sub2": "#8a7e6a", "sub3": "#7a6888", "sub4": "#5c8a72",
}

# =============================================================================
# ADAPTIVE CSS — with light-mode contrast fixes
# =============================================================================

st.markdown(f"""
<style>
    .stApp {{
        background-color: {th['bg']} !important;
        color: {th['text_primary']} !important;
    }}

    /* --- Sidebar: full contrast override --- */
    section[data-testid="stSidebar"] {{
        background-color: {th['sidebar_bg']} !important;
        border-right: 1px solid {th['border']};
    }}
    section[data-testid="stSidebar"] * {{
        color: {th['sidebar_text']} !important;
    }}
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{
        color: {th['sidebar_caption']} !important;
    }}
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * {{
        color: {th['sidebar_caption']} !important;
    }}
    section[data-testid="stSidebar"] label {{
        color: {th['label_color']} !important;
    }}
    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stTextInput label,
    section[data-testid="stSidebar"] .stNumberInput label,
    section[data-testid="stSidebar"] .stSlider label {{
        color: {th['label_color']} !important;
    }}
    section[data-testid="stSidebar"] .stRadio label {{
        color: {th['sidebar_text']} !important;
    }}
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] h4,
    section[data-testid="stSidebar"] h5 {{
        color: {th['sidebar_text']} !important;
    }}
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span {{
        color: {th['sidebar_text']} !important;
    }}
    section[data-testid="stSidebar"] hr {{
        border-color: {th['border']} !important;
    }}

    /* --- Main area text --- */
    .stApp p, .stApp span, .stApp li {{
        color: {th['text_primary']} !important;
    }}

    /* --- Metric cards --- */
    [data-testid="stMetric"] {{
        background-color: {th['card_bg']} !important;
        border: 1px solid {th['border']};
        border-radius: 6px;
        padding: 14px 16px;
    }}
    [data-testid="stMetricValue"] {{
        color: {th['text_primary']} !important;
        font-family: 'SF Mono','Fira Code','Consolas',monospace;
        font-weight: 600;
    }}
    [data-testid="stMetricLabel"] {{
        color: {th['text_muted']} !important;
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }}
    [data-testid="stMetricDelta"] {{ font-size: 0.78rem; }}

    /* --- Typography --- */
    h1 {{ color: {th['heading_1']} !important; font-weight: 600 !important; letter-spacing: -0.01em; }}
    h2 {{ color: {th['text_primary']} !important; font-weight: 500 !important; }}
    h3 {{ color: {th['heading_3']} !important; font-weight: 500 !important; font-size: 1.05rem !important; }}

    /* --- Buttons --- */
    .stButton > button {{
        background-color: {th['btn_bg']} !important;
        color: {th['text_secondary']} !important;
        border: 1px solid {th['btn_border']};
        font-weight: 500; border-radius: 5px; letter-spacing: 0.02em;
    }}
    .stButton > button:hover {{
        background-color: {th['btn_hover']} !important;
        color: {th['text_primary']} !important;
    }}

    hr {{ border-color: {th['divider']} !important; }}
    .stDataFrame {{ border-radius: 6px; overflow: hidden; }}
    .stRadio > div {{ gap: 0.25rem; }}

    /* --- Methodology box --- */
    .method-box {{
        background-color: {th['method_bg']};
        border: 1px solid {th['method_border']};
        border-radius: 6px; padding: 20px 24px;
        margin: 8px 0 20px 0; line-height: 1.65;
    }}
    .method-box h4 {{
        color: {th['method_header']} !important;
        font-size: 0.75rem; text-transform: uppercase;
        letter-spacing: 0.08em; margin: 0 0 14px 0;
        padding-bottom: 10px; border-bottom: 1px solid {th['method_border']};
    }}
    .method-box .def-term {{ color: {th['method_term']} !important; font-weight: 600;
        font-family: 'SF Mono','Fira Code','Consolas',monospace; font-size: 0.85rem; }}
    .method-box .def-desc {{ color: {th['method_desc']} !important; font-size: 0.85rem; }}
    .method-box p {{ color: {th['method_desc']} !important; }}

    .gate-banner {{ padding: 20px; border-radius: 6px; text-align: center; margin: 10px 0; }}
    .gate-banner h1 {{ margin: 0 !important; font-size: 1.4rem !important; color: white !important; }}
    .gate-banner p {{ margin: 5px 0 0 0; font-size: 0.9rem; color: rgba(255,255,255,0.85) !important; }}

    .narrative {{ color: {th['text_muted']} !important; font-style: italic;
        font-size: 0.9rem; margin: -4px 0 18px 0; line-height: 1.5; }}
</style>
""", unsafe_allow_html=True)


# =============================================================================
# CHART LAYOUT HELPER
# =============================================================================

def _chart_layout(height=420, **kwargs):
    base = dict(
        template=th["chart_template"], height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=th["chart_font"], size=11),
        margin=dict(l=48, r=24, t=32, b=48),
        legend=dict(orientation="h", y=-0.14, font=dict(size=10, color=th["chart_font"])),
        xaxis=dict(gridcolor=th["chart_grid"], gridwidth=1),
        yaxis=dict(gridcolor=th["chart_grid"], gridwidth=1),
    )
    base.update(kwargs)
    return base


# =============================================================================
# CACHED DIRECT ENGINE CALLS — replace all call_backend() HTTP calls
# =============================================================================

@st.cache_data(ttl=300, show_spinner=False)
def _get_gsri(period="2y", rolling_window=60):
    try:
        return calculate_gsri(period=period, rolling_window=rolling_window)
    except Exception as e:
        return {"error": f"GSRI calculation failed: {e}"}

@st.cache_data(ttl=300, show_spinner=False)
def _get_pri(tickers_csv, weights_csv=None, period="2y"):
    try:
        tickers = [t.strip().upper() for t in tickers_csv.split(",") if t.strip()]
        weights = None
        if weights_csv and weights_csv.strip():
            weights = [float(w.strip()) for w in weights_csv.split(",")]
        return calculate_pri(tickers, weights, period)
    except Exception as e:
        return {"error": f"PRI calculation failed: {e}"}

@st.cache_data(ttl=300, show_spinner=False)
def _get_srs(tickers_csv, period="2y"):
    try:
        tickers = [t.strip().upper() for t in tickers_csv.split(",") if t.strip()]
        return calculate_srs(tickers, period=period)
    except Exception as e:
        return {"error": f"SRS calculation failed: {e}"}

@st.cache_data(ttl=300, show_spinner=False)
def _get_stress(tickers_csv, weights_csv=None, scenario="2008_crisis", custom_shock_pct=None, period="2y"):
    try:
        tickers = [t.strip().upper() for t in tickers_csv.split(",") if t.strip()]
        weights = None
        if weights_csv and weights_csv.strip():
            weights = [float(w.strip()) for w in weights_csv.split(",")]
        return run_stress_test(tickers, weights, scenario, custom_shock_pct, period)
    except Exception as e:
        return {"error": f"Stress test failed: {e}"}

@st.cache_data(ttl=300, show_spinner=False)
def _get_price(tickers_csv, weights_csv=None, notional=1_000_000, protection_level_pct=20.0, duration_days=90, period="2y"):
    try:
        tickers = [t.strip().upper() for t in tickers_csv.split(",") if t.strip()]
        weights = None
        if weights_csv and weights_csv.strip():
            weights = [float(w.strip()) for w in weights_csv.split(",")]
        return price_protection(tickers, weights, notional, protection_level_pct, duration_days, period)
    except Exception as e:
        return {"error": f"Pricing failed: {e}"}

def _get_waterfall(**kwargs):
    try:
        return simulate_default_waterfall(**kwargs)
    except Exception as e:
        return {"error": f"Waterfall simulation failed: {e}"}

def _get_gating(gsri_score=None, portfolio_pri=None):
    try:
        if gsri_score is None:
            gsri_result = calculate_gsri()
            if "error" in gsri_result:
                return {"error": f"Could not calculate GSRI for gating: {gsri_result['error']}"}
            gsri_score = gsri_result["current_gsri"]
        return evaluate_gating(gsri_score, portfolio_pri)
    except Exception as e:
        return {"error": f"Gating evaluation failed: {e}"}


def show_error(result):
    if isinstance(result, dict) and "error" in result:
        st.error(result["error"])
        return True
    return False


# =============================================================================
# SIDEBAR
# =============================================================================

with st.sidebar:
    st.markdown("## ◆ &nbsp;SRX Platform")
    st.caption("Systemic Risk Exchange")

    theme_choice = st.selectbox("Theme", ["Dark", "Light"],
        index=0 if st.session_state.theme == "Dark" else 1,
        help="Switch between Slate & Navy (dark) and Institutional White (light).")
    if theme_choice != st.session_state.theme:
        st.session_state.theme = theme_choice
        st.rerun()

    st.markdown("---")
    page = st.radio("Navigation",
        ["Overview", "Portfolio Risk Index", "GSRI & SRS", "Stress Testing",
         "Protection Pricing", "Default Waterfall", "Dynamic Gating"],
        label_visibility="collapsed")

    st.markdown("---")
    st.markdown("##### Portfolio")
    ticker_input = st.text_input("Tickers", value="SPY,HYG,TLT,GLD,BTC-USD", help="Comma-separated ticker symbols.")
    weight_input = st.text_input("Weights", value="0.40,0.20,0.20,0.10,0.10", help="Comma-separated. Must sum to 1.0.")
    period = st.selectbox("Period", ["1y", "2y", "5y"], index=1)

    st.markdown("---")
    st.markdown("##### Pricing Parameters")
    notional = st.number_input("Notional ($)", min_value=10_000, max_value=100_000_000, value=1_000_000, step=100_000, format="%d")
    protection_level = st.slider("Protection Level (%)", 5, 50, 20)
    duration = st.selectbox("Duration (days)", [30, 60, 90, 180, 365], index=2)
    liquidity_adj = st.slider("Liquidity Adjustment", 0.5, 2.0, 1.0, step=0.05, help="1.0 = standard.")

    st.markdown("---")
    st.markdown("##### Stress Scenario")
    scenario = st.selectbox("Scenario",
        ["2008_crisis", "covid_crash", "rate_shock", "liquidity_freeze", "crypto_contagion", "custom"],
        format_func=lambda x: {"2008_crisis": "2008 Financial Crisis", "covid_crash": "COVID-19 Crash",
            "rate_shock": "Interest Rate Shock", "liquidity_freeze": "Liquidity Freeze",
            "crypto_contagion": "Crypto Contagion", "custom": "Custom Shock"}.get(x, x))
    custom_shock = None
    if scenario == "custom":
        custom_shock = st.number_input("Custom Shock (%)", -90.0, 0.0, -25.0)

    st.markdown("---")
    st.caption("Research prototype. Not financial advice.")

tickers_str = ",".join([s.strip().upper() for s in ticker_input.split(",") if s.strip()])
weights_str = weight_input.strip() if weight_input.strip() else None


# =============================================================================
# PAGE 1: OVERVIEW
# =============================================================================

if page == "Overview":
    st.markdown("# Executive Overview")
    st.markdown('<p class="narrative">Real-time systemic risk assessment across portfolio, market, and clearinghouse dimensions.</p>', unsafe_allow_html=True)
    st.markdown("""<div class="method-box">
        <h4>Systemic Risk Exchange &nbsp;|&nbsp; Platform Methodology</h4>
        <p><span class="def-term">PRI</span> <span class="def-desc">(Portfolio Risk Index): A normalized time series starting at 100, tracking the value and risk profile of the specific user portfolio.</span></p>
        <p><span class="def-term">SRS</span> <span class="def-desc">(Systemic Risk Score): A 0–100 score measuring real-time stress across volatility, liquidity, and correlation.</span></p>
        <p><span class="def-term">GSRI</span> <span class="def-desc">(Global Systemic Risk Index): An institutional benchmark of global financial stability.</span></p>
        <p><span class="def-term">Protection Premium</span> <span class="def-desc">: The model-implied cost to insure the current notional against systemic shocks.</span></p>
    </div>""", unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        with st.spinner("Loading GSRI..."):
            gsri_data = _get_gsri(period=period)
        if not show_error(gsri_data):
            st.metric("GSRI", f"{gsri_data['current_gsri']:.1f}", gsri_data["risk_level"],
                       help="Global Systemic Risk Index — aggregate benchmark across major asset classes.")
    with col2:
        srs_val = gsri_data.get("srs_current", 0) if isinstance(gsri_data, dict) and "srs_current" in gsri_data else 0
        st.metric("SRS", f"{srs_val:.1f}", "Systemic Risk Score",
                   help="0–100 score. 0–70 = Normal. 70–85 = Elevated. Above 85 = Critical.")
    with col3:
        with st.spinner("Loading PRI..."):
            pri_data = _get_pri(tickers_str, weights_str, period)
        if not show_error(pri_data):
            st.metric("PRI", f"{pri_data['pri']:.1f}", pri_data["risk_level"],
                       help="Portfolio Risk Index — composite 0–100 score of portfolio-specific risk.")
    with col4:
        with st.spinner("Loading gating..."):
            gate_data = _get_gating()
        if not show_error(gate_data):
            st.metric("Gate Status", f"Level {gate_data['level']}", gate_data["label"],
                       help="Dynamic gating level based on real-time SRS thresholds.")

    st.markdown("---")
    if isinstance(gsri_data, dict) and "gsri_history" in gsri_data:
        history_df = pd.DataFrame(gsri_data["gsri_history"])
        if not history_df.empty:
            st.markdown("### Global Systemic Risk Index — Historical")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=history_df["date"], y=history_df["gsri"], mode="lines", name="GSRI",
                line=dict(color=R["line"], width=2), fill="tozeroy", fillcolor=R["fill"]))
            for cn, clr in [("correlation", R["sub1"]), ("volatility", R["sub2"]), ("credit", R["sub3"]), ("tail", R["sub4"])]:
                if cn in history_df.columns:
                    fig.add_trace(go.Scatter(x=history_df["date"], y=history_df[cn], mode="lines", name=cn.title(),
                        line=dict(width=1, dash="dot", color=clr), opacity=0.45))
            fig.add_hline(y=30, line_dash="dot", line_color=R["safe"], annotation_text="Low", annotation_font_size=10, annotation_font_color=th["text_muted"])
            fig.add_hline(y=55, line_dash="dot", line_color=R["elevated"], annotation_text="Elevated", annotation_font_size=10, annotation_font_color=th["text_muted"])
            fig.add_hline(y=75, line_dash="dot", line_color=R["critical"], annotation_text="Critical", annotation_font_size=10, annotation_font_color=th["text_muted"])
            fig.update_layout(**_chart_layout(420, yaxis_title="Score"))
            st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# PAGE 2: PORTFOLIO RISK INDEX
# =============================================================================

elif page == "Portfolio Risk Index":
    st.markdown("# Portfolio Risk Index (PRI)")
    st.markdown('<p class="narrative">Composite risk assessment across volatility, correlation, concentration, and tail risk dimensions.</p>', unsafe_allow_html=True)
    if st.button("Calculate PRI", type="primary"):
        with st.spinner("Computing PRI..."):
            result = _get_pri(tickers_str, weights_str, period)
        if not show_error(result):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("PRI Score", f"{result['pri']:.1f} / 100", result["risk_level"])
            c2.metric("Annualized Volatility", f"{result['portfolio_volatility_annual']:.1f}%")
            c3.metric("Max Drawdown", f"{result.get('max_drawdown_pct', 'N/A')}%")
            c4.metric("Sharpe Ratio", f"{result.get('sharpe_ratio', 'N/A')}")
            st.markdown("---")
            cl, cr = st.columns([3, 2])
            with cl:
                st.markdown("### Risk Component Breakdown")
                cats = ["Volatility", "Correlation", "Concentration", "Tail Risk"]
                vals = [result["volatility_score"], result["correlation_score"], result["concentration_score"], result["tail_risk_score"]]
                polar_fill = "rgba(132,148,167,0.10)" if st.session_state.theme == "Dark" else "rgba(90,106,122,0.08)"
                fig = go.Figure(data=go.Scatterpolar(r=vals+[vals[0]], theta=cats+[cats[0]], fill="toself",
                    fillcolor=polar_fill, line=dict(color=R["line"], width=2)))
                fig.update_layout(**_chart_layout(380),
                    polar=dict(radialaxis=dict(visible=True, range=[0, 100], gridcolor=th["chart_grid"], color=th["chart_font"]),
                               angularaxis=dict(color=th["chart_font"]), bgcolor="rgba(0,0,0,0)"))
                st.plotly_chart(fig, use_container_width=True)
            with cr:
                st.markdown("### Portfolio Composition")
                st.dataframe(pd.DataFrame({"Ticker": result["tickers"], "Weight": [f"{w*100:.1f}%" for w in result["weights"]]}), hide_index=True, use_container_width=True)
                if result.get("cumulative_return_pct") is not None:
                    st.markdown("### Performance")
                    st.write(f"Cumulative Return: **{result['cumulative_return_pct']:.2f}%**")
                    st.write(f"Annualized Return: **{result.get('annualized_return_pct', 'N/A')}%**")
    st.markdown("---")
    st.markdown("### Systemic Risk Scores (SRS) — Per Asset")
    st.markdown('<p class="narrative">Individual asset contribution to systemic risk.</p>', unsafe_allow_html=True)
    if st.button("Calculate SRS"):
        with st.spinner("Computing SRS..."):
            srs_result = _get_srs(tickers_str, period)
        if not show_error(srs_result):
            scores = srs_result.get("scores", {})
            rows = [{"Ticker": tk, "SRS": d["srs"], "Risk Level": d["risk_level"], "Beta": d["beta"], "Volatility (%)": d["volatility_annual_pct"]}
                    for tk, d in scores.items() if d.get("srs") is not None]
            if rows:
                srs_df = pd.DataFrame(rows).sort_values("SRS", ascending=False)
                fig = px.bar(srs_df, x="Ticker", y="SRS", color="SRS",
                    color_continuous_scale=[[0, R["safe"]], [0.5, R["neutral"]], [0.75, R["elevated"]], [1.0, R["critical"]]],
                    range_color=[0, 100], text="SRS")
                fig.update_layout(**_chart_layout(380))
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(srs_df, hide_index=True, use_container_width=True)


# =============================================================================
# PAGE 3: GSRI & SRS
# =============================================================================

elif page == "GSRI & SRS":
    st.markdown("# Global Systemic Risk Index (GSRI)")
    st.markdown('<p class="narrative">Institutional benchmark combining equity volatility, credit stress, treasury dynamics, crypto volatility, and cross-asset correlation.</p>', unsafe_allow_html=True)
    rolling_window = st.slider("Rolling Window (trading days)", 20, 120, 60, step=10)
    if st.button("Calculate GSRI", type="primary"):
        with st.spinner("Computing GSRI & SRS..."):
            result = _get_gsri(period=period, rolling_window=rolling_window)
        if not show_error(result):
            cl, cr = st.columns([1, 2])
            with cl:
                st.metric("Current GSRI", f"{result['current_gsri']:.1f}", help="Aggregate systemic risk benchmark.")
                st.info(result["risk_level"])
                st.metric("Current SRS", f"{result.get('srs_current', 0):.1f}", help="0–70 Normal. 70–85 Elevated. 85+ Critical.")
                st.markdown("**GSRI Sub-Scores**")
                for name, val in result.get("sub_scores", {}).items():
                    st.progress(min(val / 100.0, 1.0), text=f"{name.replace('_', ' ').title()}: {val:.1f}")
                srs_comp = result.get("srs_components", {})
                if srs_comp:
                    st.markdown("**SRS Components**")
                    for name, val in srs_comp.items():
                        st.progress(min(val / 100.0, 1.0), text=f"{name.replace('_', ' ').title()}: {val:.1f}")
            with cr:
                history_df = pd.DataFrame(result.get("gsri_history", []))
                if not history_df.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=history_df["date"], y=history_df["gsri"], mode="lines", name="GSRI", line=dict(color=R["line"], width=2.5)))
                    for cn, clr in [("correlation", R["sub1"]), ("volatility", R["sub2"]), ("credit", R["sub3"]), ("tail", R["sub4"])]:
                        if cn in history_df.columns:
                            fig.add_trace(go.Scatter(x=history_df["date"], y=history_df[cn], mode="lines", name=cn.title(), line=dict(width=1, dash="dot", color=clr), opacity=0.45))
                    fig.add_hline(y=30, line_dash="dot", line_color=R["safe"])
                    fig.add_hline(y=55, line_dash="dot", line_color=R["elevated"])
                    fig.add_hline(y=75, line_dash="dot", line_color=R["critical"])
                    fig.update_layout(**_chart_layout(500, yaxis_title="Score"))
                    st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# PAGE 4: STRESS TESTING
# =============================================================================

elif page == "Stress Testing":
    st.markdown("# Stress Testing")
    st.markdown('<p class="narrative">Scenario analysis projecting portfolio impact under historical and hypothetical market dislocations.</p>', unsafe_allow_html=True)
    if st.button("Run Stress Test", type="primary"):
        with st.spinner("Running stress test..."):
            result = _get_stress(tickers_str, weights_str, scenario, custom_shock, period)
        if not show_error(result):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Portfolio Shock", f"{result['portfolio_shock_pct']:.1f}%")
            c2.metric("Stressed Value", f"${result['stressed_value']:.2f}")
            c3.metric("Severity", result["severity"])
            sp = result.get("stressed_pri")
            if sp is not None:
                c4.metric("Stressed PRI", f"{sp:.1f}", result.get("stressed_risk_level", ""))
            st.markdown("---")
            impact_df = pd.DataFrame(result["asset_impacts"])
            fig = go.Figure(go.Waterfall(name="Impact", orientation="v", x=impact_df["ticker"], y=impact_df["weighted_impact_pct"],
                text=[f"{v:+.2f}%" for v in impact_df["weighted_impact_pct"]], textposition="outside",
                connector=dict(line=dict(color=th["chart_grid"], width=1)),
                increasing=dict(marker=dict(color=R["safe"])), decreasing=dict(marker=dict(color=R["critical"]))))
            fig.update_layout(**_chart_layout(400, title="Per-Asset Contribution to Portfolio Shock", yaxis_title="Weighted Impact (%)"))
            st.plotly_chart(fig, use_container_width=True)
            cl, cr = st.columns(2)
            with cl:
                st.markdown("**Scenario Details**")
                st.write(f"Scenario: {result.get('scenario_name', result['scenario'])}")
                st.write(f"Recovery Estimate: {result.get('estimated_recovery_days', 'N/A')} trading days")
                sv = result.get("stressed_volatility_pct")
                if sv: st.write(f"Stressed Volatility: {sv:.1f}%")
            with cr:
                worst = result.get("worst_asset")
                if worst:
                    st.markdown("**Worst Contributing Asset**")
                    st.write(f"Ticker: **{worst['ticker']}** ({worst['shock_pct']:+.1f}%)")
                    st.write(f"Loss Contribution: {worst.get('contribution_to_loss_pct', 'N/A')}% of total")
            st.dataframe(impact_df, hide_index=True, use_container_width=True)


# =============================================================================
# PAGE 5: PROTECTION PRICING
# =============================================================================

elif page == "Protection Pricing":
    st.markdown("# Protection Pricing")
    st.markdown('<p class="narrative">Model-implied crash protection premium based on notional exposure and systemic stress conditions.</p>', unsafe_allow_html=True)
    if st.button("Price Protection", type="primary"):
        with st.spinner("Pricing protection contract..."):
            result = _get_price(tickers_str, weights_str, notional, protection_level, duration, period)
        if not show_error(result):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Premium", f"${result['premium_dollars']:,.2f}", help="Model-implied crash protection estimate.")
            c2.metric("Premium (bps)", f"{result['premium_bps']:.1f}")
            c3.metric("Max Payout", f"${result['max_payout_dollars']:,.2f}")
            c4.metric("Crash Probability", f"{result['historical_crash_probability']*100:.2f}%")
            st.markdown("---")
            cl, cr = st.columns(2)
            with cl:
                st.markdown("### Contract Specification")
                st.write(f"Notional: **${notional:,.0f}**")
                st.write(f"Protection Trigger: **-{protection_level}%**")
                st.write(f"Duration: **{duration} days**")
                st.write(f"GSRI at Pricing: **{result['gsri_used']:.1f}**")
                srs_u = result.get("srs_used")
                if srs_u is not None: st.write(f"SRS at Pricing: **{srs_u:.1f}**")
            with cr:
                st.markdown("### Premium Decomposition")
                mb = result.get("multiplier_breakdown", {})
                if mb:
                    st.dataframe(pd.DataFrame([
                        {"Component": "Base Rate", "Value": f"{mb.get('base_rate',0.01):.4f}"},
                        {"Component": "SRS Multiplier", "Value": f"{mb.get('srs_multiplier',1):.4f}x"},
                        {"Component": "Portfolio Risk Adj.", "Value": f"{mb.get('portfolio_risk_adjustment',1):.4f}x"},
                        {"Component": "Liquidity Adj.", "Value": f"{mb.get('liquidity_adjustment',1):.4f}x"},
                        {"Component": "Risk Loading", "Value": f"{mb.get('risk_loading',1.25):.4f}x"},
                        {"Component": "Duration Factor", "Value": f"{mb.get('duration_factor',1):.4f}x"},
                        {"Component": "Depth Factor", "Value": f"{mb.get('depth_factor',1):.4f}x"},
                        {"Component": "Combined", "Value": f"{mb.get('combined_multiplier',1):.4f}x"},
                    ]), hide_index=True, use_container_width=True)
            payout = result.get("payout_profile")
            if payout and "binary_payouts" in payout:
                st.markdown("---")
                st.markdown("### Payout Profile")
                pay_df = pd.DataFrame(payout["binary_payouts"])
                fig = go.Figure()
                fig.add_trace(go.Bar(x=[f"-{d}%" for d in pay_df["drawdown_pct"]], y=pay_df["portfolio_loss_dollars"], name="Portfolio Loss", marker_color=R["critical"], opacity=0.45))
                fig.add_trace(go.Bar(x=[f"-{d}%" for d in pay_df["drawdown_pct"]], y=pay_df["binary_payout_dollars"], name="Insurance Payout", marker_color=R["safe"], opacity=0.7))
                fig.update_layout(**_chart_layout(380, barmode="overlay", yaxis_title="Dollars ($)", xaxis_title="Portfolio Drawdown"))
                st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# PAGE 6: DEFAULT WATERFALL
# =============================================================================

elif page == "Default Waterfall":
    st.markdown("# Default Waterfall Simulation")
    st.markdown('<p class="narrative">Absorption of a major default event through the five-layer SRX capital structure.</p>', unsafe_allow_html=True)
    event_magnitude = st.number_input("Event Magnitude ($)", min_value=0, max_value=10_000_000_000, value=500_000_000, step=50_000_000, format="%d",
        help="e.g. 100000000 ($100M), 500000000 ($500M), 1000000000 ($1B)")
    with st.expander("Custom Layer Sizes"):
        lc1, lc2, lc3 = st.columns(3)
        with lc1:
            dm = st.number_input("Defaulter Margin ($)", value=200_000_000, step=10_000_000, format="%d")
            ddf = st.number_input("Defaulter Default Fund ($)", value=50_000_000, step=5_000_000, format="%d")
        with lc2:
            dcc = st.number_input("Defaulter Contingent Capital ($)", value=30_000_000, step=5_000_000, format="%d")
            mdf = st.number_input("Mutualized Default Fund ($)", value=500_000_000, step=50_000_000, format="%d")
        with lc3:
            srx_cap = st.number_input("SRX Clearinghouse Capital ($)", value=150_000_000, step=10_000_000, format="%d")
    if st.button("Run Waterfall Stress Test", type="primary"):
        result = _get_waterfall(defaulter_margin=dm, defaulter_guarantee_fund=ddf,
            platform_capital=dcc+srx_cap, other_members_guarantee_fund=mdf,
            emergency_assessment_capacity=0, loss_amount=event_magnitude)
        if not show_error(result):
            if result["unabsorbed_loss"] > 0:
                st.error(f"BREACH — {result['outcome']}")
                st.warning(result["outcome_detail"])
            else:
                st.success(f"CONTAINED — {result['outcome']}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Loss Event", f"${event_magnitude:,.0f}")
            c2.metric("Total Capacity", f"${result.get('total_waterfall_capacity', 0):,.0f}")
            c3.metric("Unabsorbed", f"${result['unabsorbed_loss']:,.0f}")
            st.markdown("---")
            layers_df = pd.DataFrame(result["layers"])
            fig = go.Figure()
            fig.add_trace(go.Bar(x=[f"L{r['layer']}: {r['name']}" for _, r in layers_df.iterrows()], y=layers_df["absorbed"], name="Loss Absorbed",
                marker_color=[R["critical"] if r["exhausted"] else R["elevated"] for _, r in layers_df.iterrows()],
                text=[f"${v:,.0f}" for v in layers_df["absorbed"]], textposition="outside"))
            remaining = layers_df["available"] - layers_df["absorbed"]
            fig.add_trace(go.Bar(x=[f"L{r['layer']}: {r['name']}" for _, r in layers_df.iterrows()], y=remaining, name="Remaining Capacity", marker_color=R["safe"], opacity=0.3))
            fig.update_layout(**_chart_layout(450, barmode="stack", title="Waterfall Layer Depletion", yaxis_title="Amount ($)"))
            st.plotly_chart(fig, use_container_width=True)
            display_df = layers_df.copy()
            for cn in ["available", "absorbed", "remaining_loss_after"]:
                if cn in display_df.columns:
                    display_df[cn] = display_df[cn].apply(lambda x: f"${x:,.2f}")
            st.dataframe(display_df, hide_index=True, use_container_width=True)


# =============================================================================
# PAGE 7: DYNAMIC GATING
# =============================================================================

elif page == "Dynamic Gating":
    st.markdown("# Dynamic Gating")
    st.markdown('<p class="narrative">Platform circuit breakers triggered by SRS thresholds to preserve clearinghouse integrity during stress.</p>', unsafe_allow_html=True)
    st.markdown("### Threshold Explorer")
    manual_srs = st.slider("Simulated SRS", 0.0, 100.0, 50.0, step=1.0)
    manual_pri = st.slider("Simulated PRI", 0.0, 100.0, 40.0, step=1.0)
    result = _get_gating(gsri_score=manual_srs / 1.1, portfolio_pri=manual_pri)
    if not show_error(result):
        color_map = {"green": R["safe"], "yellow": R["elevated"], "orange": R["elevated"], "red": R["critical"]}
        gate_color = color_map.get(result.get("color", ""), "#555")
        st.markdown(f"<div class='gate-banner' style='background-color:{gate_color};'>"
            f"<h1 style='color:white;'>GATE LEVEL {result['level']}: {result['label'].upper()}</h1>"
            f"<p style='color:rgba(255,255,255,0.85);'>{result['description']}</p></div>", unsafe_allow_html=True)
        if result.get("actions"):
            st.markdown("### Active Restrictions")
            for action in result["actions"]:
                st.write(f"• {action}")
        st.markdown("---")
        st.markdown("### System Status")
        c1, c2, c3, c4 = st.columns(4)
        mp = int((result["margin_multiplier"] - 1) * 100)
        c1.metric("Margin Multiplier", f"{result['margin_multiplier']:.2f}x", delta=f"+{mp}%" if mp > 0 else "Standard")
        c2.metric("New Positions", "Open" if result["new_positions_allowed"] else "Blocked")
        c3.metric("Redemptions", "Open" if result["redemptions_allowed"] else "Delayed")
        c4.metric("Forced De-leveraging", "Active" if result["forced_deleveraging"] else "Inactive")
        st.markdown("---")
        st.markdown("### SRS Threshold Map")
        fig = go.Figure()
        fig.add_trace(go.Indicator(mode="gauge+number", value=manual_srs,
            title={"text": "Systemic Risk Score", "font": {"size": 13, "color": th["text_muted"]}},
            number={"font": {"color": th["text_primary"]}},
            gauge=dict(axis=dict(range=[0, 100], tickcolor=th["gauge_tick"]), bar=dict(color=R["neutral"]),
                steps=[dict(range=[0,70], color=th["gauge_zone_0"]), dict(range=[70,85], color=th["gauge_zone_1"]),
                       dict(range=[85,95], color=th["gauge_zone_2"]), dict(range=[95,100], color=th["gauge_zone_3"])],
                threshold=dict(line=dict(color=th["gauge_needle"], width=2), value=manual_srs))))
        fig.update_layout(**_chart_layout(280))
        st.plotly_chart(fig, use_container_width=True)
    st.markdown("---")
    st.markdown("### Live Gating")
    if st.button("Check Live Gate Status"):
        with st.spinner("Calculating live GSRI and gating..."):
            live = _get_gating()
        if not show_error(live):
            st.info(f"Live Gate Level: **{live['level']} ({live['label']})** — GSRI: {live.get('gsri_input', 'N/A')}")
            if live.get("actions"):
                for action in live["actions"]:
                    st.write(f"• {action}")
