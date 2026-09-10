"""
core/sip_tracker.py
SIP Suggestion Logging & Forward Accuracy Tracker
"""
import logging
from datetime import date, timedelta
from typing import Dict, List
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

_CREATE_SIP_LOG_TABLE = """
    CREATE TABLE IF NOT EXISTS sip_suggestion_log (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        log_date           TEXT NOT NULL,
        month_label        TEXT NOT NULL,
        symbol             TEXT NOT NULL,
        name               TEXT,
        asset_class        TEXT DEFAULT 'Stock',
        sector             TEXT,
        tier               TEXT,
        strategy           TEXT,
        exit_protocol      TEXT,
        entry_price        REAL NOT NULL,
        shares_suggested   INTEGER,
        total_cost         REAL,
        stop_loss          REAL,
        target_price       REAL,
        composite_score    REAL,
        signal             TEXT,
        momentum_6m_pct    REAL,
        status             TEXT DEFAULT 'OPEN',
        max_price_reached  REAL,
        min_price_reached  REAL,
        exit_date          TEXT,
        exit_price         REAL,
        realized_gain_pct  REAL,
        benchmark_gain_pct REAL,
        alpha_pct          REAL,
        forward_1d_pct     REAL,
        forward_5d_pct     REAL,
        forward_1m_pct     REAL,
        forward_3m_pct     REAL,
        days_held          INTEGER,
        verified_date      TEXT,
        UNIQUE(log_date, symbol, strategy)
    )
"""

_MIGRATION_COLS = [
    "asset_class TEXT DEFAULT 'Stock'",
    "max_price_reached REAL", "min_price_reached REAL", "exit_date TEXT",
    "exit_price REAL", "realized_gain_pct REAL", "benchmark_gain_pct REAL",
    "alpha_pct REAL", "forward_1d_pct REAL", "forward_5d_pct REAL",
    "forward_1m_pct REAL", "forward_3m_pct REAL", "days_held INTEGER",
    "verified_date TEXT", "momentum_6m_pct REAL",
]


def init_sip_log_table(session: Session) -> None:
    """Create sip_suggestion_log table and add any missing columns."""
    session.execute(text(_CREATE_SIP_LOG_TABLE))
    for col_def in _MIGRATION_COLS:
        try:
            session.execute(text(f"ALTER TABLE sip_suggestion_log ADD COLUMN {col_def}"))
        except Exception:
            pass
    session.commit()


def get_any_asset_latest_price(session: Session, symbol: str, asset_class: str = None) -> float | None:
    """
    Robust latest price lookup across all asset tables:
    1. Check appropriate table based on asset_class or symbol type
    2. Fallback across all other price tables if not found (e.g., GOLDBEES.NS is in index_prices, MF_122639 in mutual_fund_navs)
    """
    if not symbol:
        return None

    sym = str(symbol).strip()
    ac = (asset_class or "").strip()

    # Extract clean MF scheme code if prefixed with MF_ or is numeric
    mf_code = sym.replace("MF_", "") if sym.startswith("MF_") else sym

    # 1. Mutual Fund Check
    if ac in ("Mutual Fund", "MF") or sym.startswith("MF_") or mf_code.isdigit():
        p = session.execute(
            text("SELECT nav FROM mutual_fund_navs WHERE scheme_code=:s ORDER BY date DESC LIMIT 1"),
            {"s": mf_code}
        ).scalar()
        if p is not None:
            return float(p)

    # 2. Commodity Check
    if ac == "Commodity" or any(c in sym.upper() for c in ["GOLD", "SILVER", "CRUDE", "COPPER"]) and ("=" in sym or "F" in sym):
        p = session.execute(
            text("SELECT close FROM commodity_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"),
            {"s": sym}
        ).scalar()
        if p is not None:
            return float(p)

    # 3. Index / ETF Check
    if ac in ("Index / ETF", "Index") or sym.startswith("^") or "BEES" in sym.upper() or "ETF" in sym.upper():
        p = session.execute(
            text("SELECT close FROM index_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"),
            {"s": sym}
        ).scalar()
        if p is not None:
            return float(p)

    # 4. Stock Check (default)
    p = session.execute(
        text("SELECT close FROM daily_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"),
        {"s": sym}
    ).scalar()
    if p is not None:
        return float(p)

    # 5. Fallbacks across all tables
    # Index / ETF table
    p = session.execute(
        text("SELECT close FROM index_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"),
        {"s": sym}
    ).scalar()
    if p is not None:
        return float(p)

    # Commodity table
    p = session.execute(
        text("SELECT close FROM commodity_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"),
        {"s": sym}
    ).scalar()
    if p is not None:
        return float(p)

    # Mutual Fund table (using both mf_code and sym)
    for c in [mf_code, sym]:
        p = session.execute(
            text("SELECT nav FROM mutual_fund_navs WHERE scheme_code=:s ORDER BY date DESC LIMIT 1"),
            {"s": c}
        ).scalar()
        if p is not None:
            return float(p)

    return None


