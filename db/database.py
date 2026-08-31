"""
SQLAlchemy Database Models — Stock Analyzer
All tables for storing prices, indicators, signals, scores, ML forecasts,
sector analysis, strategies, and records.
"""
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    create_engine, Column, Integer, Float, String, DateTime, Date,
    Boolean, Text, ForeignKey, Index, UniqueConstraint, JSON
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship
from sqlalchemy.pool import StaticPool

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import DB_PATH, DB_URL


# ─── Ensure data directory exists ────────────────────────────────────────────
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


class Base(DeclarativeBase):
    pass


# ─── Stock Universe ───────────────────────────────────────────────────────────
class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), unique=True, nullable=False, index=True)
    yf_symbol = Column(String(25), nullable=False)      # symbol + .NS / .BO
    name = Column(String(100), nullable=False)
    sector = Column(String(60), nullable=False, index=True)
    exchange = Column(String(10), default="NSE")
    market_cap_tier = Column(String(10))                # large/mid/small
    instrument_type = Column(String(15), default="stock")  # stock/etf/index
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    prices = relationship("DailyPrice", back_populates="stock", cascade="all, delete-orphan")
    indicators = relationship("TechnicalIndicator", back_populates="stock", cascade="all, delete-orphan")
    signals = relationship("Signal", back_populates="stock", cascade="all, delete-orphan")
    scores = relationship("CompositeScore", back_populates="stock", cascade="all, delete-orphan")
    forecasts = relationship("Forecast", back_populates="stock", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Stock(symbol={self.symbol}, name={self.name}, sector={self.sector})>"


# ─── Price Data ───────────────────────────────────────────────────────────────
class DailyPrice(Base):
    __tablename__ = "daily_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    adj_close = Column(Float)
    volume = Column(Float)
    # Derived fields
    daily_return = Column(Float)       # % change from previous close
    log_return = Column(Float)         # log return

    stock = relationship("Stock", back_populates="prices")

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_symbol_date"),
        Index("ix_price_symbol_date", "symbol", "date"),
    )


# ─── Commodity & Index Prices (separate for clarity) ─────────────────────────
class IndexPrice(Base):
    __tablename__ = "index_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    name = Column(String(100))
    date = Column(Date, nullable=False, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    daily_return = Column(Float)

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_idx_symbol_date"),
    )


class CommodityPrice(Base):
    __tablename__ = "commodity_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    name = Column(String(100))
    date = Column(Date, nullable=False, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    daily_return = Column(Float)

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_com_symbol_date"),
    )


# ─── Technical Indicators ─────────────────────────────────────────────────────
class TechnicalIndicator(Base):
    __tablename__ = "technical_indicators"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)

    # RSI
    rsi_14 = Column(Float)

    # MACD
    macd = Column(Float)
    macd_signal = Column(Float)
    macd_hist = Column(Float)

    # Bollinger Bands
    bb_upper = Column(Float)
    bb_middle = Column(Float)
    bb_lower = Column(Float)
    bb_width = Column(Float)
    bb_pct = Column(Float)           # % position within band

    # EMAs
    ema_9 = Column(Float)
    ema_21 = Column(Float)
    ema_50 = Column(Float)
    ema_200 = Column(Float)

    # ADX
    adx = Column(Float)
    di_plus = Column(Float)
    di_minus = Column(Float)

    # Stochastic
    stoch_k = Column(Float)
    stoch_d = Column(Float)

    # CCI
    cci_20 = Column(Float)

    # OBV
    obv = Column(Float)
    obv_sma = Column(Float)

    # ATR
    atr_14 = Column(Float)

    # Volume Analysis
    volume_sma_20 = Column(Float)
    volume_ratio = Column(Float)     # current_vol / sma_20
    volume_spike = Column(Boolean, default=False)

    # Price patterns
    trend_pattern = Column(String(30))   # e.g. "↑↑↓↑↑"
    trend_direction = Column(String(10)) # "UP" / "DOWN" / "SIDEWAYS"
    trend_strength = Column(Float)       # 0-100

    stock = relationship("Stock", back_populates="indicators")

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_ind_symbol_date"),
        Index("ix_ind_symbol_date", "symbol", "date"),
    )


