"""
Data Refresh Status & Asset Universe Health Module
Provides centralized queries for data freshness, daily ingestion counts,
universe totals (stocks, indexes, commodities), and searchable directory metadata.
"""
from datetime import datetime, date
from typing import Dict, Any, List, Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.database import get_global_engine, get_session

COMMODITY_NAMES = {
    "GC=F": "Gold (COMEX / MCX Future)",
    "SI=F": "Silver (COMEX / MCX Future)",
    "CL=F": "Crude Oil (WTI / MCX)",
    "BZ=F": "Brent Crude Oil",
    "HG=F": "Copper (COMEX / MCX)",
    "NG=F": "Natural Gas",
    "PL=F": "Platinum",
    "PA=F": "Palladium",
    "GOLDBEES.NS": "Nippon India Gold ETF (GOLDBEES)",
    "SILVERBEES.NS": "Nippon India Silver ETF (SILVERBEES)",
}

INDEX_NAMES = {
    "^NSEI": "NIFTY 50 (National Stock Exchange)",
    "^BSESN": "BSE SENSEX (Bombay Stock Exchange)",
    "^NSEBANK": "NIFTY BANK (Banking Index)",
    "^CNXIT": "NIFTY IT (Technology Index)",
    "NIFTYBEES.NS": "Nippon India Nifty 50 ETF (NIFTYBEES)",
    "BANKBEES.NS": "Nippon India Nifty Bank ETF (BANKBEES)",
    "ITBEES.NS": "Nippon India Nifty IT ETF (ITBEES)",
    "^GSPC": "S&P 500 (US Benchmark)",
    "^NDX": "Nasdaq 100 (US Tech Benchmark)",
}


def get_database_status_summary(session: Optional[Session] = None) -> Dict[str, Any]:
    """
    Get high-level summary metrics of database freshness and asset universe counts.
    """
    close_session = False
    if session is None:
        engine = get_global_engine()
        session = get_session(engine)
        close_session = True

    try:
        # Max date across all price tables
        max_date_row = session.execute(text("""
            SELECT MAX(m) FROM (
                SELECT MAX(date) as m FROM daily_prices
                UNION ALL
                SELECT MAX(date) FROM index_prices
                UNION ALL
                SELECT MAX(date) FROM commodity_prices
            )
        """)).scalar()
        max_date = str(max_date_row) if max_date_row else str(date.today())

        # Asset Counts
        stock_cnt = session.execute(text("SELECT COUNT(*) FROM stocks WHERE is_active=1")).scalar() or 0
        index_cnt = session.execute(text("SELECT COUNT(DISTINCT symbol) FROM index_prices")).scalar() or 0
        comm_cnt = session.execute(text("SELECT COUNT(DISTINCT symbol) FROM commodity_prices")).scalar() or 0
        total_assets = stock_cnt + index_cnt + comm_cnt

        # Total Price Bars
        total_bars = session.execute(text("""
            SELECT (SELECT COUNT(*) FROM daily_prices) + 
                   (SELECT COUNT(*) FROM index_prices) + 
                   (SELECT COUNT(*) FROM commodity_prices)
        """)).scalar() or 0

        # Latest session stock coverage
        latest_stocks = session.execute(text(
            "SELECT COUNT(DISTINCT symbol) FROM daily_prices WHERE date=:d"
        ), {"d": max_date}).scalar() or 0

        # Indicator & Signal counts
        signals_cnt = session.execute(text(
            "SELECT COUNT(*) FROM signals WHERE date=(SELECT MAX(date) FROM signals)"
        )).scalar() or 0

        # Format status
        status_badge = "🟢 Live Feed Synced" if latest_stocks > 0 else "🟡 Sync Pending"

        return {
            "max_date": max_date,
            "stock_count": stock_cnt,
            "index_count": index_cnt,
            "commodity_count": comm_cnt,
            "total_assets": total_assets,
            "total_bars": total_bars,
            "latest_session_stock_count": latest_stocks,
            "latest_signals_count": signals_cnt,
            "status_badge": status_badge,
            "next_refresh_ist": "08:00 AM IST (Daily Scheduled)",
        }
    finally:
        if close_session:
            session.close()


