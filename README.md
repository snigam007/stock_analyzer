# Indian Stock Market Analyzer

A comprehensive, locally-hosted Python application for analyzing 500+ BSE/NSE stocks using 15 algorithms, ML forecasting, and sector analysis.

## 🚀 Quick Start

### Step 1: Install Python 3.10+
Download from [python.org](https://www.python.org/downloads/)

### Step 2: Run the Application
**Windows (Double-click):**
```
run.bat
```
This will:
1. Create a virtual environment
2. Install all dependencies  
3. Initialize the database (first-time, ~30-90 min)
4. Launch the Streamlit dashboard at http://localhost:8501

**Manual setup:**
```bash
# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Initialize database (one-time, downloads all historical data)
python initialize.py

# Launch dashboard
streamlit run app/main.py
```

---

## 📊 Features

### Data Coverage
- **500 NSE stocks** across 14 sectors (sector-balanced selection)
- **Full historical data** from 2000 to present
- **Daily auto-updates** at 6:30 PM IST via scheduler
- **6 Indexes**: NIFTY 50, SENSEX, NIFTY Bank, NIFTY IT, etc.
- **7 Commodities**: Gold, Silver, Crude Oil, Natural Gas, Copper, Wheat, USD/INR

### 15 Analysis Algorithms
| # | Algorithm | Signal Type |
|---|---|---|
| 1 | RSI (14) | Overbought/Oversold |
| 2 | MACD (12,26,9) | Momentum crossover |
| 3 | Bollinger Bands | Mean reversion |
| 4 | EMA Crossover (9/21/50/200) | Trend alignment |
| 5 | Volume Spike Analysis | Confirmation |
| 6 | ADX | Trend strength |
| 7 | Stochastic Oscillator | Momentum |
| 8 | CCI | Overbought/Oversold |
| 9 | OBV | Volume-price divergence |
| 10 | ATR | Volatility/Stop-loss |
| 11 | Prophet (Meta) | 7D–1Y forecast |
| 12 | Random Forest | BUY/SELL classification |
| 13 | Linear Regression | Trend slope |
| 14 | PCA + Correlation | Sector relationships |
| 15 | Z-Score Ranking | Percentile scoring |

### Signal Output
- **BUY 🟢 / SELL 🔴 / WATCH 🟡** with strength (STRONG/MODERATE/WEAK)
- **Buy Price** — recommended entry
- **Target 1 / Target 2 / Target 3** — progressive profit targets
- **Stop-Loss** — ATR-based dynamic stop
- **Risk-Reward Ratio**
- **Detailed reasons** for each signal

### Investment Classification
- **🛡️ SAFE** — Large-cap, low-beta, defensive sectors
- **⚖️ MODERATE** — Mid-cap, balanced risk
- **⚡ RISKY** — Small-cap, high-beta, momentum plays

### Trend Pattern
Displays last 20 days as: `↑↑↓↑↑↓↓↑↑↑`

### Sector Analysis
- Multi-period returns (1D/1W/1M/3M/6M/YTD)
- Sector correlation heatmap
- Sector rotation signals
- Cross-sector impact rules (direct/inverse)

---

## 📁 Project Structure
```
stock_analyzer/
├── app/                    # Streamlit UI (6 pages)
│   ├── main.py             # Landing page
│   └── pages/
│       ├── 2_Stock_Analysis.py
│       ├── 3_Sector_Analysis.py
│       ├── 4_Daily_Top_Stocks.py
│       ├── 5_Trends.py
│       └── 6_Strategies.py
├── core/                   # Analysis engine
│   ├── data_fetcher.py     # yfinance + anti-bot
│   ├── indicators.py       # 10 technical indicators
│   ├── signals.py          # Signal generation
│   ├── scoring.py          # Composite scoring
│   ├── ml_models.py        # Prophet + Random Forest
│   ├── sector_analysis.py  # Sector analysis
│   └── strategies.py       # Strategy engine
├── db/
│   └── database.py         # SQLite + SQLAlchemy
├── scheduler/
│   └── jobs.py             # Daily APScheduler jobs
├── config/
│   ├── settings.py         # All configuration
│   └── stocks.yaml         # 500 stock universe
├── data/                   # SQLite database (auto-created)
├── logs/                   # Log files (auto-created)
├── initialize.py           # One-time setup
├── requirements.txt
└── run.bat                 # Windows launcher
```

---

## ⚠️ Anti-Bot Measures for yfinance
- Batch downloads (20 stocks/batch)
- Random delays: 2.5–6s between batches + occasional 5-15s long pauses
- Exponential backoff retry (5 retries, 2x backoff)
- User-agent rotation (4 different browsers)
- SQLite caching — data already in DB is never re-downloaded
- Incremental updates — only downloads data newer than last stored date

---

## 🗄️ Database
- **SQLite** at `data/stock_analyzer.db`
- ~50,000+ price records per year for 500 stocks
- Auto-backup: copy `data/stock_analyzer.db` to preserve your data

---

## ⚠️ Disclaimer
This application is for **educational and informational purposes only**. All signals and forecasts are NOT financial advice. Past performance does not guarantee future results. Always consult a SEBI-registered investment advisor before making investment decisions.

---

## 🔄 Daily Update (Manual)
To manually trigger a data update:
```bash
python -c "from scheduler.jobs import run_daily_update; run_daily_update()"
```

Or the scheduler runs automatically at 6:30 PM IST when the app is running.
