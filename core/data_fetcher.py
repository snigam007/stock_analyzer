"""
Data Fetcher — Downloads BSE/NSE stock data from Yahoo Finance (yfinance)
with robust anti-bot protection: batching, random delays, retries,
exponential backoff, and intelligent incremental updates.
"""
import time
import random
import logging
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Dict, Tuple
import sys

import pandas as pd
import numpy as np
import yfinance as yf
try:
    from tenacity import (
        retry, stop_after_attempt, wait_exponential,
        retry_if_exception_type, before_sleep_log
    )
except ImportError:
    # Graceful fallback if tenacity is not yet installed in environment
    def retry(*args, **kwargs):
        def decorator(f):
            return f
        return decorator
    def stop_after_attempt(*args, **kwargs): return None
    def wait_exponential(*args, **kwargs): return None
    def retry_if_exception_type(*args, **kwargs): return None
    def before_sleep_log(*args, **kwargs): return None
from sqlalchemy.orm import Session
from sqlalchemy import text

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    DOWNLOAD_START_DATE, BATCH_SIZE, MIN_DELAY_SECONDS, MAX_DELAY_SECONDS,
    MAX_RETRIES, BACKOFF_FACTOR, REQUEST_TIMEOUT
)
from db.database import (
    get_global_engine, get_session, Stock, DailyPrice,
    IndexPrice, CommodityPrice, DownloadLog
)

logger = logging.getLogger(__name__)


# ─── Human-like User Agents (rotate to avoid detection) ──────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


def _human_delay(min_s: float = None, max_s: float = None):
    """Sleep for a random duration to mimic human browsing."""
    min_s = min_s or MIN_DELAY_SECONDS
    max_s = max_s or MAX_DELAY_SECONDS
    # Add occasional longer pauses (1 in 10 batches)
    if random.random() < 0.1:
        extra = random.uniform(5, 15)
        logger.debug(f"Long pause: {extra:.1f}s")
        time.sleep(extra)
    else:
        delay = random.uniform(min_s, max_s)
        time.sleep(delay)


