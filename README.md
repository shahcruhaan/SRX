# SRX Platform — Systemic Risk Exchange

A research prototype that demonstrates how systemic risk analytics, crash protection pricing, and clearinghouse safety mechanisms could work in a centralized exchange.

**This is not a trading platform.** It is a working proof-of-concept built in Python that you can run on your own computer.

---

## What Does This Project Do?

Imagine you could buy insurance against a stock market crash — not just for one stock, but for your entire portfolio. And imagine the price of that insurance went up automatically when the financial system became more stressed, and the exchange itself had circuit breakers that activated during a crisis to prevent a total meltdown.

That's what SRX simulates. Specifically, it:

1. **Measures portfolio risk (PRI)** — Scores your portfolio from 0 to 100 based on volatility, correlation, concentration, and tail risk.

2. **Detects systemic stress (SRS & GSRI)** — Watches market-wide signals like cross-asset correlation spikes, liquidity dry-ups, and drawdown acceleration to produce a single "danger number" for the entire financial system.

3. **Prices crash protection** — Calculates what it would cost to insure a portfolio against a crash, with premiums that adjust automatically based on systemic risk.

4. **Stress tests portfolios** — Simulates five historical/hypothetical scenarios (2008 crisis, COVID crash, rate shock, liquidity freeze, crypto contagion) and shows what would happen to your portfolio.

5. **Simulates a clearinghouse safety net** — Runs losses through a 5-layer "default waterfall" that shows how the system absorbs member failures before they become systemic.

6. **Enforces dynamic circuit breakers** — Automatically restricts platform activity when risk crosses critical thresholds (margin increases, contract freezes, contingent capital calls).

7. **Displays everything in an interactive dashboard** — A professional dark-themed web interface where you can explore all of the above with sliders, charts, and real market data.

---

## Folder Structure

```
srx-platform/
│
├── backend/                          ← The calculation engines
│   ├── __init__.py                   ← Tells Python this folder is a package
│   ├── main.py                       ← FastAPI server (connects everything)
│   ├── portfolio_engine.py           ← PRI score, SRS per asset, weight validation
│   ├── gsri_engine.py                ← GSRI, SRS time series, Amihud liquidity
│   ├── pricing_engine.py             ← Crash protection premium pricing
│   ├── stress_engine.py              ← 5 stress scenarios + projected PRI
│   ├── clearinghouse_simulation.py   ← Default waterfall (5 layers)
│   └── gating_engine.py              ← Dynamic gating / circuit breakers
│
├── data/                             ← Market data layer
│   ├── __init__.py                   ← Tells Python this folder is a package
│   ├── market_data.py                ← Downloads + caches Yahoo Finance data
│   └── cache/                        ← Saved CSV files (auto-generated)
│
├── frontend/                         ← Visual interface
│   ├── __init__.py                   ← Tells Python this folder is a package
│   └── dashboard.py                  ← Streamlit dashboard (7 sections)
│
├── docs/                             ← Documentation
│   └── srx_whitepaper.tex            ← LaTeX whitepaper placeholder
│
├── requirements.txt                  ← List of Python packages to install
└── README.md                         ← This file
```

---

## Setup Guide (Step by Step)

You need a Mac (or Linux) computer with internet access. Every click and command is explained below.

### Step 1: Install Python