# ─── Signals ──────────────────────────────────────────────────────────────────
class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)

    # Primary signal
    signal = Column(String(10), nullable=False)   # BUY / SELL / WATCH
    signal_strength = Column(String(10))           # STRONG / MODERATE / WEAK
    confidence = Column(Float)                     # 0.0 - 1.0

    # Price targets
    current_price = Column(Float)
    buy_price = Column(Float)          # Recommended entry price
    target_price_1 = Column(Float)     # Conservative target
    target_price_2 = Column(Float)     # Moderate target
    target_price_3 = Column(Float)     # Aggressive target
    stop_loss = Column(Float)          # Stop-loss price

    # Returns if targets hit
    target_1_upside_pct = Column(Float)
    target_2_upside_pct = Column(Float)
    target_3_upside_pct = Column(Float)
    stop_loss_downside_pct = Column(Float)

    # Risk-reward
    risk_reward_ratio = Column(Float)

    # Individual indicator signals
    rsi_signal = Column(String(10))
    macd_signal = Column(String(10))
    bb_signal = Column(String(10))
    ema_signal = Column(String(10))
    adx_signal = Column(String(10))
    stoch_signal = Column(String(10))
    cci_signal = Column(String(10))
    obv_signal = Column(String(10))
    volume_signal = Column(String(10))
    ml_signal = Column(String(10))

    # Reasoning
    reasons = Column(Text)            # JSON list of reason strings
    key_reason = Column(String(255))  # Primary reason (one liner)

    # Investment classification
    risk_level = Column(String(10))   # SAFE / MODERATE / RISKY
    investment_type = Column(String(20))  # Value/Growth/Momentum/Defensive

    generated_at = Column(DateTime, default=datetime.utcnow)

    stock = relationship("Stock", back_populates="signals")

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_sig_symbol_date"),
        Index("ix_sig_symbol_date", "symbol", "date"),
    )


# ─── Composite Scores ─────────────────────────────────────────────────────────
class CompositeScore(Base):
    __tablename__ = "composite_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)

    # Component scores (0–100 each)
    score_rsi = Column(Float)
    score_macd = Column(Float)
    score_bb = Column(Float)
    score_ema = Column(Float)
    score_volume = Column(Float)
    score_adx = Column(Float)
    score_stoch = Column(Float)
    score_cci = Column(Float)
    score_obv = Column(Float)
    score_ml = Column(Float)

    # Final composite score (0–100)
    composite_score = Column(Float, nullable=False)

    # Percentile within sector
    sector_percentile = Column(Float)
    # Percentile within full universe
    universe_percentile = Column(Float)

    # Risk metrics
    beta = Column(Float)
    volatility_annual = Column(Float)
    sharpe_ratio = Column(Float)
    max_drawdown = Column(Float)

    stock = relationship("Stock", back_populates="scores")

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_score_symbol_date"),
        Index("ix_score_symbol_date", "symbol", "date"),
    )


# ─── ML Forecasts ─────────────────────────────────────────────────────────────
class Forecast(Base):
    __tablename__ = "forecasts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    generated_date = Column(Date, nullable=False, index=True)

    # Horizon forecasts
    forecast_7d_price = Column(Float)
    forecast_7d_change_pct = Column(Float)
    forecast_7d_upper = Column(Float)
    forecast_7d_lower = Column(Float)

    forecast_14d_price = Column(Float)
    forecast_14d_change_pct = Column(Float)
    forecast_14d_upper = Column(Float)
    forecast_14d_lower = Column(Float)

    forecast_1m_price = Column(Float)
    forecast_1m_change_pct = Column(Float)
    forecast_1m_upper = Column(Float)
    forecast_1m_lower = Column(Float)

    forecast_3m_price = Column(Float)
    forecast_3m_change_pct = Column(Float)
    forecast_3m_upper = Column(Float)
    forecast_3m_lower = Column(Float)

    forecast_6m_price = Column(Float)
    forecast_6m_change_pct = Column(Float)
    forecast_6m_upper = Column(Float)
    forecast_6m_lower = Column(Float)

    forecast_1y_price = Column(Float)
    forecast_1y_change_pct = Column(Float)
    forecast_1y_upper = Column(Float)
    forecast_1y_lower = Column(Float)

    # Model metadata
    model_used = Column(String(30))    # prophet / rf / linear
    model_rmse = Column(Float)
    model_r2 = Column(Float)
    data_points_used = Column(Integer)

    stock = relationship("Stock", back_populates="forecasts")

    __table_args__ = (
        UniqueConstraint("symbol", "generated_date", name="uq_fc_symbol_date"),
    )


