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
        days_held          INTEGER,
        verified_date      TEXT,
        UNIQUE(log_date, symbol, strategy)
    )
"""

_MIGRATION_COLS = [
    "max_price_reached REAL", "min_price_reached REAL", "exit_date TEXT",
    "exit_price REAL", "realized_gain_pct REAL", "days_held INTEGER",
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


def log_sip_basket(
    session: Session,
    basket: Dict,
    strategy: str,
    exit_protocol: str,
    force_relog: bool = False,
) -> int:
    """
    Snapshot the current basket into sip_suggestion_log.
    Skips ETF/Commodity positions. Returns number of new rows inserted.
    """
    init_sip_log_table(session)
    today_str   = date.today().isoformat()
    month_label = date.today().strftime("%b %Y")
    inserted    = 0

    assets_list = basket.get("assets") or basket.get("selected_assets") or []
    for asset in assets_list:
        symbol = asset.get("symbol", "")
        if not symbol or asset.get("asset_class") in ("Index / ETF", "Commodity"):
            continue
        entry_price = float(asset.get("current_price", 0.0))
        if entry_price <= 0:
            continue

        # Fetch 6M momentum if not in asset dict
        momentum_6m = asset.get("momentum_6m_pct", None)
        if momentum_6m is None:
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

        params = {
            "log_date": today_str, "month_label": month_label,
            "symbol": symbol, "name": asset.get("name", symbol),
            "sector": asset.get("sector", "General"), "tier": asset.get("tier", "mid"),
            "strategy": strategy, "exit_protocol": exit_protocol,
            "entry_price": entry_price,
            "shares_suggested": asset.get("shares_to_buy", 0),
            "total_cost": asset.get("total_cost", 0.0),
            "stop_loss": asset.get("stop_loss"),
            "target_price": asset.get("target_price"),
            "composite_score": asset.get("composite_score"),
            "signal": asset.get("signal", "BUY"),
            "momentum_6m_pct": momentum_6m,
        }

        if force_relog:
            session.execute(text("""
                INSERT INTO sip_suggestion_log
                    (log_date, month_label, symbol, name, sector, tier, strategy, exit_protocol,
                     entry_price, shares_suggested, total_cost, stop_loss, target_price,
                     composite_score, signal, momentum_6m_pct, status, max_price_reached, min_price_reached)
                VALUES (:log_date,:month_label,:symbol,:name,:sector,:tier,:strategy,:exit_protocol,
                        :entry_price,:shares_suggested,:total_cost,:stop_loss,:target_price,
                        :composite_score,:signal,:momentum_6m_pct,'OPEN',:entry_price,:entry_price)
                ON CONFLICT(log_date, symbol, strategy) DO UPDATE SET
                    entry_price=excluded.entry_price, shares_suggested=excluded.shares_suggested,
                    total_cost=excluded.total_cost, stop_loss=excluded.stop_loss,
                    target_price=excluded.target_price, composite_score=excluded.composite_score,
                    signal=excluded.signal, momentum_6m_pct=excluded.momentum_6m_pct, status='OPEN'
            """), params)
            inserted += 1
        else:
            res = session.execute(text("""
                INSERT OR IGNORE INTO sip_suggestion_log
                    (log_date, month_label, symbol, name, sector, tier, strategy, exit_protocol,
                     entry_price, shares_suggested, total_cost, stop_loss, target_price,
                     composite_score, signal, momentum_6m_pct, status, max_price_reached, min_price_reached)
                VALUES (:log_date,:month_label,:symbol,:name,:sector,:tier,:strategy,:exit_protocol,
                        :entry_price,:shares_suggested,:total_cost,:stop_loss,:target_price,
                        :composite_score,:signal,:momentum_6m_pct,'OPEN',:entry_price,:entry_price)
            """), params)
            if res.rowcount > 0:
                inserted += 1

    session.commit()
    logger.info(f"SIP basket logged: {inserted} new picks [{strategy}] for {today_str}.")
    return inserted


def update_sip_forward_performance(session: Session) -> int:
    """
    Evaluate all OPEN sip_suggestion_log rows against latest market prices.
    Exit priority: SL_HIT > T1_HIT > TRAILING_SL_HIT > EXPIRED (365 days).
    Returns count of positions that changed status.
    """
    init_sip_log_table(session)
    today_str = date.today().isoformat()

    open_rows = session.execute(text("""
        SELECT id, log_date, symbol, entry_price, stop_loss, target_price,
               max_price_reached, min_price_reached
        FROM sip_suggestion_log WHERE status = 'OPEN'
    """)).fetchall()

    if not open_rows:
        return 0

    updated = 0
    for row in open_rows:
        rid, log_date_str, symbol, entry_price, stop_loss, target_price, max_p, min_p = row

        price_row = session.execute(text(
            "SELECT close FROM daily_prices WHERE symbol=:sym ORDER BY date DESC LIMIT 1"
        ), {"sym": symbol}).first()
        if not price_row or price_row[0] is None:
            continue

        curr_p       = float(price_row[0])
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

        if exit_price and entry_price > 0:
            realized_gain_pct = round((exit_price - entry_price) / entry_price * 100.0, 2)

        session.execute(text("""
            UPDATE sip_suggestion_log SET
                max_price_reached=:max_p, min_price_reached=:min_p,
                status=:status, exit_date=:exit_date, exit_price=:exit_price,
                realized_gain_pct=:realized_gain_pct, days_held=:days_held,
                verified_date=:verified_date
            WHERE id=:rid
        """), {
            "max_p": round(new_max, 2), "min_p": round(new_min, 2),
            "status": new_status, "exit_date": exit_date,
            "exit_price": round(exit_price, 2) if exit_price else None,
            "realized_gain_pct": realized_gain_pct, "days_held": days_held,
            "verified_date": today_str, "rid": rid,
        })
        if new_status != "OPEN":
            updated += 1

    session.commit()
    logger.info(f"SIP tracker: {updated}/{len(open_rows)} positions updated.")
    return updated


def get_sip_accuracy_report(session: Session, months: int = 12) -> Dict:
    """
    Aggregate SIP suggestion outcomes for the trailing N months.
    Returns summary metrics dict + full DataFrame.
    """
    init_sip_log_table(session)
    since_date = (date.today() - timedelta(days=months * 30)).isoformat()

    rows = session.execute(text("""
        SELECT symbol, name, sector, tier, log_date, month_label, strategy,
               entry_price, stop_loss, target_price, composite_score, momentum_6m_pct,
               status, exit_date, exit_price, realized_gain_pct, days_held,
               max_price_reached, min_price_reached, shares_suggested, total_cost
        FROM sip_suggestion_log WHERE log_date >= :since
        ORDER BY log_date DESC, symbol
    """), {"since": since_date}).fetchall()

    cols = ["symbol","name","sector","tier","log_date","month_label","strategy",
            "entry_price","stop_loss","target_price","composite_score","momentum_6m_pct",
            "status","exit_date","exit_price","realized_gain_pct","days_held",
            "max_price_reached","min_price_reached","shares_suggested","total_cost"]
    df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)

    _empty = {"total_suggestions":0,"win_rate_pct":0.0,"profit_factor":0.0,
              "avg_winner_gain_pct":0.0,"avg_loser_loss_pct":0.0,"live_xirr_pct":0.0,
              "open_count":0,"t1_count":0,"sl_count":0,"trailing_sl_count":0,
              "expired_count":0,"df":df}
    if df.empty:
        return _empty

    df["realized_gain_pct"] = pd.to_numeric(df["realized_gain_pct"], errors="coerce")
    df["entry_price"]       = pd.to_numeric(df["entry_price"],       errors="coerce")
    df["exit_price"]        = pd.to_numeric(df["exit_price"],        errors="coerce")
    df["total_cost"]        = pd.to_numeric(df["total_cost"],        errors="coerce").fillna(0.0)

    closed  = df[df["status"] != "OPEN"]
    winners = closed[closed["realized_gain_pct"] > 0]
    losers  = closed[closed["realized_gain_pct"] <= 0]

    win_rate_pct = round(len(winners) / max(1, len(closed)) * 100.0, 1) if len(closed) > 0 else 0.0
    gross_gain   = winners["realized_gain_pct"].sum() if len(winners) > 0 else 0.0
    gross_loss   = abs(losers["realized_gain_pct"].sum()) if len(losers) > 0 else 0.0
    pf           = round(gross_gain / max(0.01, gross_loss), 2)
    avg_win      = round(winners["realized_gain_pct"].mean(), 2) if len(winners) > 0 else 0.0
    avg_loss     = round(losers["realized_gain_pct"].mean(), 2)  if len(losers) > 0 else 0.0
    live_xirr    = _compute_live_xirr(df)

    open_mask = df["status"] == "OPEN"
    if open_mask.any():
        curr_prices = {}
        for sym in df.loc[open_mask, "symbol"].unique():
            pr = session.execute(text(
                "SELECT close FROM daily_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"
            ), {"s": sym}).first()
            curr_prices[sym] = float(pr[0]) if pr and pr[0] else None

        def _unreal(r):
            cp, ep = curr_prices.get(r["symbol"]), r["entry_price"]
            return round((cp - ep) / ep * 100.0, 2) if cp and ep and ep > 0 else None
        df.loc[open_mask, "unrealized_gain_pct"] = df.loc[open_mask].apply(_unreal, axis=1)

    return {
        "total_suggestions": len(df), "win_rate_pct": win_rate_pct,
        "profit_factor": pf, "avg_winner_gain_pct": avg_win,
        "avg_loser_loss_pct": avg_loss, "live_xirr_pct": live_xirr,
        "open_count": int(open_mask.sum()),
        "t1_count": int(df["status"].isin(["T1_HIT","TRAILING_SL_HIT"]).sum()),
        "sl_count": int((df["status"] == "SL_HIT").sum()),
        "trailing_sl_count": int((df["status"] == "TRAILING_SL_HIT").sum()),
        "expired_count": int((df["status"] == "EXPIRED").sum()),
        "df": df,
    }


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