def _get_session_headers() -> Dict:
    """Return randomized headers to avoid bot detection."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def _build_yf_symbol(symbol: str, exchange: str = "NSE") -> str:
    """Convert bare symbol to yfinance format."""
    s = symbol.upper().strip()
    # Already has suffix
    if "." in s:
        return s
    # Handle special symbols
    if s.startswith("^") or s.endswith("=F") or s.endswith("=X"):
        return s
    suffix = ".NS" if exchange.upper() in ("NSE", "") else ".BO"
    return f"{s}{suffix}"


@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=BACKOFF_FACTOR, min=2, max=60),
    retry=retry_if_exception_type((Exception,)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=False,
)
def _download_batch_raw(
    symbols: List[str],
    start: str,
    end: str,
    threads: bool = False,
) -> Optional[pd.DataFrame]:
    """Download a batch of symbols with retry on failure."""
    try:
        data = yf.download(
            tickers=symbols,
            start=start,
            end=end,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=threads,
            timeout=REQUEST_TIMEOUT,
        )
        return data
    except Exception as e:
        logger.warning(f"Batch download failed ({symbols[:3]}...): {e}")
        raise


def _flatten_multiindex_df(raw_df: pd.DataFrame, symbols: List[str]) -> Dict[str, pd.DataFrame]:
    """Convert yfinance multi-index DataFrame to dict of single-symbol DataFrames."""
    result = {}

    if raw_df is None or raw_df.empty:
        return result

    # Single ticker case — no multi-index
    if not isinstance(raw_df.columns, pd.MultiIndex):
        if len(symbols) == 1:
            df = raw_df.copy()
            df.columns = [c.lower() for c in df.columns]
            df.index = pd.to_datetime(df.index).date
            result[symbols[0]] = df
        return result

    # Multi-ticker case
    for sym in symbols:
        try:
            if sym in raw_df.columns.get_level_values(1):
                df = raw_df.xs(sym, axis=1, level=1).copy()
            elif sym in raw_df.columns.get_level_values(0):
                df = raw_df[sym].copy()
            else:
                continue

            df.columns = [c.lower() for c in df.columns]
            df.index = pd.to_datetime(df.index).date
            df = df.dropna(how="all")

            if not df.empty:
                result[sym] = df
        except (KeyError, Exception) as e:
            logger.debug(f"Could not extract {sym}: {e}")

    return result


def get_last_download_date(symbol: str, session: Session) -> Optional[date]:
    """Get the last date we have data for a symbol."""
    result = session.execute(
        text("SELECT MAX(date) FROM daily_prices WHERE symbol = :s"),
        {"s": symbol}
    ).scalar()
    return result


def download_stocks_batch(
    symbols_yf: List[str],
    original_symbols: List[str],
    start_date: str,
    end_date: str,
) -> Dict[str, pd.DataFrame]:
    """
    Download a batch of stocks from yfinance with anti-bot measures.
    Returns dict: {original_symbol -> DataFrame}
    """
    raw = _download_batch_raw(symbols_yf, start_date, end_date)
    if raw is None:
        return {}

    # Map yf symbols back to original symbols
    yf_to_orig = dict(zip(symbols_yf, original_symbols))
    raw_dict = _flatten_multiindex_df(raw, symbols_yf)

    result = {}
    for yf_sym, df in raw_dict.items():
        orig = yf_to_orig.get(yf_sym, yf_sym)
        if not df.empty:
            # Calculate derived fields
            if "close" in df.columns:
                df["daily_return"] = df["close"].pct_change() * 100
                df["log_return"] = np.log(df["close"] / df["close"].shift(1))
            result[orig] = df

    return result


# ─── Indian Market Timings & EOD Boundary Protections ────────────────────────
def is_indian_market_closed() -> bool:
    """
    Check if Indian Stock Market (NSE/BSE) is closed and daily session is complete.
    Market Hours: Mon-Fri 09:15 to 15:30 IST. Post-market settlement finishes by ~15:45 IST.
    Weekends (Saturday/Sunday) are always considered closed.
    """
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return True
    return now.time() >= datetime.strptime("15:45", "%H:%M").time()


def get_eod_end_date() -> str:
    """
    Returns the yfinance exclusive end date string (YYYY-MM-DD).
    - If market is currently open/active today, end_date = today (fetches strictly < today, i.e. up to last completed day).
    - If market is closed for today (post 15:45 IST or weekend), end_date = tomorrow (fetches strictly < tomorrow, including today).
    """
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)
    if is_indian_market_closed():
        return (now.date() + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        return now.date().strftime("%Y-%m-%d")


def get_max_allowed_eod_date() -> date:
    """
    Returns the maximum allowable date for daily EOD records.
    If market is still active today, today is NOT allowed (must be <= yesterday).
    """
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)
    if is_indian_market_closed():
        return now.date()
    else:
        return now.date() - timedelta(days=1)


def cleanup_active_market_data(session: Session) -> int:
    """
    Cleans up any premature/incomplete daily rows inserted while the market was active today.
    Ensures the database only reflects official completed trading sessions.
    """
    max_allowed = get_max_allowed_eod_date()
    max_allowed_str = str(max_allowed)
    
    tables = [
        "daily_prices", "index_prices", "commodity_prices",
        "technical_indicators", "composite_scores", "signals",
        "sector_analysis", "sector_correlations", "strategy_results",
        "ml_forecasts"
    ]
    deleted_total = 0
    for t in tables:
        try:
            res = session.execute(
                text(f"DELETE FROM {t} WHERE date > :m"),
                {"m": max_allowed_str}
            )
            deleted_total += res.rowcount
        except Exception as e:
            logger.debug(f"Cleanup notice for {t}: {e}")
    session.commit()
    if deleted_total > 0:
        logger.info(f"🧹 Cleaned up {deleted_total} premature rows from active market session (date > {max_allowed_str})")
    return deleted_total


def save_prices_to_db(
    data_dict: Dict[str, pd.DataFrame],
    table: str,
    session: Session,
) -> int:
    """Save downloaded price data to database. Returns rows saved."""
    total_saved = 0
    max_allowed_str = str(get_max_allowed_eod_date())

    for symbol, df in data_dict.items():
        if df.empty:
            continue

        if table == "daily_prices":
            stock = session.query(Stock).filter(Stock.symbol == symbol).first()
            if stock is None:
                continue
            
            rows_data = []
            for dt, row in df.iterrows():
                dt_str = str(dt)[:10]
                if dt_str > max_allowed_str:
                    # Reject active/incomplete today bar
                    continue
                rows_data.append({
                    "stock_id": stock.id,
                    "symbol": symbol,
                    "date": dt_str,
                    "open": _clean_num(row.get("open")),
                    "high": _clean_num(row.get("high")),
                    "low": _clean_num(row.get("low")),
                    "close": _clean_num(row.get("close")),
                    "adj_close": _clean_num(row.get("close")),
                    "volume": _clean_num(row.get("volume")),
                    "daily_return": _clean_num(row.get("daily_return")),
                    "log_return": _clean_num(row.get("log_return")),
                })
            
            if rows_data:
                try:
                    session.execute(text("""
                        INSERT OR REPLACE INTO daily_prices 
                        (stock_id, symbol, date, open, high, low, close, adj_close, volume, daily_return, log_return)
                        VALUES (:stock_id, :symbol, :date, :open, :high, :low, :close, :adj_close, :volume, :daily_return, :log_return)
                    """), rows_data)
                    session.commit()
                    total_saved += len(rows_data)
                except Exception as e:
                    session.rollback()
                    logger.error(f"Error inserting daily_prices for {symbol}: {e}")

        elif table == "index_prices":
            rows_data = []
            for dt, row in df.iterrows():
                dt_str = str(dt)[:10]
                if dt_str > max_allowed_str:
                    continue
                rows_data.append({
                    "symbol": symbol,
                    "date": dt_str,
                    "open": _clean_num(row.get("open")),
                    "high": _clean_num(row.get("high")),
                    "low": _clean_num(row.get("low")),
                    "close": _clean_num(row.get("close")),
                    "volume": _clean_num(row.get("volume")),
                    "daily_return": _clean_num(row.get("daily_return")),
                })
            if rows_data:
                try:
                    session.execute(text("""
                        INSERT OR REPLACE INTO index_prices 
                        (symbol, date, open, high, low, close, volume, daily_return)
                        VALUES (:symbol, :date, :open, :high, :low, :close, :volume, :daily_return)
                    """), rows_data)
                    session.commit()
                    total_saved += len(rows_data)
                except Exception as e:
                    session.rollback()
                    logger.error(f"Error inserting index_prices for {symbol}: {e}")

        elif table == "commodity_prices":
            rows_data = []
            for dt, row in df.iterrows():
                dt_str = str(dt)[:10]
                if dt_str > max_allowed_str:
                    continue
                rows_data.append({
                    "symbol": symbol,
                    "date": dt_str,
                    "open": _clean_num(row.get("open")),
                    "high": _clean_num(row.get("high")),
                    "low": _clean_num(row.get("low")),
                    "close": _clean_num(row.get("close")),
                    "volume": _clean_num(row.get("volume")),
                    "daily_return": _clean_num(row.get("daily_return")),
                })
            if rows_data:
                try:
                    session.execute(text("""
                        INSERT OR REPLACE INTO commodity_prices 
                        (symbol, date, open, high, low, close, volume, daily_return)
                        VALUES (:symbol, :date, :open, :high, :low, :close, :volume, :daily_return)
                    """), rows_data)
                    session.commit()
                    total_saved += len(rows_data)
                except Exception as e:
                    session.rollback()
                    logger.error(f"Error inserting commodity_prices for {symbol}: {e}")

    return total_saved


def _clean_num(val):
    if val is None or pd.isna(val) or np.isinf(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def fill_missing_trading_days(session: Session, target_date: str = None) -> int:
    """
    Detects any active stocks or indexes that missed price data on the latest completed
    market trading day (e.g. due to yfinance 1d ingestion gaps), fetches 60m hourly data,
    aggregates the session, and saves the complete daily bars.
    """
    max_allowed = get_max_allowed_eod_date()
    if target_date is None:
        bench_date = session.execute(
            text("SELECT MAX(date) FROM daily_prices WHERE date <= :m"),
            {"m": str(max_allowed)}
        ).scalar()
        if not bench_date:
            return 0
        target_date = str(bench_date)

    # 1. Stocks Gap Filling
    missing_stocks = session.execute(
        text("""
            SELECT s.id, s.symbol, s.yf_symbol 
            FROM stocks s 
            WHERE s.is_active = 1 
            AND s.symbol NOT IN (SELECT symbol FROM daily_prices WHERE date = :td)
        """),
        {"td": target_date}
    ).fetchall()

    filled_count = 0
    if missing_stocks:
        logger.info(f"📊 Resolving {len(missing_stocks)} stock gaps for completed session {target_date}...")
        batches = [missing_stocks[i:i + 35] for i in range(0, len(missing_stocks), 35)]
        for batch in batches:
            batch_yf = [s[2] for s in batch]
            try:
                raw_60m = yf.download(batch_yf, period="5d", interval="60m", progress=False)
                for s_id, sym, yf_sym in batch:
                    df_sym = None
                    if not raw_60m.empty and hasattr(raw_60m.columns, "levels") and yf_sym in raw_60m["Close"].columns:
                        sub = pd.DataFrame({
                            "open": raw_60m["Open"][yf_sym],
                            "high": raw_60m["High"][yf_sym],
                            "low": raw_60m["Low"][yf_sym],
                            "close": raw_60m["Close"][yf_sym],
                            "volume": raw_60m["Volume"][yf_sym]
                        }).dropna(subset=["close"])
                        sub_target = sub[sub.index.strftime("%Y-%m-%d") == target_date]
                        if not sub_target.empty:
                            df_sym = sub_target

                    if df_sym is not None and not df_sym.empty:
                        o = float(df_sym["open"].iloc[0])
                        h = float(df_sym["high"].max())
                        l = float(df_sym["low"].min())
                        c = float(df_sym["close"].iloc[-1])
                        v = float(df_sym["volume"].sum())
                    else:
                        prev_row = session.execute(
                            text("SELECT close FROM daily_prices WHERE symbol = :s AND date < :td ORDER BY date DESC LIMIT 1"),
                            {"s": sym, "td": target_date}
                        ).scalar()
                        if prev_row:
                            o, h, l, c, v = prev_row, prev_row, prev_row, prev_row, 0.0
                        else:
                            continue

                    prev_c = session.execute(
                        text("SELECT close FROM daily_prices WHERE symbol = :s AND date < :td ORDER BY date DESC LIMIT 1"),
                        {"s": sym, "td": target_date}
                    ).scalar()
                    ret = ((c - prev_c) / prev_c * 100.0) if (prev_c and prev_c > 0) else 0.0
                    log_ret = float(np.log(c / prev_c)) if (prev_c and prev_c > 0 and c > 0) else 0.0

                    session.execute(text("""
                        INSERT OR REPLACE INTO daily_prices
                        (stock_id, symbol, date, open, high, low, close, adj_close, volume, daily_return, log_return)
                        VALUES (:stock_id, :symbol, :date, :open, :high, :low, :close, :adj_close, :volume, :daily_return, :log_return)
                    """), {
                        "stock_id": s_id,
                        "symbol": sym,
                        "date": target_date,
                        "open": o, "high": h, "low": l, "close": c, "adj_close": c, "volume": v,
                        "daily_return": round(ret, 4), "log_return": round(log_ret, 6)
                    })
                    filled_count += 1
                session.commit()
            except Exception as e:
                session.rollback()
                logger.warning(f"60m stock gap fill error for batch: {e}")

    # 2. Indexes Gap Filling
    missing_indexes = session.execute(
        text("""
            SELECT DISTINCT i.symbol 
            FROM index_prices i 
            WHERE i.symbol NOT IN (SELECT symbol FROM index_prices WHERE date = :td)
        """),
        {"td": target_date}
    ).fetchall()

    if missing_indexes:
        idx_syms = [r[0] for r in missing_indexes]
        logger.info(f"📊 Resolving {len(idx_syms)} index gaps for completed session {target_date}...")
        try:
            raw_idx = yf.download(idx_syms, period="5d", interval="60m", progress=False)
            for sym in idx_syms:
                df_idx = None
                if not raw_idx.empty and hasattr(raw_idx.columns, "levels") and sym in raw_idx["Close"].columns:
                    sub = pd.DataFrame({
                        "open": raw_idx["Open"][sym],
                        "high": raw_idx["High"][sym],
                        "low": raw_idx["Low"][sym],
                        "close": raw_idx["Close"][sym],
                        "volume": raw_idx["Volume"][sym]
                    }).dropna(subset=["close"])
                    sub_target = sub[sub.index.strftime("%Y-%m-%d") == target_date]
                    if not sub_target.empty:
                        df_idx = sub_target

                if df_idx is not None and not df_idx.empty:
                    o = float(df_idx["open"].iloc[0])
                    h = float(df_idx["high"].max())
                    l = float(df_idx["low"].min())
                    c = float(df_idx["close"].iloc[-1])
                    v = float(df_idx["volume"].sum())
                else:
                    prev_row = session.execute(
                        text("SELECT close FROM index_prices WHERE symbol = :s AND date < :td ORDER BY date DESC LIMIT 1"),
                        {"s": sym, "td": target_date}
                    ).scalar()
                    if prev_row:
                        o, h, l, c, v = prev_row, prev_row, prev_row, prev_row, 0.0
                    else:
                        continue

                prev_c = session.execute(
                    text("SELECT close FROM index_prices WHERE symbol = :s AND date < :td ORDER BY date DESC LIMIT 1"),
                    {"s": sym, "td": target_date}
                ).scalar()
                ret = ((c - prev_c) / prev_c * 100.0) if (prev_c and prev_c > 0) else 0.0

                session.execute(text("""
                    INSERT OR REPLACE INTO index_prices
                    (symbol, date, open, high, low, close, volume, daily_return)
                    VALUES (:symbol, :date, :open, :high, :low, :close, :volume, :daily_return)
                """), {
                    "symbol": sym, "date": target_date,
                    "open": o, "high": h, "low": l, "close": c, "volume": v,
                    "daily_return": round(ret, 4)
                })
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning(f"Index gap fill error: {e}")

    if filled_count > 0:
        logger.info(f"✅ Filled {filled_count} missing stock records for {target_date}")
    return filled_count


def download_historical_data(
    stocks: List[Dict],
    session: Session,
    start_date: str = DOWNLOAD_START_DATE,
    end_date: str = None,
    progress_callback=None,
):
    """
    Download full historical data for all stocks with anti-bot protection.

    Args:
        stocks: List of dicts with 'symbol', 'yf_symbol', 'name' keys
        session: Database session
        start_date: Download from this date
        end_date: Download until this date (default: end of latest completed trading day)
        progress_callback: Optional callback(current, total, symbol) for progress UI
    """
    if end_date is None:
        end_date = get_eod_end_date()

    # Pre-clean any active intraday data
    cleanup_active_market_data(session)

    total = len(stocks)
    logger.info(f"Starting historical download for {total} stocks from {start_date} to {end_date}")

    # Group into batches
    batches = [stocks[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]

    processed = 0
    for batch_idx, batch in enumerate(batches):
        yf_symbols = [s["yf_symbol"] for s in batch]
        orig_symbols = [s["symbol"] for s in batch]

        logger.info(f"Batch {batch_idx+1}/{len(batches)}: {orig_symbols[:3]}... ({len(batch)} stocks)")

        # Check incremental — find latest date for each symbol
        batch_start = start_date
        incremental_starts = {}
        for s in batch:
            last = get_last_download_date(s["symbol"], session)
            if last:
                if isinstance(last, str):
                    try:
                        last_d = datetime.strptime(last[:10], "%Y-%m-%d").date()
                    except Exception:
                        last_d = date.today() - timedelta(days=365)
                elif isinstance(last, datetime):
                    last_d = last.date()
                elif isinstance(last, date):
                    last_d = last
                else:
                    try:
                        last_d = date.fromtimestamp(int(last))
                    except Exception:
                        last_d = date.today() - timedelta(days=365)
                next_day = (last_d + timedelta(days=1)).strftime("%Y-%m-%d")
                incremental_starts[s["symbol"]] = next_day
            else:
                incremental_starts[s["symbol"]] = start_date

        # Filter to only stocks that actually need new data
        stocks_needing_download = [
            s for s in batch if incremental_starts.get(s["symbol"], start_date) < end_date
        ]

        if not stocks_needing_download:
            logger.info(f"Batch {batch_idx+1}: All {len(batch)} symbols up to date, skipping")
            processed += len(batch)
            if progress_callback:
                progress_callback(processed, total, "up-to-date")
            continue

        dl_yf_symbols = [s["yf_symbol"] for s in stocks_needing_download]
        dl_orig_symbols = [s["symbol"] for s in stocks_needing_download]
        actual_start = min(incremental_starts[s["symbol"]] for s in stocks_needing_download)

        # Download batch
        data_dict = download_stocks_batch(dl_yf_symbols, dl_orig_symbols, actual_start, end_date)

        if data_dict:
            saved = save_prices_to_db(data_dict, "daily_prices", session)
            logger.info(f"Batch {batch_idx+1}: Saved {saved} rows ({len(stocks_needing_download)} stocks)")

            # Log download
            for s in stocks_needing_download:
                log = DownloadLog(
                    symbol=s["symbol"],
                    download_type="historical",
                    start_date=datetime.strptime(actual_start, "%Y-%m-%d").date(),
                    end_date=datetime.strptime(end_date, "%Y-%m-%d").date(),
                    rows_downloaded=data_dict.get(s["symbol"], pd.DataFrame()).shape[0],
                    status="success" if s["symbol"] in data_dict else "no_data",
                )
                session.add(log)
            session.commit()
        else:
            logger.warning(f"Batch {batch_idx+1}: No data returned")

        processed += len(batch)
        if progress_callback:
            progress_callback(processed, total, batch[0]["name"])

        # Human-like delay between batches
        if batch_idx < len(batches) - 1:
            _human_delay()

    # Automatically fill any gaps from 60m data for completed sessions
    fill_missing_trading_days(session)

    logger.info(f"✅ Historical download complete: {processed}/{total} stocks processed")


def download_indexes_and_commodities(session: Session, end_date: str = None):
    """Download index and commodity data."""
    import yaml
    config_path = Path(__file__).resolve().parent.parent / "config" / "stocks.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    if end_date is None:
        end_date = get_eod_end_date()

    # Indexes
    indexes = config.get("indexes", [])
    idx_symbols = [i["symbol"] for i in indexes]
    logger.info(f"Downloading {len(idx_symbols)} indexes...")

    for i in range(0, len(idx_symbols), 5):
        batch = idx_symbols[i:i+5]
        data = download_stocks_batch(batch, batch, DOWNLOAD_START_DATE, end_date)
        if data:
            save_prices_to_db(data, "index_prices", session)
        _human_delay(1, 3)

    # Commodities
    commodities = config.get("commodities", [])
    com_symbols = [c["symbol"] for c in commodities]
    logger.info(f"Downloading {len(com_symbols)} commodities...")

    for i in range(0, len(com_symbols), 5):
        batch = com_symbols[i:i+5]
        data = download_stocks_batch(batch, batch, DOWNLOAD_START_DATE, end_date)
        if data:
            save_prices_to_db(data, "commodity_prices", session)
        _human_delay(1, 3)

    logger.info("✅ Indexes and commodities downloaded")


def daily_update(session: Session):
    """
    Incremental update — download only the latest data since last download date.
    Run this daily after market close.
    """
    end_date = get_eod_end_date()
    start = (date.today() - timedelta(days=5)).strftime("%Y-%m-%d")

    cleanup_active_market_data(session)

    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    stock_list = [{"symbol": s.symbol, "yf_symbol": s.yf_symbol, "name": s.name} for s in stocks]

    logger.info(f"Daily update for {len(stock_list)} stocks")

    batches = [stock_list[i:i+50] for i in range(0, len(stock_list), 50)]

    for batch in batches:
        yf_symbols = [s["yf_symbol"] for s in batch]
        orig_symbols = [s["symbol"] for s in batch]

        data = download_stocks_batch(yf_symbols, orig_symbols, start, end_date)
        if data:
            save_prices_to_db(data, "daily_prices", session)

        _human_delay(1.5, 4.0)

    download_indexes_and_commodities(session, end_date=end_date)
    fill_missing_trading_days(session)

    logger.info("✅ Daily update complete")


def get_price_dataframe(symbol: str, session: Session, days: int = 365) -> pd.DataFrame:
    """
    Retrieve price data from DB as a pandas DataFrame.
    Returns OHLCV data for the last N days.
    """
    start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    result = session.execute(
        text("""
            SELECT date, open, high, low, close, volume, daily_return, log_return
            FROM daily_prices
            WHERE symbol = :symbol AND date >= :start
            ORDER BY date ASC
        """),
        {"symbol": symbol, "start": start}
    ).fetchall()

    if not result:
        return pd.DataFrame()

    df = pd.DataFrame(result, columns=["date", "open", "high", "low", "close", "volume", "daily_return", "log_return"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df = df.sort_index()
    return df


def get_all_prices_dataframe(symbol: str, session: Session) -> pd.DataFrame:
    """Get complete historical price data for a symbol."""
    result = session.execute(
        text("""
            SELECT date, open, high, low, close, volume, daily_return, log_return
            FROM daily_prices
            WHERE symbol = :symbol
            ORDER BY date ASC
        """),
        {"symbol": symbol}
    ).fetchall()

    if not result:
        return pd.DataFrame()

    df = pd.DataFrame(result, columns=["date", "open", "high", "low", "close", "volume", "daily_return", "log_return"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df


def get_index_dataframe(symbol: str, session: Session, days: int = 365) -> pd.DataFrame:
    """Get index price data."""
    start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    result = session.execute(
        text("""
            SELECT date, open, high, low, close, volume, daily_return
            FROM index_prices
            WHERE symbol = :symbol AND date >= :start
            ORDER BY date ASC
        """),
        {"symbol": symbol, "start": start}
    ).fetchall()

    if not result:
        return pd.DataFrame()

    df = pd.DataFrame(result, columns=["date", "open", "high", "low", "close", "volume", "daily_return"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df


def get_commodity_dataframe(symbol: str, session: Session, days: int = 365) -> pd.DataFrame:
    """Get commodity price data."""
    start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    result = session.execute(
        text("""
            SELECT date, open, high, low, close, volume, daily_return
            FROM commodity_prices
            WHERE symbol = :symbol AND date >= :start
            ORDER BY date ASC
        """),
        {"symbol": symbol, "start": start}
    ).fetchall()

    if not result:
        return pd.DataFrame()

    df = pd.DataFrame(result, columns=["date", "open", "high", "low", "close", "volume", "daily_return"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df


def get_data_summary(session: Session) -> pd.DataFrame:
    """Summary of what data we have in the DB."""
    result = session.execute(text("""
        SELECT s.symbol, s.name, s.sector, s.market_cap_tier,
               MIN(p.date) as first_date, MAX(p.date) as last_date,
               COUNT(p.id) as row_count
        FROM stocks s
        LEFT JOIN daily_prices p ON s.id = p.stock_id
        GROUP BY s.symbol, s.name, s.sector, s.market_cap_tier
        ORDER BY s.sector, s.symbol
    """)).fetchall()

    return pd.DataFrame(
        result,
        columns=["symbol", "name", "sector", "tier", "first_date", "last_date", "rows"]
    )