def log_sip_basket(
    session: Session,
    basket: Dict,
    strategy: str,
    exit_protocol: str,
    force_relog: bool = False,
) -> int:
    """
    Snapshot the current basket into sip_suggestion_log across all asset classes:
    Stocks, Indexes / ETFs, Commodities, and Mutual Funds.
    Returns number of new rows inserted.
    """
    init_sip_log_table(session)
    today_str   = date.today().isoformat()
    month_label = date.today().strftime("%b %Y")
    inserted    = 0

    assets_list = basket.get("assets") or basket.get("selected_assets") or []
    for asset in assets_list:
        symbol = str(asset.get("symbol", "")).strip()
        if not symbol:
            continue

        raw_asset_class = str(asset.get("asset_class", "")).strip()
        if not raw_asset_class or raw_asset_class == "Stock":
            if "NIFTY" in symbol.upper() or symbol.startswith("^") or "BEES" in symbol.upper() or "ETF" in symbol.upper():
                raw_asset_class = "Index / ETF"
            elif any(c in symbol.upper() for c in ["GOLD", "SILVER", "CRUDE", "COPPER"]) and ("=" in symbol or "F" in symbol):
                raw_asset_class = "Commodity"
            elif symbol.isdigit() or symbol.startswith("MF_") or "FUND" in str(asset.get("name", "")).upper():
                raw_asset_class = "Mutual Fund"
            else:
                raw_asset_class = raw_asset_class or "Stock"

        entry_price = float(asset.get("current_price", 0.0) or asset.get("nav", 0.0))
        if entry_price <= 0:
            pr = get_any_asset_latest_price(session, symbol, raw_asset_class)
            entry_price = float(pr) if pr else 0.0

        if entry_price <= 0:
            continue

        # Fetch 6M momentum if not in asset dict
        momentum_6m = asset.get("momentum_6m_pct", None)
        if momentum_6m is None:
            if raw_asset_class == "Stock":
                row = session.execute(text("""
                    SELECT (sig.current_price - dp_past.close) / NULLIF(dp_past.close, 0.0) * 100.0
                    FROM signals sig
                    LEFT JOIN daily_prices dp_past ON dp_past.symbol = sig.symbol
                        AND dp_past.date = (
                            SELECT MIN(date) FROM daily_prices
                            WHERE symbol = sig.symbol AND date >= date(:today, '-180 days')
                        )
                    WHERE sig.symbol = :sym ORDER BY sig.date DESC LIMIT 1
                """), {"sym": symbol, "today": today_str}).first()
                momentum_6m = round(float(row[0]), 2) if row and row[0] is not None else None
            elif raw_asset_class == "Mutual Fund" or symbol.isdigit():
                row = session.execute(text("""
                    SELECT (n1.nav - n2.nav) / NULLIF(n2.nav, 0.0) * 100.0
                    FROM mutual_fund_navs n1
                    JOIN mutual_fund_navs n2 ON n1.scheme_code = n2.scheme_code
                        AND n2.date = (SELECT MIN(date) FROM mutual_fund_navs WHERE scheme_code = n1.scheme_code AND date >= date(:today, '-180 days'))
                    WHERE n1.scheme_code = :sc ORDER BY n1.date DESC LIMIT 1
                """), {"sc": symbol, "today": today_str}).first()
                momentum_6m = round(float(row[0]), 2) if row and row[0] is not None else None

        params = {
            "log_date": today_str, "month_label": month_label,
            "symbol": symbol, "name": asset.get("name", symbol),
            "asset_class": raw_asset_class,
            "sector": asset.get("sector", "General"), "tier": asset.get("tier", "mid"),
            "strategy": strategy, "exit_protocol": exit_protocol,
            "entry_price": entry_price,
            "shares_suggested": int(asset.get("shares_to_buy", 1) or 1),
            "total_cost": float(asset.get("total_cost", entry_price)),
            "stop_loss": asset.get("stop_loss"),
            "target_price": asset.get("target_price") or asset.get("target_price_1"),
            "composite_score": asset.get("composite_score", 60.0),
            "signal": asset.get("signal", "BUY"),
            "momentum_6m_pct": momentum_6m,
        }

        if force_relog:
            session.execute(text("""
                INSERT INTO sip_suggestion_log
                    (log_date, month_label, symbol, name, asset_class, sector, tier, strategy, exit_protocol,
                     entry_price, shares_suggested, total_cost, stop_loss, target_price,
                     composite_score, signal, momentum_6m_pct, status, max_price_reached, min_price_reached)
                VALUES (:log_date,:month_label,:symbol,:name,:asset_class,:sector,:tier,:strategy,:exit_protocol,
                        :entry_price,:shares_suggested,:total_cost,:stop_loss,:target_price,
                        :composite_score,:signal,:momentum_6m_pct,'OPEN',:entry_price,:entry_price)
                ON CONFLICT(log_date, symbol, strategy) DO UPDATE SET
                    entry_price=excluded.entry_price, shares_suggested=excluded.shares_suggested,
                    total_cost=excluded.total_cost, stop_loss=excluded.stop_loss,
                    target_price=excluded.target_price, composite_score=excluded.composite_score,
                    signal=excluded.signal, momentum_6m_pct=excluded.momentum_6m_pct, status='OPEN',
                    asset_class=excluded.asset_class
            """), params)
            inserted += 1
        else:
            res = session.execute(text("""
                INSERT OR IGNORE INTO sip_suggestion_log
                    (log_date, month_label, symbol, name, asset_class, sector, tier, strategy, exit_protocol,
                     entry_price, shares_suggested, total_cost, stop_loss, target_price,
                     composite_score, signal, momentum_6m_pct, status, max_price_reached, min_price_reached)
                VALUES (:log_date,:month_label,:symbol,:name,:asset_class,:sector,:tier,:strategy,:exit_protocol,
                        :entry_price,:shares_suggested,:total_cost,:stop_loss,:target_price,
                        :composite_score,:signal,:momentum_6m_pct,'OPEN',:entry_price,:entry_price)
            """), params)
            if res.rowcount > 0:
                inserted += 1

    session.commit()
    logger.info(f"Multi-Asset SIP basket logged: {inserted} new picks [{strategy}] for {today_str}.")
    return inserted


