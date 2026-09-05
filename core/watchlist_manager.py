"""
Watchlist & 52-Week High/Low Proximity Radar Engine
- Multi-watchlist management with targets, stop-losses, and personal notes
- Real-time 52-Week High / Low breakout & breakdown radar
- Automated price alert trigger and notification dispatcher
"""
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

import importlib
import db.database
if not hasattr(db.database, "Watchlist"):
    importlib.reload(db.database)
from db.database import Watchlist, WatchlistItem, PriceAlert, Stock, DailyPrice

logger = logging.getLogger(__name__)


# ─── 1. Watchlist Management CRUD ─────────────────────────────────────────────
def get_all_watchlists(session: Session) -> List[Dict]:
    """Retrieve all user watchlists with item counts."""
    watchlists = session.query(Watchlist).all()
    if not watchlists:
        # Seed default watchlist if none exists
        default_wl = Watchlist(name="Primary Focus", description="Core high-conviction holdings & targets")
        session.add(default_wl)
        session.commit()
        # Add a few default bluechips
        for sym in ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]:
            stock_exists = session.query(Stock).filter(Stock.symbol == sym).first()
            if stock_exists:
                session.add(WatchlistItem(watchlist_id=default_wl.id, symbol=sym, notes="Nifty Bluechip core"))
        session.commit()
        watchlists = session.query(Watchlist).all()

    results = []
    for wl in watchlists:
        results.append({
            "id": wl.id,
            "name": wl.name,
            "description": wl.description or "",
            "item_count": len(wl.items),
            "created_at": wl.created_at,
        })
    return results


def create_watchlist(name: str, description: str, session: Session) -> Optional[int]:
    """Create a new custom watchlist."""
    try:
        wl = Watchlist(name=name.strip(), description=description.strip())
        session.add(wl)
        session.commit()
        return wl.id
    except Exception as e:
        session.rollback()
        logger.error(f"Error creating watchlist {name}: {e}")
        return None


def delete_watchlist(watchlist_id: int, session: Session) -> bool:
    """Delete a watchlist and all associated items."""
    try:
        wl = session.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
        if wl:
            session.delete(wl)
            session.commit()
            return True
        return False
    except Exception as e:
        session.rollback()
        logger.error(f"Error deleting watchlist {watchlist_id}: {e}")
        return False


def get_watchlist_items(watchlist_id: int, session: Session) -> List[Dict]:
    """Get all items in a watchlist with current prices, changes, and signals."""
    rows = session.execute(text("""
        SELECT
            wi.id, wi.symbol, s.name, s.sector, s.market_cap_tier,
            wi.target_buy_price, wi.target_sell_price, wi.stop_loss, wi.notes, wi.added_at,
            dp.close, dp.daily_return,
            sig.signal, sig.signal_strength, sig.risk_level, sig.risk_reward_ratio,
            cs.composite_score
        FROM watchlist_items wi
        JOIN stocks s ON wi.symbol = s.symbol
        LEFT JOIN (
            SELECT symbol, close, daily_return
            FROM daily_prices
            WHERE date = (SELECT MAX(date) FROM daily_prices)
        ) dp ON wi.symbol = dp.symbol
        LEFT JOIN (
            SELECT symbol, signal, signal_strength, risk_level, risk_reward_ratio
            FROM signals
            WHERE date = (SELECT MAX(date) FROM signals)
        ) sig ON wi.symbol = sig.symbol
        LEFT JOIN (
            SELECT symbol, composite_score
            FROM composite_scores
            WHERE date = (SELECT MAX(date) FROM composite_scores)
        ) cs ON wi.symbol = cs.symbol
        WHERE wi.watchlist_id = :w_id
        ORDER BY wi.added_at DESC
    """), {"w_id": watchlist_id}).fetchall()

    items = []
    for r in rows:
        close = r[10] or 0.0
        target_buy = r[5]
        target_sell = r[6]
        stop_loss = r[7]

        # Calculate distance to targets
        dist_to_buy = round((close - target_buy) / target_buy * 100, 2) if target_buy and target_buy > 0 and close else None
        dist_to_sell = round((target_sell - close) / close * 100, 2) if target_sell and target_sell > 0 and close else None
        dist_to_sl = round((stop_loss - close) / close * 100, 2) if stop_loss and stop_loss > 0 and close else None

        items.append({
            "item_id": r[0],
            "symbol": r[1],
            "name": r[2],
            "sector": r[3],
            "market_cap_tier": r[4] or "Large",
            "target_buy_price": target_buy,
            "target_sell_price": target_sell,
            "stop_loss": stop_loss,
            "notes": r[8] or "",
            "added_at": r[9],
            "current_price": close,
            "daily_return": round(r[11] or 0.0, 2),
            "signal": r[12] or "WATCH",
            "signal_strength": r[13] or "MODERATE",
            "risk_level": r[14] or "MODERATE",
            "risk_reward_ratio": r[15],
            "composite_score": round(r[16] or 50.0, 1),
            "dist_to_buy_pct": dist_to_buy,
            "dist_to_sell_pct": dist_to_sell,
            "dist_to_sl_pct": dist_to_sl,
        })
    return items


