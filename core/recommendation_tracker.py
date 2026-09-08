"""
core/recommendation_tracker.py
Active Recommendation Mandate & Daily Shift Tracker Engine
- Bridges the gap between static watchlists and real-time algorithmic portfolio following.
- Allows 1-click tracking of any recommended basket as a live "Active Mandate".
- Performs real-time surveillance: Target 1 / Target 2 profit-booking alerts, dynamic trailing stops, and stop-loss triggers.
- Computes daily recommendation deltas ("What Changed Today?"): New Entrants, Dropped / Rotated Assets, Status Shifts, and Retained Compounders.
- Maintains a chronological Recommendation Shift Audit Journal.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

_CREATE_MANDATES_TABLE = """
CREATE TABLE IF NOT EXISTS tracked_recommendation_mandates (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL,
    strategy           TEXT NOT NULL,
    source             TEXT DEFAULT 'Monthly SIP Planner',
    inception_date     TEXT NOT NULL,
    last_evaluated     TEXT,
    monthly_outlay     REAL DEFAULT 20000.0,
    status             TEXT DEFAULT 'ACTIVE',
    notes              TEXT,
    created_at         TEXT
);
"""

_CREATE_MANDATE_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS tracked_mandate_items (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    mandate_id         INTEGER NOT NULL,
    symbol             TEXT NOT NULL,
    name               TEXT,
    asset_class        TEXT DEFAULT 'Stock',
    sector             TEXT,
    recommended_qty    INTEGER DEFAULT 1,
    entry_price        REAL NOT NULL,
    entry_score        REAL,
    entry_signal       TEXT,
    entry_consensus    TEXT,
    stop_loss          REAL,
    target_1           REAL,
    target_2           REAL,
    peak_price         REAL,
    trailing_stop      REAL,
    current_status     TEXT DEFAULT 'HOLDING',
    notes              TEXT,
    FOREIGN KEY(mandate_id) REFERENCES tracked_recommendation_mandates(id) ON DELETE CASCADE
);
"""