def update_sip_forward_performance(session: Session) -> int:
    """
    Evaluate all OPEN sip_suggestion_log rows against latest market prices across
    all asset classes (Stocks, Mutual Funds, Indexes, Commodities).
    """
    init_sip_log_table(session)
    today_str = date.today().isoformat()

    open_rows = session.execute(text("""
        SELECT id, log_date, symbol, entry_price, stop_loss, target_price,
               max_price_reached, min_price_reached, asset_class
        FROM sip_suggestion_log WHERE status = 'OPEN'
    """)).fetchall()

    if not open_rows:
        return 0

    nifty_latest = session.execute(text("""
        SELECT close FROM index_prices WHERE symbol = '^NSEI' ORDER BY date DESC LIMIT 1
    """)).scalar()

    updated = 0
    for row in open_rows:
        rid, log_date_str, symbol, entry_price, stop_loss, target_price, max_p, min_p, asset_class = row

        curr_p = get_any_asset_latest_price(session, symbol, asset_class)

        if curr_p is None:
            continue

        curr_p       = float(curr_p)
        entry_price  = float(entry_price)  if entry_price  else 0.0
        stop_loss    = float(stop_loss)    if stop_loss    else None
        target_price = float(target_price) if target_price else None
        max_p        = float(max_p) if max_p else entry_price
        min_p        = float(min_p) if min_p else entry_price

        new_max = max(max_p, curr_p)
        new_min = min(min_p, curr_p)

        try:
            days_held = (date.today() - date.fromisoformat(log_date_str)).days
        except Exception:
            days_held = 0

        # Benchmark return over holding period
        bench_ret = 0.0
        if nifty_latest:
            nifty_start = session.execute(text("""
                SELECT close FROM index_prices WHERE symbol = '^NSEI' AND date <= :ld ORDER BY date DESC LIMIT 1
            """), {"ld": log_date_str}).scalar()
            if nifty_start and float(nifty_start) > 0:
                bench_ret = round((float(nifty_latest) - float(nifty_start)) / float(nifty_start) * 100.0, 2)

        new_status = "OPEN"
        exit_price = realized_gain_pct = exit_date = None

        if stop_loss and curr_p <= stop_loss:
            new_status = "SL_HIT"; exit_price = curr_p; exit_date = today_str
        elif target_price and curr_p >= target_price:
            new_status = "T1_HIT"; exit_price = curr_p; exit_date = today_str
        elif target_price and new_max >= target_price and curr_p < entry_price:
            new_status = "TRAILING_SL_HIT"; exit_price = curr_p; exit_date = today_str
        elif days_held > 365:
            new_status = "EXPIRED"; exit_price = curr_p; exit_date = today_str

        current_or_exit_p = exit_price if exit_price else curr_p
        gain_pct = round((current_or_exit_p - entry_price) / entry_price * 100.0, 2) if entry_price > 0 else 0.0
        alpha_val = round(gain_pct - bench_ret, 2)

        if exit_price and entry_price > 0:
            realized_gain_pct = gain_pct

        session.execute(text("""
            UPDATE sip_suggestion_log SET
                max_price_reached=:max_p, min_price_reached=:min_p,
                status=:status, exit_date=:exit_date, exit_price=:exit_price,
                realized_gain_pct=:realized_gain_pct,
                benchmark_gain_pct=:bench_gain, alpha_pct=:alpha,
                days_held=:days_held, verified_date=:verified_date
            WHERE id=:rid
        """), {
            "max_p": round(new_max, 2), "min_p": round(new_min, 2),
            "status": new_status, "exit_date": exit_date,
            "exit_price": round(exit_price, 2) if exit_price else None,
            "realized_gain_pct": realized_gain_pct,
            "bench_gain": bench_ret,
            "alpha": alpha_val,
            "days_held": days_held,
            "verified_date": today_str, "rid": rid,
        })
        if new_status != "OPEN":
            updated += 1

    session.commit()
    logger.info(f"Multi-Asset SIP tracker: {updated}/{len(open_rows)} positions evaluated and updated.")
    return updated