def add_item_to_watchlist(
    watchlist_id: int,
    symbol: str,
    target_buy_price: Optional[float],
    target_sell_price: Optional[float],
    stop_loss: Optional[float],
    notes: Optional[str],
    session: Session,
) -> bool:
    """Add a stock to a watchlist with custom parameters."""
    try:
        item = session.query(WatchlistItem).filter(
            WatchlistItem.watchlist_id == watchlist_id,
            WatchlistItem.symbol == symbol.strip().upper()
        ).first()

        if item:
            item.target_buy_price = target_buy_price
            item.target_sell_price = target_sell_price
            item.stop_loss = stop_loss
            item.notes = notes
        else:
            item = WatchlistItem(
                watchlist_id=watchlist_id,
                symbol=symbol.strip().upper(),
                target_buy_price=target_buy_price,
                target_sell_price=target_sell_price,
                stop_loss=stop_loss,
                notes=notes,
            )
            session.add(item)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error adding {symbol} to watchlist {watchlist_id}: {e}")
        return False


def remove_item_from_watchlist(item_id: int, session: Session) -> bool:
    """Remove an item from a watchlist."""
    try:
        item = session.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
        if item:
            session.delete(item)
            session.commit()
            return True
        return False
    except Exception as e:
        session.rollback()
        logger.error(f"Error removing item {item_id}: {e}")
        return False


# ─── 2. 52-Week High & Low Proximity Radar ───────────────────────────────────
def get_52_week_high_low_radar(session: Session, lookback_days: int = 252) -> Dict[str, List[Dict]]:
    """
    Computes 52-week High and Low for all stocks and buckets them by breakout proximity.
    """
    query = f"""
        WITH stats_52w AS (
            SELECT
                symbol,
                MAX(high) as high_52w,
                MIN(low) as low_52w,
                AVG(volume) as avg_vol_52w
            FROM daily_prices
            WHERE date >= date((SELECT MAX(date) FROM daily_prices), '-365 days')
            GROUP BY symbol
        ),
        latest_prices AS (
            SELECT dp.symbol, dp.close, dp.high, dp.low, dp.daily_return, dp.volume, dp.date
            FROM daily_prices dp
            JOIN (
                SELECT symbol, MAX(date) as max_d
                FROM daily_prices
                GROUP BY symbol
            ) lm ON dp.symbol = lm.symbol AND dp.date = lm.max_d
        )
        SELECT
            s.symbol, s.name, s.sector, s.market_cap_tier,
            lp.close, lp.daily_return, lp.volume,
            st.high_52w, st.low_52w, st.avg_vol_52w,
            ROUND((lp.close - st.high_52w) / st.high_52w * 100.0, 2) as dist_52w_high_pct,
            ROUND((lp.close - st.low_52w) / st.low_52w * 100.0, 2) as dist_52w_low_pct,
            sig.signal, cs.composite_score
        FROM latest_prices lp
        JOIN stats_52w st ON lp.symbol = st.symbol
        JOIN stocks s ON lp.symbol = s.symbol
        LEFT JOIN signals sig ON s.symbol = sig.symbol AND sig.date = lp.date
        LEFT JOIN composite_scores cs ON s.symbol = cs.symbol AND cs.date = lp.date
        WHERE s.is_active = 1 AND st.high_52w > 0 AND st.low_52w > 0
    """
    rows = session.execute(text(query)).fetchall()

    near_52w_high = []       # Within 3% of 52W High
    breakout_52w_high = []   # New 52W High (within 0.5% or above)
    near_52w_low = []        # Within 3% of 52W Low (potential oversold / bargain)
    breakdown_52w_low = []   # New 52W Low (within 0.5% or below)
    all_radar = []

    for r in rows:
        symbol = r[0]
        name = r[1]
        sector = r[2]
        tier = r[3] or "Mid"
        close = r[4] or 0.0
        d_ret = r[5] or 0.0
        vol = r[6] or 0.0
        h52 = r[7] or 0.0
        l52 = r[8] or 0.0
        dist_high = r[10] or 0.0
        dist_low = r[11] or 0.0
        signal = r[12] or "WATCH"
        score = round(r[13] or 50.0, 1)

        item = {
            "symbol": symbol, "name": name, "sector": sector, "tier": tier,
            "current_price": close, "daily_return": d_ret,
            "high_52w": h52, "low_52w": l52,
            "dist_52w_high_pct": dist_high,
            "dist_52w_low_pct": dist_low,
            "signal": signal, "composite_score": score,
        }

        all_radar.append(item)

        if dist_high >= -0.75:
            breakout_52w_high.append(item)
        elif dist_high >= -3.5:
            near_52w_high.append(item)

        if dist_low <= 0.75:
            breakdown_52w_low.append(item)
        elif dist_low <= 3.5:
            near_52w_low.append(item)

    # Sort each category logically
    breakout_52w_high.sort(key=lambda x: x["dist_52w_high_pct"], reverse=True)
    near_52w_high.sort(key=lambda x: x["dist_52w_high_pct"], reverse=True)
    near_52w_low.sort(key=lambda x: x["dist_52w_low_pct"])
    breakdown_52w_low.sort(key=lambda x: x["dist_52w_low_pct"])
    all_radar.sort(key=lambda x: x["dist_52w_high_pct"], reverse=True)

    return {
        "breakout_52w_high": breakout_52w_high,
        "near_52w_high": near_52w_high,
        "near_52w_low": near_52w_low,
        "breakdown_52w_low": breakdown_52w_low,
        "all_stocks_radar": all_radar,
    }