# ─── Sector Analysis ──────────────────────────────────────────────────────────
class SectorAnalysis(Base):
    __tablename__ = "sector_analysis"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sector = Column(String(60), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)

    # Performance
    daily_return_avg = Column(Float)
    daily_return_median = Column(Float)
    weekly_return = Column(Float)
    monthly_return = Column(Float)
    quarterly_return = Column(Float)
    ytd_return = Column(Float)

    # Breadth
    total_stocks = Column(Integer)
    stocks_up = Column(Integer)
    stocks_down = Column(Integer)
    stocks_unchanged = Column(Integer)
    advance_decline_ratio = Column(Float)

    # Strength
    avg_composite_score = Column(Float)
    median_composite_score = Column(Float)
    buy_signals_count = Column(Integer)
    sell_signals_count = Column(Integer)
    watch_signals_count = Column(Integer)
    sector_signal = Column(String(10))   # BUY / SELL / WATCH

    # Volatility
    sector_volatility = Column(Float)
    sector_beta = Column(Float)

    __table_args__ = (
        UniqueConstraint("sector", "date", name="uq_sec_sector_date"),
    )


class SectorCorrelation(Base):
    __tablename__ = "sector_correlations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    sector_a = Column(String(60), nullable=False)
    sector_b = Column(String(60), nullable=False)
    correlation_30d = Column(Float)
    correlation_90d = Column(Float)
    correlation_1y = Column(Float)
    lag_days = Column(Integer, default=0)
    impact_direction = Column(Float)      # +1 / -1 / 0

    __table_args__ = (
        UniqueConstraint("date", "sector_a", "sector_b", name="uq_corr_date_sectors"),
    )


# ─── Daily Top Stocks ─────────────────────────────────────────────────────────
class DailyTopStock(Base):
    __tablename__ = "daily_top_stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    rank = Column(Integer, nullable=False)
    symbol = Column(String(20), nullable=False)
    name = Column(String(100))
    sector = Column(String(60))

    composite_score = Column(Float)
    signal = Column(String(10))
    current_price = Column(Float)
    buy_price = Column(Float)
    target_1 = Column(Float)
    target_2 = Column(Float)
    stop_loss = Column(Float)
    risk_reward = Column(Float)
    risk_level = Column(String(10))

    # Trend pattern: last 10 days
    trend_pattern = Column(String(40))   # "↑↑↓↑↑↓↑↑↑↑"
    trend_direction = Column(String(10))

    # Returns
    daily_return = Column(Float)
    weekly_return = Column(Float)
    monthly_return = Column(Float)

    key_reason = Column(String(255))

    list_type = Column(String(20), default="top_buy")  # top_buy/top_sell/safe/risky

    __table_args__ = (
        UniqueConstraint("date", "rank", "list_type", name="uq_top_date_rank_type"),
    )


# ─── Investment Strategies ────────────────────────────────────────────────────
class Strategy(Base):
    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    target_type = Column(String(15), nullable=False)   # stock / sector / portfolio
    target_name = Column(String(60), nullable=False)   # symbol or sector name

    strategy_name = Column(String(60), nullable=False)
    strategy_type = Column(String(30))                 # Momentum/Value/Defensive/Growth
    risk_level = Column(String(10))                    # SAFE / MODERATE / RISKY
    time_horizon = Column(String(10))                  # SHORT/MEDIUM/LONG

    description = Column(Text)
    action = Column(String(10))                        # BUY/SELL/HOLD/ACCUMULATE/AVOID
    entry_price = Column(Float)
    target_price = Column(Float)
    stop_loss = Column(Float)
    expected_return_pct = Column(Float)

    rationale = Column(Text)
    risks = Column(Text)

    __table_args__ = (
        UniqueConstraint("date", "target_type", "target_name", name="uq_strat_date_target"),
    )


# ─── Data Download Tracking ───────────────────────────────────────────────────
class DownloadLog(Base):
    __tablename__ = "download_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    download_type = Column(String(20))   # historical / daily_update
    start_date = Column(Date)
    end_date = Column(Date)
    rows_downloaded = Column(Integer, default=0)
    status = Column(String(15))          # success / failed / partial
    error_message = Column(Text)
    downloaded_at = Column(DateTime, default=datetime.utcnow)