_CREATE_SHIFT_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS recommendation_shift_events (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date         TEXT NOT NULL,
    mandate_id         INTEGER,
    strategy           TEXT,
    symbol             TEXT NOT NULL,
    name               TEXT,
    event_type         TEXT NOT NULL,
    headline           TEXT NOT NULL,
    reason             TEXT,
    action_instruction TEXT NOT NULL,
    severity           TEXT DEFAULT 'INFO'
);
"""


def init_recommendation_tracker_tables(session: Session) -> None:
    """Initialize all tables needed for recommendation tracking and shift logs."""
    session.execute(text(_CREATE_MANDATES_TABLE))
    session.execute(text(_CREATE_MANDATE_ITEMS_TABLE))
    session.execute(text(_CREATE_SHIFT_EVENTS_TABLE))
    session.commit()


def save_active_recommendation_mandate(
    session: Session,
    name: str,
    strategy: str,
    assets: List[Dict],
    source: str = "Monthly SIP Planner",
    monthly_outlay: float = 20000.0,
    notes: str = ""
) -> int:
    """
    Save the given recommendation basket as an active tracked mandate.
    Returns the newly created mandate_id.
    """
    init_recommendation_tracker_tables(session)
    today_str = date.today().isoformat()
    now_str = datetime.now().isoformat()

    res = session.execute(text("""
        INSERT INTO tracked_recommendation_mandates
            (name, strategy, source, inception_date, last_evaluated, monthly_outlay, status, notes, created_at)
        VALUES
            (:name, :strategy, :source, :inception_date, :last_evaluated, :monthly_outlay, 'ACTIVE', :notes, :created_at)
    """), {
        "name": name.strip(),
        "strategy": strategy,
        "source": source,
        "inception_date": today_str,
        "last_evaluated": today_str,
        "monthly_outlay": float(monthly_outlay),
        "notes": notes,
        "created_at": now_str
    })
    mandate_id = res.lastrowid

    for asset in assets:
        sym = str(asset.get("symbol", "")).strip()
        if not sym:
            continue
        
        ep = float(asset.get("current_price", 0.0) or asset.get("price", 0.0) or asset.get("nav", 0.0))
        if ep <= 0:
            ep = _lookup_asset_price(session, sym, asset.get("asset_class", "Stock"))

        qty = int(asset.get("shares_to_buy", 1) or asset.get("qty", 1) or 1)
        sl = float(asset.get("stop_loss", 0.0)) if asset.get("stop_loss") else round(ep * 0.86, 2)
        t1 = float(asset.get("target_price", 0.0) or asset.get("target_price_1", 0.0)) if (asset.get("target_price") or asset.get("target_price_1")) else round(ep * 1.15, 2)
        t2 = round(ep * 1.30, 2)

        session.execute(text("""
            INSERT INTO tracked_mandate_items
                (mandate_id, symbol, name, asset_class, sector, recommended_qty,
                 entry_price, entry_score, entry_signal, entry_consensus,
                 stop_loss, target_1, target_2, peak_price, trailing_stop, current_status, notes)
            VALUES
                (:mid, :sym, :name, :ac, :sec, :qty,
                 :ep, :score, :sig, :cons,
                 :sl, :t1, :t2, :peak, :tsl, 'HOLDING', :notes)
        """), {
            "mid": mandate_id,
            "sym": sym,
            "name": asset.get("name", sym),
            "ac": asset.get("asset_class", "Stock"),
            "sec": asset.get("sector", "General"),
            "qty": qty,
            "ep": ep,
            "score": float(asset.get("composite_score", 65.0) or 65.0),
            "sig": asset.get("signal", "BUY"),
            "cons": asset.get("consensus_label") or asset.get("street_consensus") or "Hold",
            "sl": sl,
            "t1": t1,
            "t2": t2,
            "peak": ep,
            "tsl": sl,
            "notes": f"Inception recommendation on {today_str}"
        })

        # Log event into shift log
        session.execute(text("""
            INSERT INTO recommendation_shift_events
                (event_date, mandate_id, strategy, symbol, name, event_type, headline, reason, action_instruction, severity)
            VALUES
                (:ed, :mid, :strat, :sym, :name, 'NEW_ENTRY', :hl, :reason, :act, 'INFO')
        """), {
            "ed": today_str,
            "mid": mandate_id,
            "strat": strategy,
            "sym": sym,
            "name": asset.get("name", sym),
            "hl": f"🆕 {sym} added to active mandate '{name}'",
            "reason": f"Recommended by {strategy} model @ ₹{ep:,.2f} with Target ₹{t1:,.2f} and SL ₹{sl:,.2f}",
            "act": f"Execute purchase of {qty} share(s) @ ~₹{ep:,.2f} (Total: ₹{ep * qty:,.2f})"
        })

    session.commit()

    # Also sync into sip_suggestion_log for backward-compatible audit tracker
    try:
        from core.sip_tracker import log_sip_basket
        log_sip_basket(
            session,
            basket={"assets": assets, "total_spent": monthly_outlay},
            strategy=strategy,
            exit_protocol="ADAPTIVE_STRUCTURAL"
        )
    except Exception as e:
        logger.warning(f"Could not auto-sync into sip_suggestion_log: {e}")

    logger.info(f"Saved active recommendation mandate #{mandate_id} '{name}' with {len(assets)} assets.")
    return mandate_id


def get_tracked_mandates(session: Session, status: Optional[str] = "ACTIVE") -> List[Dict]:
    """Retrieve all tracked recommendation mandates with item counts and overview stats."""
    init_recommendation_tracker_tables(session)
    q = "SELECT id, name, strategy, source, inception_date, last_evaluated, monthly_outlay, status, notes FROM tracked_recommendation_mandates"
    params = {}
    if status and status != "ALL":
        q += " WHERE status = :status"
        params["status"] = status
    q += " ORDER BY id DESC"

    rows = session.execute(text(q), params).fetchall()
    mandates = []
    for r in rows:
        mid, name, strat, src, incept, last_eval, outlay, stat, notes = r
        cnt = session.execute(text("SELECT COUNT(*) FROM tracked_mandate_items WHERE mandate_id = :mid"), {"mid": mid}).scalar() or 0
        mandates.append({
            "id": mid,
            "name": name,
            "strategy": strat,
            "source": src,
            "inception_date": incept,
            "last_evaluated": last_eval,
            "monthly_outlay": outlay,
            "status": stat,
            "notes": notes,
            "item_count": cnt
        })
    return mandates


def evaluate_mandate_live_status(session: Session, mandate_id: int) -> Dict:
    """
    Perform deep real-time surveillance on an active tracked mandate:
    - Fetches current live prices across stocks, indexes, commodities, and mutual funds.
    - Computes live unrealized P&L, peak price, and dynamic trailing stop.
    - Evaluates action triggers: RIDE TREND, TRIM 30%, TARGET 2 HIT, or STOP LOSS EXIT.
    - Compares portfolio performance against NIFTY 50 benchmark.
    - Generates concrete daily action checklist.
    """
    init_recommendation_tracker_tables(session)
    today_str = date.today().isoformat()

    mandate_row = session.execute(text("""
        SELECT id, name, strategy, source, inception_date, monthly_outlay, status, notes
        FROM tracked_recommendation_mandates WHERE id = :mid
    """), {"mid": mandate_id}).fetchone()

    if not mandate_row:
        return {"error": f"Mandate #{mandate_id} not found."}

    mid, name, strategy, source, incept_date, monthly_outlay, status, notes = mandate_row

    items_rows = session.execute(text("""
        SELECT id, symbol, name, asset_class, sector, recommended_qty, entry_price,
               entry_score, entry_signal, entry_consensus, stop_loss, target_1, target_2,
               peak_price, trailing_stop, current_status, notes
        FROM tracked_mandate_items WHERE mandate_id = :mid
    """), {"mid": mandate_id}).fetchall()

    items = []
    total_invested = 0.0
    current_portfolio_value = 0.0
    action_items = []

    # Get latest NIFTY 50 return since inception for benchmark alpha
    nifty_bench_return = _get_nifty_benchmark_return(session, incept_date)

    for it in items_rows:
        (item_id, sym, item_name, ac, sec, qty, ep, score, sig, cons,
         sl, t1, t2, peak_p, tsl, curr_stat, it_notes) = it

        qty = max(1, int(qty or 1))
        ep = float(ep or 0.0)
        curr_p = _lookup_asset_price(session, sym, ac) or ep
        curr_p = float(curr_p)

        invested_amt = ep * qty
        current_amt = curr_p * qty
        total_invested += invested_amt
        current_portfolio_value += current_amt

        pnl_inr = current_amt - invested_amt
        pnl_pct = round((curr_p - ep) / ep * 100.0, 2) if ep > 0 else 0.0

        # High watermark & dynamic trailing stop calculation
        peak_p = max(float(peak_p or ep), curr_p)
        
        # Adaptive Trailing Shield:
        # If gain >= 15%, lock breakeven at entry_price
        # If gain >= 25%, lock trailing stop at peak_p - 10%
        # If gain >= 40%, lock trailing stop at peak_p - 12%
        calc_tsl = float(tsl or sl or ep * 0.86)
        if pnl_pct >= 40.0:
            calc_tsl = max(calc_tsl, round(peak_p * 0.88, 2))
        elif pnl_pct >= 25.0:
            calc_tsl = max(calc_tsl, round(peak_p * 0.90, 2))
        elif pnl_pct >= 15.0:
            calc_tsl = max(calc_tsl, round(ep * 1.02, 2))  # Lock in breakeven + minor buffer

        # Check Action Triggers
        action_code = "RIDE"
        action_badge = "🟢 Ride Trend"
        action_text = f"Holding smoothly. Current price is ₹{curr_p:,.2f} ({pnl_pct:+.1f}%)."
        severity = "INFO"

        if sl and curr_p <= sl:
            action_code = "STOP_LOSS"
            action_badge = "🔴 Stop Loss Hit"
            action_text = f"Price breached stop loss ₹{sl:,.2f}. Recommend capital preservation exit."
            severity = "CRITICAL"
        elif calc_tsl and curr_p <= calc_tsl and pnl_pct > 5.0:
            action_code = "TRAILING_STOP"
            action_badge = "🛑 Trailing Stop Hit"
            action_text = f"Price breached trailing stop ₹{calc_tsl:,.2f}. Protect accumulated gains of {pnl_pct:+.1f}%."
            severity = "WARNING"
        elif t2 and curr_p >= t2:
            action_code = "TARGET_2"
            action_badge = "🚀 Target 2 Reached"
            action_text = f"Supercharged gain (+{pnl_pct:.1f}%)! Book 50% profits, trail remaining {max(1, qty // 2)} shares."
            severity = "SUCCESS"
        elif t1 and curr_p >= t1:
            action_code = "TARGET_1"
            action_badge = "🟡 Target 1 Hit"
            action_text = f"Target 1 (₹{t1:,.2f}) reached (+{pnl_pct:.1f}%). Book 30% partial profit, lock trailing stop."
            severity = "SUCCESS"

        # Update DB if peak or trailing stop changed
        session.execute(text("""
            UPDATE tracked_mandate_items
            SET peak_price = :peak, trailing_stop = :tsl, current_status = :stat
            WHERE id = :id
        """), {"peak": peak_p, "tsl": calc_tsl, "stat": action_code, "id": item_id})

        # Add to action items if actionable
        if action_code != "RIDE":
            action_items.append({
                "symbol": sym,
                "name": item_name,
                "action_code": action_code,
                "action_badge": action_badge,
                "current_price": curr_p,
                "pnl_pct": pnl_pct,
                "instruction": action_text,
                "severity": severity
            })

        dist_t1_pct = round((t1 - curr_p) / curr_p * 100.0, 1) if (t1 and curr_p > 0) else None
        dist_sl_pct = round((curr_p - sl) / curr_p * 100.0, 1) if (sl and curr_p > 0) else None

        items.append({
            "id": item_id,
            "symbol": sym,
            "name": item_name,
            "asset_class": ac,
            "sector": sec,
            "recommended_qty": qty,
            "entry_price": ep,
            "current_price": curr_p,
            "invested_amt": invested_amt,
            "current_amt": current_amt,
            "pnl_inr": round(pnl_inr, 2),
            "pnl_pct": pnl_pct,
            "peak_price": peak_p,
            "stop_loss": sl,
            "trailing_stop": calc_tsl,
            "target_1": t1,
            "target_2": t2,
            "dist_t1_pct": dist_t1_pct,
            "dist_sl_pct": dist_sl_pct,
            "entry_score": score,
            "entry_signal": sig,
            "entry_consensus": cons,
            "action_code": action_code,
            "action_badge": action_badge,
            "action_text": action_text,
            "severity": severity
        })

    # Update mandate last_evaluated
    session.execute(text("""
        UPDATE tracked_recommendation_mandates SET last_evaluated = :today WHERE id = :mid
    """), {"today": today_str, "mid": mandate_id})
    session.commit()

    total_pnl_inr = current_portfolio_value - total_invested
    total_pnl_pct = round((total_pnl_inr / max(1.0, total_invested)) * 100.0, 2)
    alpha_pct = round(total_pnl_pct - nifty_bench_return, 2)

    return {
        "mandate_id": mandate_id,
        "name": name,
        "strategy": strategy,
        "source": source,
        "inception_date": incept_date,
        "monthly_outlay": monthly_outlay,
        "status": status,
        "total_invested": round(total_invested, 2),
        "current_value": round(current_portfolio_value, 2),
        "total_pnl_inr": round(total_pnl_inr, 2),
        "total_pnl_pct": total_pnl_pct,
        "benchmark_return_pct": nifty_bench_return,
        "alpha_pct": alpha_pct,
        "items": items,
        "action_items": action_items,
        "total_items": len(items)
    }


def compute_daily_recommendation_shifts(
    session: Session,
    current_basket_assets: List[Dict],
    strategy: str = "MULTI_ASSET"
) -> Dict:
    """
    Compare today's freshly generated recommendation basket against the most recent
    previous recommendation snapshot in `sip_suggestion_log` or `tracked_mandate_items`.
    
    Returns:
      - new_additions: List of newly recommended assets entering today.
      - dropped_assets: List of assets from previous run that fell out of the basket.
      - retained_assets: Assets recommended in both periods, with any score/target/signal shifts.
      - actionable_summary: Plain English instructions on what action to take today.
      - is_identical: True if basket is unchanged.
    """
    today_str = date.today().isoformat()
    init_recommendation_tracker_tables(session)

    # 1. Fetch prior recommended basket from sip_suggestion_log (prior to today)
    prior_rows = session.execute(text("""
        SELECT symbol, name, asset_class, sector, entry_price, composite_score, signal, stop_loss, target_price
        FROM sip_suggestion_log
        WHERE strategy = :strat AND log_date < :today
        ORDER BY log_date DESC, id DESC
    """), {"strat": strategy, "today": today_str}).fetchall()

    prior_dict = {}
    if prior_rows:
        # Get the latest log_date available
        latest_prior_date = session.execute(text("""
            SELECT MAX(log_date) FROM sip_suggestion_log WHERE strategy = :strat AND log_date < :today
        """), {"strat": strategy, "today": today_str}).scalar()

        if latest_prior_date:
            specific_prior_rows = session.execute(text("""
                SELECT symbol, name, asset_class, sector, entry_price, composite_score, signal, stop_loss, target_price
                FROM sip_suggestion_log
                WHERE strategy = :strat AND log_date = :ld
            """), {"strat": strategy, "ld": latest_prior_date}).fetchall()
            for pr in specific_prior_rows:
                prior_dict[pr[0]] = {
                    "symbol": pr[0], "name": pr[1], "asset_class": pr[2],
                    "sector": pr[3], "entry_price": pr[4], "composite_score": pr[5],
                    "signal": pr[6], "stop_loss": pr[7], "target_price": pr[8],
                    "as_of_date": latest_prior_date
                }

    current_dict = {}
    for a in current_basket_assets:
        sym = str(a.get("symbol", "")).strip()
        if sym:
            current_dict[sym] = a

    new_additions = []
    dropped_assets = []
    retained_assets = []

    # Check new additions & retained
    for sym, curr in current_dict.items():
        if sym not in prior_dict:
            new_additions.append({
                "symbol": sym,
                "name": curr.get("name", sym),
                "asset_class": curr.get("asset_class", "Stock"),
                "sector": curr.get("sector", "General"),
                "current_price": curr.get("current_price", 0.0),
                "composite_score": curr.get("composite_score", 65.0),
                "signal": curr.get("signal", "BUY"),
                "target_price": curr.get("target_price") or curr.get("target_price_1"),
                "stop_loss": curr.get("stop_loss"),
                "reason": f"Fresh quantitative alpha entry with high momentum score ({curr.get('composite_score', 65.0):.0f}/100)"
            })
        else:
            p_item = prior_dict[sym]
            score_diff = round(float(curr.get("composite_score", 0.0)) - float(p_item.get("composite_score", 0.0)), 1)
            sig_changed = curr.get("signal") != p_item.get("signal")
            retained_assets.append({
                "symbol": sym,
                "name": curr.get("name", sym),
                "asset_class": curr.get("asset_class", "Stock"),
                "sector": curr.get("sector", "General"),
                "current_price": curr.get("current_price", 0.0),
                "composite_score": curr.get("composite_score", 0.0),
                "prior_score": p_item.get("composite_score", 0.0),
                "score_diff": score_diff,
                "signal": curr.get("signal"),
                "prior_signal": p_item.get("signal"),
                "signal_changed": sig_changed,
                "target_price": curr.get("target_price") or curr.get("target_price_1"),
                "stop_loss": curr.get("stop_loss")
            })

    # Check dropped assets
    for sym, prior in prior_dict.items():
        if sym not in current_dict:
            dropped_assets.append({
                "symbol": sym,
                "name": prior.get("name", sym),
                "asset_class": prior.get("asset_class", "Stock"),
                "sector": prior.get("sector", "General"),
                "prior_score": prior.get("composite_score"),
                "prior_signal": prior.get("signal"),
                "prior_date": prior.get("as_of_date"),
                "reason": "Relative momentum decay or displaced by a higher-ranking peer in the sector"
            })

    is_identical = (len(new_additions) == 0 and len(dropped_assets) == 0)

    # Generate actionable recommendation guidance
    if is_identical:
        action_summary = "🛡️ High Basket Stability: No changes detected since yesterday. All recommended positions maintain optimal risk/reward. Continue your existing SIP allocation smoothly!"
    else:
        parts = []
        if new_additions:
            add_names = ", ".join([x["symbol"] for x in new_additions])
            parts.append(f"• 🆕 New Entries: Consider allocating fresh capital to {add_names}.")
        if dropped_assets:
            drop_names = ", ".join([x["symbol"] for x in dropped_assets])
            parts.append(f"• 🔄 Rotated Out: {drop_names} dropped from top picks. If holding, raise trailing stop or let profit ride with a tight leash; avoid adding fresh monthly capital.")
        if retained_assets:
            retained_names = ", ".join([x["symbol"] for x in retained_assets])
            parts.append(f"• 🔒 Core Compounders: Maintain active positions in {retained_names}.")
        action_summary = "\n".join(parts)

    return {
        "is_identical": is_identical,
        "new_additions": new_additions,
        "dropped_assets": dropped_assets,
        "retained_assets": retained_assets,
        "action_summary": action_summary,
        "prior_snapshot_date": latest_prior_date if prior_rows else None
    }


def get_recommendation_shift_timeline(
    session: Session,
    mandate_id: Optional[int] = None,
    limit: int = 30
) -> List[Dict]:
    """Retrieve chronological recommendation shift & milestone events."""
    init_recommendation_tracker_tables(session)
    q = "SELECT id, event_date, mandate_id, strategy, symbol, name, event_type, headline, reason, action_instruction, severity FROM recommendation_shift_events"
    params = {"lim": limit}
    if mandate_id:
        q += " WHERE mandate_id = :mid"
        params["mid"] = mandate_id
    q += " ORDER BY event_date DESC, id DESC LIMIT :lim"

    rows = session.execute(text(q), params).fetchall()
    events = []
    for r in rows:
        events.append({
            "id": r[0],
            "event_date": r[1],
            "mandate_id": r[2],
            "strategy": r[3],
            "symbol": r[4],
            "name": r[5],
            "event_type": r[6],
            "headline": r[7],
            "reason": r[8],
            "action_instruction": r[9],
            "severity": r[10]
        })
    return events


def delete_or_retire_mandate(session: Session, mandate_id: int, action: str = "DELETE") -> bool:
    """Delete or retire a tracked mandate."""
    init_recommendation_tracker_tables(session)
    if action == "RETIRE":
        session.execute(text("UPDATE tracked_recommendation_mandates SET status = 'RETIRED' WHERE id = :mid"), {"mid": mandate_id})
    else:
        session.execute(text("DELETE FROM tracked_mandate_items WHERE mandate_id = :mid"), {"mid": mandate_id})
        session.execute(text("DELETE FROM tracked_recommendation_mandates WHERE id = :mid"), {"mid": mandate_id})
    session.commit()
    return True


# ── Internal Helpers ──────────────────────────────────────────────────────────

def _lookup_asset_price(session: Session, symbol: str, asset_class: str) -> float:
    """Safely fetch latest price/NAV from DB."""
    try:
        if asset_class in ("Mutual Fund", "MF") or str(symbol).isdigit():
            p = session.execute(text("SELECT nav FROM mutual_fund_navs WHERE scheme_code=:s ORDER BY date DESC LIMIT 1"), {"s": symbol}).scalar()
        elif asset_class in ("Index / ETF", "Index") or symbol.startswith("^"):
            p = session.execute(text("SELECT close FROM index_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"), {"s": symbol}).scalar()
        elif asset_class == "Commodity" or any(c in symbol.upper() for c in ["GOLD", "SILVER", "CRUDE", "COPPER"]):
            p = session.execute(text("SELECT close FROM commodity_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"), {"s": symbol}).scalar()
        else:
            p = session.execute(text("SELECT close FROM daily_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"), {"s": symbol}).scalar()
        return float(p) if p else 0.0
    except Exception:
        return 0.0


def _get_nifty_benchmark_return(session: Session, since_date: str) -> float:
    """Compute NIFTY 50 return since inception date."""
    try:
        p_latest = session.execute(text("SELECT close FROM index_prices WHERE symbol = '^NSEI' ORDER BY date DESC LIMIT 1")).scalar()
        p_start = session.execute(text("SELECT close FROM index_prices WHERE symbol = '^NSEI' AND date <= :d ORDER BY date DESC LIMIT 1"), {"d": since_date}).scalar()
        if p_latest and p_start and float(p_start) > 0:
            return round((float(p_latest) - float(p_start)) / float(p_start) * 100.0, 2)
        return 0.0
    except Exception:
        return 0.0
