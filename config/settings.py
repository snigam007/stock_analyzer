"""
Application Configuration Settings
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── Database ────────────────────────────────────────────────────────────────
DB_PATH = BASE_DIR / "data" / "stock_analyzer.db"
DB_URL = f"sqlite:///{DB_PATH}"

# ─── Data Download Settings ───────────────────────────────────────────────────
DOWNLOAD_START_DATE = "2000-01-01"   # Full history from 2000
BATCH_SIZE = 20                       # Stocks per yfinance batch call
MIN_DELAY_SECONDS = 2.5               # Min random delay between batches
MAX_DELAY_SECONDS = 6.0               # Max random delay between batches
MAX_RETRIES = 5                       # Retry on failure
BACKOFF_FACTOR = 2.0                  # Exponential backoff multiplier
REQUEST_TIMEOUT = 60                  # HTTP timeout in seconds

# ─── Analysis Settings ────────────────────────────────────────────────────────
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BB_PERIOD = 20
BB_STD = 2
ATR_PERIOD = 14
ADX_PERIOD = 14
CCI_PERIOD = 20
STOCH_K = 14
STOCH_D = 3
OBV_SMOOTH = 10

EMA_PERIODS = [9, 21, 50, 200]
VOLUME_SPIKE_MULTIPLIER = 2.0        # Volume > 2x 20-day avg = spike
TREND_LOOKBACK_DAYS = 20             # Days for trend pattern display

# ─── ML Settings ─────────────────────────────────────────────────────────────
ML_PREDICTION_DAYS = [7, 14, 30, 90, 180, 365]  # Forecast horizons
ML_TRAIN_MIN_ROWS = 252              # Minimum 1 year of data for ML
PROPHET_CHANGEPOINT_PRIOR = 0.05
RF_N_ESTIMATORS = 200
RF_MAX_DEPTH = 10
RF_RANDOM_STATE = 42

# ─── Scoring & Signals ────────────────────────────────────────────────────────
# Composite score weights
WEIGHT_RSI = 0.10
WEIGHT_MACD = 0.12
WEIGHT_BB = 0.10
WEIGHT_EMA = 0.12
WEIGHT_VOLUME = 0.10
WEIGHT_ADX = 0.08
WEIGHT_STOCH = 0.08
WEIGHT_CCI = 0.08
WEIGHT_OBV = 0.10
WEIGHT_ML = 0.12

BUY_SCORE_THRESHOLD = 65             # Score >= 65 → BUY
SELL_SCORE_THRESHOLD = 35            # Score <= 35 → SELL
# Between 35–65 → WATCH

# Risk Classification Thresholds
SAFE_BETA_MAX = 0.8
SAFE_VOLATILITY_MAX = 0.20           # Annualized std dev
RISKY_BETA_MIN = 1.3
RISKY_VOLATILITY_MIN = 0.35

# ATR multipliers for targets/stop-loss
TARGET_ATR_MULTIPLIER_BUY = 3.0
STOPLOSS_ATR_MULTIPLIER = 1.5
TARGET_ATR_MULTIPLIER_SELL = 2.0

# ─── Scheduler Settings ───────────────────────────────────────────────────────
DAILY_UPDATE_HOUR = 18               # 6 PM IST
DAILY_UPDATE_MINUTE = 30
TIMEZONE = "Asia/Kolkata"

# ─── Sector Definitions ───────────────────────────────────────────────────────
SECTOR_CORRELATIONS = {
    # (sector_a, sector_b): correlation_direction, lag_days, description
    ("Energy", "Automobiles"): (-1, 0, "Crude oil up → Auto costs up → Auto down"),
    ("Banking & Finance", "Real Estate"): (1, 5, "Credit easing → Real estate up"),
    ("IT & Technology", "Telecom"): (1, 0, "IT growth drives telecom infra"),
    ("Metals & Mining", "Construction & Infrastructure"): (1, 0, "Metals supply construction"),
    ("Energy", "Chemicals"): (1, 0, "Crude feedstock → Chemical costs"),
    ("FMCG & Consumer", "Banking & Finance"): (1, 10, "Consumer spending → credit demand"),
    ("Pharmaceuticals", "FMCG & Consumer"): (0.3, 0, "Both defensive; mild positive"),
    ("Banking & Finance", "Capital Goods & Engineering"): (1, 15, "Credit → capex investment"),
    ("Automobiles", "Metals & Mining"): (1, 0, "Auto demand → metals demand"),
    ("IT & Technology", "Banking & Finance"): (0.5, 0, "Tech-enabled banking growth"),
}

# ─── App Settings ─────────────────────────────────────────────────────────────
APP_TITLE = "📊 Indian Stock Market Analyzer"
APP_VERSION = "1.0.0"
MAX_TOP_STOCKS = 15
DISCLAIMER = (
    "⚠️ DISCLAIMER: This application is for educational and informational purposes only. "
    "Signals and forecasts are NOT financial advice. Past performance does not guarantee future results. "
    "Always consult a SEBI-registered investment advisor before making investment decisions."
)

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_DIR = BASE_DIR / "logs"
LOG_LEVEL = "INFO"