def get_daily_stock_counts_history(days: int = 180, session: Optional[Session] = None) -> pd.DataFrame:
    """
    Get historical count of stocks, indexes, and commodities per trading day.
    """
    close_session = False
    if session is None:
        engine = get_global_engine()
        session = get_session(engine)
        close_session = True

    try:
        df_stocks = pd.read_sql(f"""
            SELECT date, 
                   COUNT(DISTINCT symbol) as stock_count,
                   AVG(close) as avg_stock_close,
                   SUM(volume) as total_stock_volume
            FROM daily_prices
            GROUP BY date
            ORDER BY date DESC
            LIMIT {days}
        """, session.connection())

        df_idx = pd.read_sql(f"""
            SELECT date, COUNT(DISTINCT symbol) as index_count
            FROM index_prices
            GROUP BY date
            ORDER BY date DESC
            LIMIT {days}
        """, session.connection())

        df_comm = pd.read_sql(f"""
            SELECT date, COUNT(DISTINCT symbol) as commodity_count
            FROM commodity_prices
            GROUP BY date
            ORDER BY date DESC
            LIMIT {days}
        """, session.connection())

        # Merge on date
        merged = df_stocks.merge(df_idx, on="date", how="left").merge(df_comm, on="date", how="left")
        merged["index_count"] = merged["index_count"].fillna(0).astype(int)
        merged["commodity_count"] = merged["commodity_count"].fillna(0).astype(int)
        merged["total_assets_updated"] = merged["stock_count"] + merged["index_count"] + merged["commodity_count"]
        merged = merged.sort_values("date", ascending=True).reset_index(drop=True)
        return merged
    finally:
        if close_session:
            session.close()