# ─── Candlestick Pattern Recognition ──────────────────────────────────────────
class CandlestickPatternRecord(Base):
    __tablename__ = "candlestick_patterns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    pattern_name = Column(String(50), nullable=False)   # e.g., "Bullish Engulfing", "Hammer", "Morning Star"
    sentiment = Column(String(10), nullable=False)      # BULLISH / BEARISH / INDECISION
    reliability = Column(Integer, default=3)           # 1 (low) to 5 (high)
    candle_count = Column(Integer, default=1)          # 1, 2, or 3-bar formation
    description = Column(Text)
    close_price = Column(Float)
    detected_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("symbol", "date", "pattern_name", name="uq_pattern_sym_date"),
        Index("ix_pattern_symbol_date", "symbol", "date"),
    )


# ─── Watchlist & Items ────────────────────────────────────────────────────────
class Watchlist(Base):
    __tablename__ = "watchlists"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(60), nullable=False, unique=True)
    description = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship("WatchlistItem", back_populates="watchlist", cascade="all, delete-orphan")


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    watchlist_id = Column(Integer, ForeignKey("watchlists.id"), nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    target_buy_price = Column(Float)
    target_sell_price = Column(Float)
    stop_loss = Column(Float)
    notes = Column(Text)
    added_at = Column(DateTime, default=datetime.utcnow)

    watchlist = relationship("Watchlist", back_populates="items")

    __table_args__ = (
        UniqueConstraint("watchlist_id", "symbol", name="uq_watchlist_symbol"),
    )


# ─── Price & Breakout Alerts ──────────────────────────────────────────────────
class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    alert_type = Column(String(30), nullable=False)    # 52W_HIGH_BREAKOUT / 52W_LOW_BREAKDOWN / TARGET_HIT / STOP_LOSS / PATTERN
    condition_value = Column(Float)
    current_value = Column(Float)
    message = Column(Text, nullable=False)
    is_triggered = Column(Boolean, default=False)
    triggered_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


# ─── Institutional Bulk & Block Deals ─────────────────────────────────────────
class BulkBlockDeal(Base):
    __tablename__ = "bulk_block_deals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    security_name = Column(String(100))
    client_name = Column(String(150), nullable=False, index=True)
    deal_type = Column(String(10), default="BULK")     # BULK / BLOCK
    buy_sell = Column(String(5), nullable=False)       # BUY / SELL
    quantity = Column(Integer, nullable=False)
    trade_price = Column(Float, nullable=False)
    value_in_crores = Column(Float)
    is_promoter_or_fii = Column(Boolean, default=False)

    __table_args__ = (
        Index("ix_deal_date_symbol", "date", "symbol"),
    )


# ─── Economic Calendar & Macro Events ─────────────────────────────────────────
class EconomicEvent(Base):
    __tablename__ = "economic_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_date = Column(Date, nullable=False, index=True)
    event_name = Column(String(100), nullable=False)
    category = Column(String(40), nullable=False)      # MONETARY_POLICY / INFLATION / GDP / FO_EXPIRY / EARNINGS / MACRO
    impact_level = Column(String(10), default="MEDIUM") # HIGH / MEDIUM / LOW
    affected_sector = Column(String(60))               # Sector or "ALL"
    symbol = Column(String(20))                        # For stock-specific events like earnings
    forecast_value = Column(String(30))
    previous_value = Column(String(30))
    actual_value = Column(String(30))
    description = Column(Text)


# ─── Engine & Session Setup ───────────────────────────────────────────────────
def get_engine(db_url: str = DB_URL):
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=StaticPool,
    )
    # Enable WAL mode for better concurrent read performance
    with engine.connect() as conn:
        conn.execute(__import__("sqlalchemy").text("PRAGMA journal_mode=WAL"))
        conn.execute(__import__("sqlalchemy").text("PRAGMA synchronous=NORMAL"))
        conn.execute(__import__("sqlalchemy").text("PRAGMA cache_size=10000"))
        conn.execute(__import__("sqlalchemy").text("PRAGMA temp_store=MEMORY"))
        conn.commit()
    return engine


def create_all_tables(engine=None):
    """Create all database tables."""
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(engine)
    return engine


def get_session(engine=None) -> Session:
    """Get a database session."""
    if engine is None:
        engine = get_engine()
    return Session(engine)


# ─── Singleton engine ─────────────────────────────────────────────────────────
_engine = None

def get_global_engine():
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


if __name__ == "__main__":
    engine = create_all_tables()
    print(f"✅ Database created at {DB_PATH}")
    print(f"   Tables: {list(Base.metadata.tables.keys())}")
