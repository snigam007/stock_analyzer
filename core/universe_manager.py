"""
Universe Health & Auto-Healing Manager
- Checks data presence and identifies missing/stale stocks
- Tests alternative ticker symbols (.NS, .BO, renamed ticker aliases)
- Downloads missing historical data and heals tickers
- Flags delisted / defunct stocks gracefully
"""
import logging
import time
from typing import Dict, List, Tuple
import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session
from sqlalchemy import text

from db.database import Stock, DailyPrice, DownloadLog
from core.data_fetcher import save_prices_to_db
from core.indicators import compute_and_save_indicators
from core.scoring import compute_and_save_scores

logger = logging.getLogger(__name__)

# Known historical NSE/BSE ticker renames and corporate rebranding aliases
KNOWN_ALIASES = {
    "LTI": "LTIM.NS",
    "MOTHERSUMI": "MOTHERSON.NS",
    "CADILAHC": "ZYDUSLIFE.NS",
    "SRTRANSFIN": "SHRIRAMFIN.NS",
    "MINDTREE": "LTIM.NS",
    "IBULHSGFIN": "SAMMAANCAP.NS",
    "L&TFH": "LTF.NS",
    "HDFCBANK": "HDFCBANK.NS",
    "TATAMOTORS": "TATAMOTORS.NS",
    "M&M": "M&M.NS",
    "M&MFIN": "M&MFIN.NS",
    "BAJAJ-AUTO": "BAJAJ-AUTO.NS",
    "BAJAJFINSV": "BAJAJFINSV.NS",
    "BAJFINANCE": "BAJFINANCE.NS",
    "NAM-INDIA": "NAM-INDIA.NS",
}


def get_universe_health_summary(session: Session) -> Dict:
    """
    Categorize all stocks into Downloaded/Active vs Missing/Needs Healing.
    """
    stocks = session.query(Stock).all()
    downloaded = []
    missing = []

    # Get row counts per symbol
    counts = dict(session.execute(text("""
        SELECT symbol, COUNT(*) as cnt
        FROM daily_prices
        GROUP BY symbol
    """)).fetchall())

    for s in stocks:
        cnt = counts.get(s.symbol, 0)
        if cnt >= 50 and s.is_active:
            downloaded.append({
                "symbol": s.symbol,
                "name": s.name,
                "sector": s.sector,
                "yf_symbol": s.yf_symbol,
                "rows": cnt,
                "status": "HEALTHY",
            })
        else:
            missing.append({
                "symbol": s.symbol,
                "name": s.name,
                "sector": s.sector,
                "yf_symbol": s.yf_symbol,
                "rows": cnt,
                "is_active": s.is_active,
                "status": "DELISTED" if not s.is_active else ("NO_DATA" if cnt == 0 else "PARTIAL"),
            })

    return {
        "total_stocks": len(stocks),
        "healthy_count": len(downloaded),
        "missing_count": len(missing),
        "downloaded": downloaded,
        "missing": missing,
    }


def auto_heal_missing_stocks(session: Session, progress_callback=None) -> Dict:
    """
    Attempt to auto-heal and download data for missing stocks using ticker aliases and fallback exchanges.
    """
    health = get_universe_health_summary(session)
    missing = [m for m in health["missing"] if m["is_active"]]

    logger.info(f"Starting auto-healing for {len(missing)} missing/incomplete stocks...")

    healed_count = 0
    delisted_count = 0
    results = []

    for i, m in enumerate(missing):
        sym = m["symbol"]
        stock_obj = session.query(Stock).filter(Stock.symbol == sym).first()

        # Candidates to try in order
        candidates = []
        if sym in KNOWN_ALIASES:
            candidates.append(KNOWN_ALIASES[sym])
        candidates.append(f"{sym}.NS")
        candidates.append(f"{sym}.BO")
        candidates.append(sym)

        # Remove duplicates while preserving order
        unique_candidates = list(dict.fromkeys(candidates))

        df_healed = pd.DataFrame()
        success_ticker = None

        for ticker in unique_candidates:
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="10y", auto_adjust=True)
                if not hist.empty and len(hist) >= 50:
                    df_healed = hist
                    success_ticker = ticker
                    break
            except Exception:
                continue

        if not df_healed.empty and success_ticker:
            # Process & Save
            df_clean = df_healed.reset_index()
            date_col = "Date" if "Date" in df_clean.columns else df_clean.columns[0]
            df_clean["date"] = pd.to_datetime(df_clean[date_col]).dt.strftime("%Y-%m-%d")
            df_clean = df_clean.rename(columns={
                "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"
            })
            df_clean = df_clean[["date", "open", "high", "low", "close", "volume"]].dropna()

            # Save to daily_prices
            data_dict = {sym: df_clean}
            save_prices_to_db(data_dict, "daily_prices", session)

            # Update Stock metadata
            if stock_obj:
                stock_obj.yf_symbol = success_ticker
                stock_obj.is_active = True

            # Compute technical indicators
            df_clean_indexed = df_clean.set_index("date")
            compute_and_save_indicators(sym, df_clean_indexed, stock_obj.id if stock_obj else 1, session)

            healed_count += 1
            results.append({"symbol": sym, "status": "HEALED", "ticker_used": success_ticker, "rows": len(df_clean)})
            logger.info(f"✅ Healed {sym} using {success_ticker} ({len(df_clean)} rows)")
        else:
            # Confirm delisted / defunct
            if stock_obj:
                stock_obj.is_active = False
            delisted_count += 1
            results.append({"symbol": sym, "status": "DELISTED_FLAGGED", "ticker_used": "None", "rows": 0})
            logger.warning(f"❌ Could not resolve data for {sym} — flagged as inactive/delisted")

        session.commit()

        if progress_callback:
            progress_callback(i + 1, len(missing), sym)

    return {
        "attempted": len(missing),
        "healed_count": healed_count,
        "delisted_flagged": delisted_count,
        "details": results,
    }