def get_searchable_universe_directory(session: Optional[Session] = None) -> pd.DataFrame:
    """
    Get unified directory of all stocks, indexes, and commodities with latest price,
    return %, signal, and score.
    """
    close_session = False
    if session is None:
        engine = get_global_engine()
        session = get_session(engine)
        close_session = True

    try:
        # 1. Stocks
        stocks_query = """
            SELECT 
                s.symbol,
                s.yf_symbol,
                s.name,
                'Stock' as asset_type,
                s.sector,
                s.market_cap_tier as tier,
                COUNT(p.date) as price_records,
                MIN(p.date) as min_date,
                MAX(p.date) as max_date,
                p_latest.close as latest_close,
                p_latest.daily_return as daily_return_pct,
                sig.signal,
                sig.risk_level,
                cs.composite_score
            FROM stocks s
            LEFT JOIN daily_prices p ON s.symbol = p.symbol
            LEFT JOIN (
                SELECT symbol, close, daily_return
                FROM daily_prices
                WHERE (symbol, date) IN (
                    SELECT symbol, MAX(date) FROM daily_prices GROUP BY symbol
                )
            ) p_latest ON s.symbol = p_latest.symbol
            LEFT JOIN (
                SELECT symbol, signal, risk_level
                FROM signals
                WHERE (symbol, date) IN (
                    SELECT symbol, MAX(date) FROM signals GROUP BY symbol
                )
            ) sig ON s.symbol = sig.symbol
            LEFT JOIN (
                SELECT symbol, composite_score
                FROM composite_scores
                WHERE (symbol, date) IN (
                    SELECT symbol, MAX(date) FROM composite_scores GROUP BY symbol
                )
            ) cs ON s.symbol = cs.symbol
            WHERE s.is_active = 1
            GROUP BY s.symbol, s.yf_symbol, s.name, s.sector, s.market_cap_tier, p_latest.close, p_latest.daily_return, sig.signal, sig.risk_level, cs.composite_score
        """
        df_stocks = pd.read_sql(stocks_query, session.connection())

        # 2. Indexes
        indexes_query = """
            SELECT 
                ip.symbol,
                ip.symbol as yf_symbol,
                ip.name,
                'Index' as asset_type,
                'Benchmark Index' as sector,
                'Benchmark' as tier,
                COUNT(ip.date) as price_records,
                MIN(ip.date) as min_date,
                MAX(ip.date) as max_date,
                ip_latest.close as latest_close,
                ip_latest.daily_return as daily_return_pct,
                'WATCH' as signal,
                'SAFE' as risk_level,
                55.0 as composite_score
            FROM index_prices ip
            LEFT JOIN (
                SELECT symbol, close, daily_return
                FROM index_prices
                WHERE (symbol, date) IN (
                    SELECT symbol, MAX(date) FROM index_prices GROUP BY symbol
                )
            ) ip_latest ON ip.symbol = ip_latest.symbol
            WHERE ip.close IS NOT NULL
            GROUP BY ip.symbol, ip.name, ip_latest.close, ip_latest.daily_return
        """
        df_indexes = pd.read_sql(indexes_query, session.connection())
        # Clean index names
        df_indexes["name"] = df_indexes["symbol"].map(lambda sym: INDEX_NAMES.get(sym) or sym)

        # 3. Commodities
        commodities_query = """
            SELECT 
                cp.symbol,
                cp.symbol as yf_symbol,
                cp.name,
                'Commodity' as asset_type,
                'Global Commodity' as sector,
                'Commodity Asset' as tier,
                COUNT(cp.date) as price_records,
                MIN(cp.date) as min_date,
                MAX(cp.date) as max_date,
                cp_latest.close as latest_close,
                cp_latest.daily_return as daily_return_pct,
                'WATCH' as signal,
                'MODERATE' as risk_level,
                50.0 as composite_score
            FROM commodity_prices cp
            LEFT JOIN (
                SELECT symbol, close, daily_return
                FROM commodity_prices
                WHERE (symbol, date) IN (
                    SELECT symbol, MAX(date) FROM commodity_prices GROUP BY symbol
                )
            ) cp_latest ON cp.symbol = cp_latest.symbol
            WHERE cp.close IS NOT NULL
            GROUP BY cp.symbol, cp.name, cp_latest.close, cp_latest.daily_return
        """
        df_commodities = pd.read_sql(commodities_query, session.connection())
        # Clean commodity names
        df_commodities["name"] = df_commodities["symbol"].map(lambda sym: COMMODITY_NAMES.get(sym) or sym)

        # Combine
        combined = pd.concat([df_stocks, df_indexes, df_commodities], ignore_index=True)
        combined["symbol"] = combined["symbol"].fillna("").astype(str)
        combined["name"] = combined["name"].fillna("").astype(str)
        combined["asset_type"] = combined["asset_type"].fillna("Stock").astype(str)
        combined["sector"] = combined["sector"].fillna("General").astype(str)
        combined["tier"] = combined["tier"].fillna("Standard").astype(str)
        combined["signal"] = combined["signal"].fillna("WATCH").astype(str)
        combined["risk_level"] = combined["risk_level"].fillna("MODERATE").astype(str)
        combined["composite_score"] = pd.to_numeric(combined["composite_score"], errors="coerce").fillna(50.0).round(1)
        combined["latest_close"] = pd.to_numeric(combined["latest_close"], errors="coerce").fillna(0.0).round(2)
        combined["daily_return_pct"] = (pd.to_numeric(combined["daily_return_pct"], errors="coerce").fillna(0.0) * 100.0).round(2)
        combined["min_date"] = combined["min_date"].fillna("—").astype(str)
        combined["max_date"] = combined["max_date"].fillna("—").astype(str)
        combined["price_records"] = pd.to_numeric(combined["price_records"], errors="coerce").fillna(0).astype(int)

        return combined
    finally:
        if close_session:
            session.close()