1. Go to [python.org/downloads](https://python.org/downloads) in your browser.
2. Click the big yellow "Download Python 3.x.x" button.
3. Open the downloaded `.pkg` file and click "Continue" through the installer.
4. When it says "Installation was successful," you're done.

To verify, open Terminal (press `Cmd + Space`, type "Terminal", press Enter) and type:

```bash
python3 --version
```

You should see something like `Python 3.12.x` or `Python 3.13.x`.

### Step 2: Install VS Code (optional but recommended)

1. Go to [code.visualstudio.com](https://code.visualstudio.com).
2. Download and install it.
3. Open it, click the Extensions icon (four squares on the left sidebar), search for "Python", and install the one by Microsoft.

### Step 3: Create the project folder

Open Terminal and run these commands one at a time:

```bash
cd ~/Desktop
mkdir srx-platform
cd srx-platform
```

### Step 4: Create a virtual environment

A virtual environment keeps this project's packages separate from everything else on your computer:

```bash
python3 -m venv venv
```

### Step 5: Activate the virtual environment

```bash
source venv/bin/activate
```

You should now see `(venv)` at the beginning of your terminal line. This means you're inside the virtual environment.

**Important:** Every time you close Terminal and come back, you need to run these two commands again:

```bash
cd ~/Desktop/srx-platform
source venv/bin/activate
```

### Step 6: Install all required packages

```bash
pip install -r requirements.txt
```

You'll see text scrolling by as packages download. Wait until the cursor comes back with `(venv)` at the start.

### Step 7: Verify everything installed

```bash
python3 -c "import fastapi, streamlit, yfinance, pandas, numpy, plotly; print('All packages installed successfully.')"
```

You should see: `All packages installed successfully.`

---

## How to Run the Platform

You need **two Terminal windows** running at the same time.

### Terminal 1 — Start the backend API server

```bash
cd ~/Desktop/srx-platform
source venv/bin/activate
python3 -m uvicorn backend.main:app --reload --port 8000
```

Wait until you see:

```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

**Leave this terminal running.** Don't close it.

### Terminal 2 — Start the dashboard

Open a **new** Terminal window (`Cmd + N`) and run:

```bash
cd ~/Desktop/srx-platform
source venv/bin/activate
streamlit run frontend/dashboard.py
```

Your browser should open automatically to `http://localhost:8501`.

If it doesn't, open your browser and go to that address manually.

### What you should see

A dark-themed dashboard with a sidebar on the left for navigation and inputs. The Overview page shows four key metrics (GSRI, SRS, PRI, Gate Level) and a GSRI history chart. Use the sidebar to switch between the 7 sections.

---

## Testing Individual Modules

You can test any engine module by itself without starting the full server:

```bash
cd ~/Desktop/srx-platform
source venv/bin/activate

# Test market data downloading
python3 -m data.market_data

# Test portfolio risk analysis
python3 -m backend.portfolio_engine

# Test GSRI and SRS computation
python3 -m backend.gsri_engine

# Test stress scenarios
python3 -m backend.stress_engine

# Test crash protection pricing
python3 -m backend.pricing_engine

# Test clearinghouse waterfall
python3 -m backend.clearinghouse_simulation

# Test dynamic gating
python3 -m backend.gating_engine
```

Each module has a built-in test suite at the bottom that runs when you execute it directly.

---

## API Endpoints

Once the backend is running, you can test endpoints in your browser:

| URL | What It Does |
|---|---|
| http://localhost:8000 | Confirms the server is running |
| http://localhost:8000/docs | Interactive API documentation (auto-generated) |
| http://localhost:8000/health | Checks all engine modules are working |
| http://localhost:8000/pri?tickers=SPY,TLT,GLD | Portfolio Risk Index |
| http://localhost:8000/gsri | Global Systemic Risk Index |
| http://localhost:8000/srs-gsri | Combined SRS + GSRI snapshot |
| http://localhost:8000/stress?scenario=covid_crash | Stress test |
| http://localhost:8000/price?notional=1000000 | Protection pricing |
| http://localhost:8000/run-waterfall-stress-test?event_magnitude=500000000 | Clearinghouse stress test |
| http://localhost:8000/gating | Current gate status |

---

## What Each Python File Does

### Data Layer

**`data/market_data.py`** (687 lines)
Downloads stock, bond, gold, dollar, and Bitcoin prices from Yahoo Finance. Caches data as CSV files so you don't re-download every time. Uses an inner join across all assets so only shared trading dates remain (removes crypto weekends, stock market holidays). Provides three main functions: `get_market_prices()`, `get_market_returns()`, `get_market_volume()`.

### Backend Engines

**`backend/portfolio_engine.py`** (961 lines)
Calculates the Portfolio Risk Index (PRI) — a 0-100 score combining volatility, correlation, concentration, and tail risk. Also validates portfolio weights, computes max drawdown, and calculates per-asset Systemic Risk Scores (SRS). Contains `validate_weights()`, `compute_max_drawdown()`, `build_pri_timeseries()`, and `calculate_pri()`.

**`backend/gsri_engine.py`** (988 lines)
Computes the Global Systemic Risk Index (GSRI) and the full Systemic Risk Score (SRS). The SRS is built from four raw signals: volatility (V_t), liquidity via the Amihud ratio (L_t), cross-asset correlation (C_t), and drawdown acceleration (M_t). These are combined using a non-linear power function calibrated to historical crises. The GSRI combines asset-class-specific stress: equity volatility, credit stress, treasury volatility, crypto volatility, and cross-asset correlation.

**`backend/pricing_engine.py`** (799 lines)
Prices crash protection contracts using an actuarial formula: `Premium = Notional × BaseRate × SRS_Multiplier × PortfolioRiskAdj × LiquidityAdj × RiskLoading × DurationFactor × DepthFactor`. The SRS multiplier is quadratic above 50 — premiums accelerate as systemic risk rises. Also generates payout profiles showing what the contract pays at different drawdown levels.

**`backend/stress_engine.py`** (827 lines)
Runs five stress scenarios on a portfolio: 2008 Financial Crisis, COVID-19 Crash, Interest Rate Shock, Liquidity Freeze, and Crypto-Led Risk Contagion. For each scenario, applies asset-class-specific shocks, recomputes a projected (stressed) PRI, estimates stressed volatility, identifies the worst contributing asset, and provides recovery time estimates.

**`backend/clearinghouse_simulation.py`** (748 lines)
Simulates the SRX default waterfall — a 5-layer loss absorption structure. When a member defaults, losses flow through: (1) Defaulter Initial Margin, (2) Defaulter Default Fund, (3) Defaulter Contingent Capital, (4) Mutualized Default Fund, (5) SRX Clearinghouse Capital. Each layer reports its status as INTACT, PARTIALLY DEPLETED, or EXHAUSTED. If all layers are breached, the system has failed.

**`backend/gating_engine.py`** (640 lines)
Implements dynamic circuit breakers based on the SRS. Four gate levels: Normal (SRS ≤ 70), Elevated (SRS > 70, margins increase), Restricted (SRS > 85, new contracts blocked), Critical (SRS > 95, contingent capital calls activated, redemptions frozen). Also provides integration helpers for the pricing engine and clearinghouse.

**`backend/main.py`** (681 lines)
The FastAPI server that connects all engines to HTTP endpoints. Exposes 15 endpoints (8 original + 7 new) including a health check, raw market data access, combined PRI+SRS analysis, and POST support with Pydantic validation. This is the "brain" that the dashboard talks to.

### Frontend

**`frontend/dashboard.py`** (866 lines)
The Streamlit interactive dashboard with 7 sections: Overview, PRI Analysis, GSRI & SRS, Stress Testing, Protection Pricing, Default Waterfall, and Dynamic Gating. Uses a professional dark theme, 8 Plotly charts, and `st.cache_data` for performance. All user inputs (tickers, weights, notional, scenario, etc.) are in the sidebar.

### Project Total: 7,197 lines of Python across 9 modules.

---

## Common Beginner Errors and How to Fix Them

### "command not found: python3"

Python isn't installed or isn't in your PATH. Reinstall Python from python.org, then close and reopen Terminal.

### "No module named 'fastapi'" (or any other module)

You forgot to activate the virtual environment or install requirements. Run:

```bash
cd ~/Desktop/srx-platform
source venv/bin/activate
pip install -r requirements.txt
```

### You don't see (venv) at the start of your terminal line

The virtual environment isn't active. Run `source venv/bin/activate`. You need to do this every time you open a new Terminal window.

### "Cannot connect to the backend server" in the dashboard

The backend isn't running. You need TWO terminal windows — one for the backend (uvicorn) and one for the dashboard (streamlit). Start the backend first, wait until you see "Application startup complete," then start the dashboard.

### "Address already in use" when starting uvicorn

Another process is using port 8000. Either find the other Terminal window and press `Ctrl+C` to stop it, or use a different port: `python3 -m uvicorn backend.main:app --reload --port 8001` (and update `BACKEND_URL` in `dashboard.py` to match).

### "ModuleNotFoundError: No module named 'backend'"

You're running from the wrong folder. Make sure you're in the `srx-platform` folder:

```bash
cd ~/Desktop/srx-platform
```

Also make sure the `__init__.py` files exist in `backend/`, `data/`, and `frontend/`.

### First load is very slow (30-60 seconds)

This is normal on the first run. The backend is downloading 2 years of market data for multiple tickers from Yahoo Finance. After the first download, data is cached as CSV files in `data/cache/` and subsequent loads are fast.

### Dashboard looks plain white instead of dark

Go to the three-dot menu (⋮) in the top right of the dashboard, click Settings, then Theme, and choose "Dark."

### "No data returned for ticker 'XYZ'"

The ticker symbol might be misspelled or the stock might be delisted. Go to [finance.yahoo.com](https://finance.yahoo.com) and search for the ticker to verify it exists. Also check your internet connection.

### Data seems stale or outdated

The cache lasts 24 hours. To force a fresh download, delete the cache:

```bash
rm -rf ~/Desktop/srx-platform/data/cache/*
```

---

## How This Prototype Fits Into the Long-Term SRX Vision

This Python prototype is **Phase 1** of a larger startup vision. Here is how the pieces connect:

**Phase 1 — Research Prototype (this project):**
Proves the core concepts work. Demonstrates that systemic risk can be measured in real-time, that crash protection can be priced dynamically based on risk conditions, and that a clearinghouse safety net can be modeled and stress-tested. All running locally on one computer.

**Phase 2 — Technical Validation:**
Move from local Python scripts to cloud infrastructure. Replace Yahoo Finance with institutional data feeds. Add real-time streaming data instead of daily snapshots. Build proper databases for position and risk data. Harden the pricing model with academic peer review.

**Phase 3 — Regulatory Engagement:**
Present the prototype and research to financial regulators (SEC, CFTC, OFR). The whitepaper (in `docs/`) would be expanded into a formal regulatory proposal. Engage with existing clearinghouses (OCC, CME, DTCC) as potential partners or competitors.

**Phase 4 — Institutional Pilot:**
Partner with a small number of institutional participants (hedge funds, asset managers) to test the system with real positions and real capital. The 5-layer waterfall and gating logic would be legally formalized.

**Phase 5 — Production Exchange:**
Launch as a regulated exchange or clearinghouse offering systemic risk protection products. The Python engines would be rewritten in high-performance languages (Rust, C++) for production speed, but the logic and formulas would remain the same.

The key insight: **every formula, every threshold, every gating rule in this prototype is designed to be the same logic that would run in production.** The code is simple Python, but the ideas are production-grade.

---

## Tech Stack

| Tool | What It Does | Why We Use It |
|---|---|---|
| Python 3.12+ | Programming language | Beginner-friendly, great for finance |
| FastAPI | Backend API server | Fast, auto-generates docs, modern Python |
| Streamlit | Interactive dashboard | Build web UIs with pure Python, no HTML needed |
| yfinance | Market data downloader | Free access to Yahoo Finance data |
| pandas | Data tables and manipulation | The standard for financial data in Python |
| numpy | Fast math operations | Matrix math for portfolio calculations |
| plotly | Interactive charts | Professional charts that work in browsers |

---

## License

This is a research prototype. Not financial advice. Not a real exchange or trading platform.

---

*Built with care for the SRX vision.*