def evaluate_multi_asset_sip_accuracy(
    session: Session,
    months: int = 12,
    asset_class_filter: str = "ALL",
    strategy_filter: str = "ALL"
) -> Dict:
    """
    Comprehensive multi-asset accuracy analysis for Monthly SIP suggestions:
      - Aggregates outcomes across Stocks, Indexes, Commodities, and MFs.
      - Calculates Hit Rate (Win %), Benchmark Beat Rate (% beating NIFTY 50),
        Profit Factor, Average Alpha (%), XIRR, and Strategy Breakdown.
    """
    init_sip_log_table(session)
    since_date = (date.today() - timedelta(days=months * 30)).isoformat()

    query = """
        SELECT symbol, name, asset_class, sector, tier, log_date, month_label, strategy,
               entry_price, stop_loss, target_price, composite_score, momentum_6m_pct,
               status, exit_date, exit_price, realized_gain_pct, benchmark_gain_pct, alpha_pct,
               days_held, max_price_reached, min_price_reached, shares_suggested, total_cost
        FROM sip_suggestion_log
        WHERE log_date >= :since
    """
    params = {"since": since_date}

    if asset_class_filter != "ALL":
        query += " AND asset_class = :ac"
        params["ac"] = asset_class_filter
    if strategy_filter != "ALL":
        query += " AND strategy = :strat"
        params["strat"] = strategy_filter

    query += " ORDER BY log_date DESC, symbol"

    rows = session.execute(text(query), params).fetchall()

    cols = [
        "symbol", "name", "asset_class", "sector", "tier", "log_date", "month_label", "strategy",
        "entry_price", "stop_loss", "target_price", "composite_score", "momentum_6m_pct",
        "status", "exit_date", "exit_price", "realized_gain_pct", "benchmark_gain_pct", "alpha_pct",
        "days_held", "max_price_reached", "min_price_reached", "shares_suggested", "total_cost"
    ]
    df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)

    _empty = {
        "total_suggestions": 0, "win_rate_pct": 0.0, "benchmark_beat_rate_pct": 0.0,
        "profit_factor": 0.0, "avg_winner_gain_pct": 0.0, "avg_loser_loss_pct": 0.0,
        "avg_alpha_pct": 0.0, "live_xirr_pct": 0.0, "open_count": 0, "completed_count": 0,
        "asset_class_stats": {}, "strategy_stats": {}, "df": df
    }
    if df.empty:
        return _empty

    df["realized_gain_pct"] = pd.to_numeric(df["realized_gain_pct"], errors="coerce")
    df["entry_price"]       = pd.to_numeric(df["entry_price"],       errors="coerce")
    df["exit_price"]        = pd.to_numeric(df["exit_price"],        errors="coerce")
    df["benchmark_gain_pct"] = pd.to_numeric(df["benchmark_gain_pct"], errors="coerce").fillna(0.0)
    df["alpha_pct"]          = pd.to_numeric(df["alpha_pct"],          errors="coerce").fillna(0.0)
    df["total_cost"]        = pd.to_numeric(df["total_cost"],        errors="coerce").fillna(0.0)

    # Compute live unrealized gain for open rows
    open_mask = df["status"] == "OPEN"
    if open_mask.any():
        for idx_row, r in df[open_mask].iterrows():
            sym = r["symbol"]
            ac = r["asset_class"] or "Stock"
            curr_p = get_any_asset_latest_price(session, sym, ac)

            if curr_p and float(r["entry_price"]) > 0:
                ep = float(r["entry_price"])
                cp = float(curr_p)
                ugain = round((cp - ep) / ep * 100.0, 2)
                df.at[idx_row, "unrealized_gain_pct"] = ugain
                df.at[idx_row, "current_price"] = cp
                df.at[idx_row, "alpha_pct"] = round(ugain - float(r["benchmark_gain_pct"]), 2)
            else:
                df.at[idx_row, "unrealized_gain_pct"] = 0.0
                df.at[idx_row, "current_price"] = r["entry_price"]

    # Calculate days_held for all rows if null
    for idx_row, r in df.iterrows():
        if pd.isna(r["days_held"]) or r["days_held"] is None:
            try:
                log_d = date.fromisoformat(str(r["log_date"]))
                exit_d = date.fromisoformat(str(r["exit_date"])) if r.get("exit_date") else date.today()
                df.at[idx_row, "days_held"] = max(0, (exit_d - log_d).days)
            except Exception:
                df.at[idx_row, "days_held"] = 0

    # Effective gain = realized for closed, unrealized for open
    df["effective_gain_pct"] = df["realized_gain_pct"].combine_first(df["unrealized_gain_pct"]).fillna(0.0)

    total_cnt = len(df)
    winners = df[df["effective_gain_pct"] > 0]
    losers = df[df["effective_gain_pct"] <= 0]
    beat_benchmark = df[df["alpha_pct"] > 0]

    win_rate = round(len(winners) / max(1, total_cnt) * 100.0, 1)
    beat_rate = round(len(beat_benchmark) / max(1, total_cnt) * 100.0, 1)

    gross_gain = winners["effective_gain_pct"].sum() if len(winners) > 0 else 0.0
    gross_loss = abs(losers["effective_gain_pct"].sum()) if len(losers) > 0 else 0.0
    pf = round(gross_gain / max(0.01, gross_loss), 2)

    avg_win = round(winners["effective_gain_pct"].mean(), 2) if len(winners) > 0 else 0.0
    avg_loss = round(losers["effective_gain_pct"].mean(), 2) if len(losers) > 0 else 0.0
    avg_alpha = round(df["alpha_pct"].mean(), 2)
    live_xirr = _compute_live_xirr(df)

    # Asset Class Breakdown
    ac_stats = {}
    for ac_name, grp in df.groupby("asset_class"):
        ac_win = round((grp["effective_gain_pct"] > 0).mean() * 100.0, 1)
        ac_beat = round((grp["alpha_pct"] > 0).mean() * 100.0, 1)
        ac_stats[ac_name] = {
            "count": len(grp),
            "win_rate_pct": ac_win,
            "benchmark_beat_pct": ac_beat,
            "avg_return_pct": round(grp["effective_gain_pct"].mean(), 2),
            "avg_alpha_pct": round(grp["alpha_pct"].mean(), 2)
        }

    # Strategy Breakdown
    strat_stats = {}
    for st_name, grp in df.groupby("strategy"):
        st_win = round((grp["effective_gain_pct"] > 0).mean() * 100.0, 1)
        st_beat = round((grp["alpha_pct"] > 0).mean() * 100.0, 1)
        strat_stats[st_name] = {
            "count": len(grp),
            "win_rate_pct": st_win,
            "benchmark_beat_pct": st_beat,
            "avg_return_pct": round(grp["effective_gain_pct"].mean(), 2),
            "avg_alpha_pct": round(grp["alpha_pct"].mean(), 2)
        }

    return {
        "total_suggestions": total_cnt,
        "win_rate_pct": win_rate,
        "benchmark_beat_rate_pct": beat_rate,
        "profit_factor": pf,
        "avg_winner_gain_pct": avg_win,
        "avg_loser_loss_pct": avg_loss,
        "avg_alpha_pct": avg_alpha,
        "live_xirr_pct": live_xirr,
        "open_count": int(open_mask.sum()),
        "completed_count": int((~open_mask).sum()),
        "t1_count": int(df["status"].isin(["T1_HIT", "TRAILING_SL_HIT"]).sum()),
        "sl_count": int((df["status"] == "SL_HIT").sum()),
        "trailing_sl_count": int((df["status"] == "TRAILING_SL_HIT").sum()),
        "expired_count": int((df["status"] == "EXPIRED").sum()),
        "asset_class_stats": ac_stats,
        "strategy_stats": strat_stats,
        "df": df,
    }


