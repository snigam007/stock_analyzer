"""
fix_ticker_universe.py — Database sanitization and ticker realignment
- Migrates IBREALEST to EMBDL (Embassy Developments Limited)
- Deactivates obsolete duplicate tickers (VARDHMAN.BO, BHARAT.BO, APL.BO, VRL.BO, INDO)
- Ensures ICIL (Indo Count) and MGL (Mahanagar Gas) are active
- Cleans up any fake flat bars inserted for delisted tickers
- Downloads historical price data for newly aligned tickers
"""
import sys
import logging
from pathlib import Path
from datetime import date, datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("fix_ticker_universe")

from db.database import get_global_engine, get_session, Stock, DailyPrice
from sqlalchemy import text
from core.data_fetcher import download_stocks_batch, save_prices_to_db, get_eod_end_date


def run_sanitization():
    engine = get_global_engine()
    session = get_session(engine)
    
    logger.info("🔧 Sanitizing stock universe in SQLite database...")

    # 1. Clean up fake flat bars for VARDHMAN on 2026-09-10
    session.execute(text("DELETE FROM daily_prices WHERE symbol IN ('VARDHMAN') AND date >= '2026-09-10'"))
    session.commit()

    # 2. Deactivate obsolete duplicate / invalid tickers
    obsolete_symbols = ['VARDHMAN', 'BHARAT', 'APL', 'VRL', 'INDO']
    for sym in obsolete_symbols:
        session.execute(text("UPDATE stocks SET is_active = 0 WHERE symbol = :s"), {"s": sym})
    session.commit()
    logger.info(f"✅ Deactivated obsolete symbols: {obsolete_symbols}")

    # 3. Handle IBREALEST -> EMBDL migration
    session.execute(text("DELETE FROM stocks WHERE symbol = 'EQUINOX'"))
    session.commit()

    embdl_stock = session.query(Stock).filter(Stock.symbol == "EMBDL").first()
    ibrealest_stock = session.query(Stock).filter(Stock.symbol == "IBREALEST").first()

    if ibrealest_stock and not embdl_stock:
        ib_id = ibrealest_stock.id
        session.execute(text("""
            UPDATE stocks 
            SET symbol = 'EMBDL', yf_symbol = 'EMBDL.NS', 
                name = 'Embassy Developments (formerly Indiabulls Real Estate)',
                is_active = 1
            WHERE id = :id
        """), {"id": ib_id})
        
        tables_with_symbol = [
            "daily_prices", "technical_indicators", "composite_scores",
            "signals", "ml_forecasts", "bulk_block_deals"
        ]
        for tbl in tables_with_symbol:
            try:
                session.execute(text(f"UPDATE {tbl} SET symbol = 'EMBDL' WHERE symbol = 'IBREALEST'"))
            except Exception as e:
                logger.debug(f"Update table {tbl} note: {e}")
        session.commit()
        logger.info(f"✅ Migrated IBREALEST (id={ib_id}) to EMBDL (EMBDL.NS)")
    elif embdl_stock:
        embdl_stock.is_active = True
        embdl_stock.yf_symbol = "EMBDL.NS"
        if ibrealest_stock:
            session.execute(text("UPDATE daily_prices SET stock_id = :nid, symbol = 'EMBDL' WHERE symbol = 'IBREALEST'"), {"nid": embdl_stock.id})
            session.execute(text("UPDATE stocks SET is_active = 0 WHERE symbol = 'IBREALEST'"))
        session.commit()
        logger.info("✅ Activated EMBDL and repointed records")

    # 4. Ensure ICIL is present and active
    icil_stock = session.query(Stock).filter(Stock.symbol == "ICIL").first()
    if not icil_stock:
        icil_stock = Stock(
            symbol="ICIL",
            yf_symbol="ICIL.NS",
            name="Indo Count Industries",
            sector="Textiles & Apparel",
            exchange="NSE",
            market_cap_tier="small",
            instrument_type="stock",
            is_active=True,
        )
        session.add(icil_stock)
        session.commit()
        logger.info("✅ Added ICIL (Indo Count Industries) to stocks table")
    else:
        icil_stock.is_active = True
        icil_stock.yf_symbol = "ICIL.NS"
        session.commit()

    # 5. Ensure MGL is active
    mgl_stock = session.query(Stock).filter(Stock.symbol == "MGL").first()
    if not mgl_stock:
        mgl_stock = Stock(
            symbol="MGL",
            yf_symbol="MGL.NS",
            name="Mahanagar Gas Ltd",
            sector="Energy & Power",
            exchange="NSE",
            market_cap_tier="mid",
            instrument_type="stock",
            is_active=True,
        )
        session.add(mgl_stock)
        session.commit()
        logger.info("✅ Added MGL (Mahanagar Gas Ltd) to stocks table")
    else:
        mgl_stock.is_active = True
        mgl_stock.yf_symbol = "MGL.NS"
        session.commit()

    # 6. Download fresh data for EMBDL.NS, ICIL.NS, and VTL.NS
    end_date = get_eod_end_date()
    start_date = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    tickers_to_fetch = [
        ("EMBDL.NS", "EMBDL"),
        ("ICIL.NS", "ICIL"),
        ("VTL.NS", "VTL"),
    ]
    logger.info(f"📥 Downloading latest prices for {[t[1] for t in tickers_to_fetch]} from {start_date} to {end_date}...")
    yf_syms = [t[0] for t in tickers_to_fetch]
    orig_syms = [t[1] for t in tickers_to_fetch]
    data = download_stocks_batch(yf_syms, orig_syms, start_date, end_date)
    if data:
        saved = save_prices_to_db(data, "daily_prices", session)
        logger.info(f"✅ Saved {saved} price records for {[t[1] for t in tickers_to_fetch]}")

    session.close()
    logger.info("🎉 Database ticker sanitization complete!")


if __name__ == "__main__":
    run_sanitization()