# ─── 3. Alert Trigger & Dispatcher Engine ─────────────────────────────────────
def evaluate_and_generate_alerts(session: Session) -> List[Dict]:
    """
    Evaluates all active watchlists and 52W radar to generate automated price alerts.
    """
    radar = get_52_week_high_low_radar(session)
    watchlists = session.query(Watchlist).all()
    triggered_alerts = []

    # 1. Evaluate 52W High Breakouts
    for item in radar["breakout_52w_high"]:
        sym = item["symbol"]
        price = item["current_price"]
        h52 = item["high_52w"]
        msg = f"🚀 52-Week High Breakout: {sym} reached ₹{price:,.2f} (52W High: ₹{h52:,.2f})"

        # Check if alert already created today
        existing = session.execute(text("""
            SELECT id FROM price_alerts
            WHERE symbol = :s AND alert_type = '52W_HIGH_BREAKOUT'
            AND date(created_at) = date('now')
        """), {"s": sym}).first()

        if not existing:
            alert = PriceAlert(
                symbol=sym,
                alert_type="52W_HIGH_BREAKOUT",
                condition_value=h52,
                current_value=price,
                message=msg,
                is_triggered=True,
                triggered_at=datetime.utcnow(),
            )
            session.add(alert)
            triggered_alerts.append({"type": "52W High", "symbol": sym, "message": msg})

    # 2. Evaluate Watchlist Target Prices
    for wl in watchlists:
        for wi in wl.items:
            price_row = session.execute(text("""
                SELECT close FROM daily_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1
            """), {"s": wi.symbol}).first()
            if not price_row:
                continue

            current_p = float(price_row[0] or 0)

            # Target Buy Hit (Price <= Target Buy)
            if wi.target_buy_price and current_p <= wi.target_buy_price:
                msg = f"🎯 Buy Target Hit: {wi.symbol} at ₹{current_p:,.2f} <= Target ₹{wi.target_buy_price:,.2f} [{wl.name}]"
                existing = session.execute(text("""
                    SELECT id FROM price_alerts
                    WHERE symbol = :s AND alert_type = 'TARGET_BUY_HIT'
                    AND date(created_at) = date('now')
                """), {"s": wi.symbol}).first()
                if not existing:
                    session.add(PriceAlert(
                        symbol=wi.symbol, alert_type="TARGET_BUY_HIT",
                        condition_value=wi.target_buy_price, current_value=current_p,
                        message=msg, is_triggered=True, triggered_at=datetime.utcnow()
                    ))
                    triggered_alerts.append({"type": "Buy Target", "symbol": wi.symbol, "message": msg})

            # Target Sell Hit (Price >= Target Sell)
            if wi.target_sell_price and current_p >= wi.target_sell_price:
                msg = f"💰 Profit Target Hit: {wi.symbol} at ₹{current_p:,.2f} >= Target ₹{wi.target_sell_price:,.2f} [{wl.name}]"
                existing = session.execute(text("""
                    SELECT id FROM price_alerts
                    WHERE symbol = :s AND alert_type = 'TARGET_SELL_HIT'
                    AND date(created_at) = date('now')
                """), {"s": wi.symbol}).first()
                if not existing:
                    session.add(PriceAlert(
                        symbol=wi.symbol, alert_type="TARGET_SELL_HIT",
                        condition_value=wi.target_sell_price, current_value=current_p,
                        message=msg, is_triggered=True, triggered_at=datetime.utcnow()
                    ))
                    triggered_alerts.append({"type": "Sell Target", "symbol": wi.symbol, "message": msg})

            # 3. Stop-Loss Hit (Price <= Stop Loss) - CRITICAL SELL REMINDER
            if wi.stop_loss and current_p <= wi.stop_loss:
                msg = f"🛑 Critical Stop-Loss Hit: {wi.symbol} at ₹{current_p:,.2f} <= Stop-Loss ₹{wi.stop_loss:,.2f} [{wl.name}]"
                existing = session.execute(text("""
                    SELECT id FROM price_alerts
                    WHERE symbol = :s AND alert_type = 'STOP_LOSS_HIT'
                    AND date(created_at) = date('now')
                """), {"s": wi.symbol}).first()
                if not existing:
                    session.add(PriceAlert(
                        symbol=wi.symbol, alert_type="STOP_LOSS_HIT",
                        condition_value=wi.stop_loss, current_value=current_p,
                        message=msg, is_triggered=True, triggered_at=datetime.utcnow()
                    ))
                    triggered_alerts.append({"type": "Stop-Loss Hit", "symbol": wi.symbol, "message": msg})

            # 4. Model Signal Turned SELL or Score < 45
            sig_row = session.execute(text("""
                SELECT sig.signal, cs.composite_score FROM signals sig
                LEFT JOIN composite_scores cs ON sig.symbol = cs.symbol AND sig.date = cs.date
                WHERE sig.symbol = :s ORDER BY sig.date DESC LIMIT 1
            """), {"s": wi.symbol}).first()
            if sig_row and (sig_row[0] == 'SELL' or (sig_row[1] and sig_row[1] < 45.0)):
                sig_val = sig_row[0] or "SELL"
                sc_val = float(sig_row[1] or 0.0)
                msg = f"⚠️ Sell Reminder: {wi.symbol} model rating flipped to {sig_val} (Score: {sc_val:.1f}/100) [{wl.name}]"
                existing = session.execute(text("""
                    SELECT id FROM price_alerts
                    WHERE symbol = :s AND alert_type = 'SELL_SIGNAL_ALERT'
                    AND date(created_at) = date('now')
                """), {"s": wi.symbol}).first()
                if not existing:
                    session.add(PriceAlert(
                        symbol=wi.symbol, alert_type="SELL_SIGNAL_ALERT",
                        condition_value=45.0, current_value=sc_val,
                        message=msg, is_triggered=True, triggered_at=datetime.utcnow()
                    ))
                    triggered_alerts.append({"type": "Sell Signal", "symbol": wi.symbol, "message": msg})

            # 5. 200 EMA Breakdown
            ti_row = session.execute(text("""
                SELECT ema_200 FROM technical_indicators WHERE symbol = :s ORDER BY date DESC LIMIT 1
            """), {"s": wi.symbol}).first()
            if ti_row and ti_row[0] and current_p < float(ti_row[0]):
                ema_val = float(ti_row[0])
                msg = f"📉 200-EMA Breakdown: {wi.symbol} at ₹{current_p:,.2f} traded below 200 EMA (₹{ema_val:,.2f}) [{wl.name}]"
                existing = session.execute(text("""
                    SELECT id FROM price_alerts
                    WHERE symbol = :s AND alert_type = '200_EMA_BREAKDOWN'
                    AND date(created_at) = date('now')
                """), {"s": wi.symbol}).first()
                if not existing:
                    session.add(PriceAlert(
                        symbol=wi.symbol, alert_type="200_EMA_BREAKDOWN",
                        condition_value=ema_val, current_value=current_p,
                        message=msg, is_triggered=True, triggered_at=datetime.utcnow()
                    ))
                    triggered_alerts.append({"type": "200 EMA Breakdown", "symbol": wi.symbol, "message": msg})

    session.commit()
    return triggered_alerts


def get_recent_alerts(session: Session, limit: int = 30) -> List[Dict]:
    """Retrieve recent triggered price and breakout alerts."""
    rows = session.execute(text("""
        SELECT id, symbol, alert_type, condition_value, current_value, message, is_triggered, triggered_at
        FROM price_alerts
        ORDER BY triggered_at DESC
        LIMIT :lim
    """), {"lim": limit}).fetchall()

    return [{
        "id": r[0],
        "symbol": r[1],
        "alert_type": r[2],
        "condition_value": r[3],
        "current_value": r[4],
        "message": r[5],
        "is_triggered": bool(r[6]),
        "triggered_at": r[7],
    } for r in rows]