def get_sip_accuracy_report(session: Session, months: int = 12) -> Dict:
    """Backward-compatible wrapper around evaluate_multi_asset_sip_accuracy."""
    return evaluate_multi_asset_sip_accuracy(session, months=months, asset_class_filter="ALL", strategy_filter="ALL")


def _compute_live_xirr(df: pd.DataFrame) -> float:
    """Compute XIRR from all logged suggestion cash flows."""
    cash_flows = []
    for _, r in df.iterrows():
        try:
            log_d = date.fromisoformat(str(r["log_date"]))
            cost = float(r["total_cost"]) if r["total_cost"] > 0 else \
                   float(r["entry_price"]) * max(1, int(r["shares_suggested"] or 1))
            cash_flows.append((log_d, -cost))
            shares = max(1, int(r["shares_suggested"] or 1))
            if r["status"] != "OPEN" and r["exit_date"] and r["exit_price"]:
                cash_flows.append((date.fromisoformat(str(r["exit_date"])),
                                   float(r["exit_price"]) * shares))
            elif "current_price" in r and r["current_price"]:
                cash_flows.append((date.today(), float(r["current_price"]) * shares))
            else:
                cash_flows.append((date.today(), float(r["entry_price"]) * shares))
        except Exception:
            continue
    if len(cash_flows) < 2:
        return 0.0
    try:
        from core.sip_audit_backtester import calculate_xirr
        return calculate_xirr(cash_flows)
    except Exception:
        return 0.0

