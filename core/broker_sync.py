"""
Broker Portfolio Import & Live Holdings Synchronization Engine
- Supports Zerodha Kite (holdings.csv) and Groww (holdings.csv / xlsx)
- Reconciles live portfolio holdings against Monthly SIP & Sell Radar rules
- Generates precise whole-share rebalance orders, pyramid tranches, and sell/skim alerts
"""
import io
import re
import math
import logging
from typing import Dict, List, Optional, Tuple, Union
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def normalize_symbol(raw_sym: str) -> str:
    """Normalizes raw broker ticker symbol to standardized NSE Yahoo Finance format (e.g. RELIANCE -> RELIANCE.NS)"""
    s = str(raw_sym or "").strip().upper()
    s = re.sub(r'[^A-Z0-9_\-\.]', '', s)
    if not s:
        return ""
    if s.endswith(".BO"):
        return s
    if not s.endswith(".NS"):
        s = f"{s}.NS"
    return s


def parse_broker_holdings(file_source: Union[str, bytes, io.BytesIO, pd.DataFrame], broker_hint: str = "AUTO") -> Dict:
    """
    Parses Zerodha or Groww holdings CSV/Excel into a standardized portfolio list.
    Returns:
      {
        "broker": "ZERODHA" | "GROWW" | "GENERIC",
        "total_holdings_count": int,
        "total_invested": float,
        "current_value": float,
        "total_pnl": float,
        "total_pnl_pct": float,
        "holdings": List[Dict]
      }
    """
    try:
        if isinstance(file_source, pd.DataFrame):
            df = file_source.copy()
        elif isinstance(file_source, (bytes, bytearray)):
            try:
                df = pd.read_csv(io.BytesIO(file_source))
            except Exception:
                df = pd.read_excel(io.BytesIO(file_source))
        elif isinstance(file_source, io.BytesIO):
            try:
                df = pd.read_csv(file_source)
            except Exception:
                file_source.seek(0)
                df = pd.read_excel(file_source)
        elif isinstance(file_source, str):
            try:
                df = pd.read_csv(io.StringIO(file_source))
            except Exception:
                df = pd.read_csv(file_source)
        else:
            return {"error": "Unsupported file source format."}
    except Exception as e:
        return {"error": f"Failed to parse file: {str(e)}"}

    if df.empty:
        return {"error": "Uploaded file is empty."}

    # Clean column headers
    orig_cols = list(df.columns)
    col_map = {c: str(c).strip().lower().replace(" ", "_").replace(".", "").replace("%", "pct") for c in orig_cols}
    df = df.rename(columns=col_map)
    cols = list(df.columns)

    broker_detected = "GENERIC"
    parsed_holdings = []

    # Check for Zerodha Kite Holdings format:
    # columns usually: instrument, qty, avg_cost, ltp, cur_val, p&l, net_chg
    if any("instrument" in c for c in cols) or (any("qty" in c for c in cols) and any("avg" in c for c in cols) and any("ltp" in c for c in cols)):
        broker_detected = "ZERODHA"
        sym_col = next((c for c in cols if "instrument" in c or "symbol" in c), cols[0])
        qty_col = next((c for c in cols if "qty" in c or "shares" in c or "quantity" in c), None)
        cost_col = next((c for c in cols if "avg" in c or "buy" in c), None)
        ltp_col = next((c for c in cols if "ltp" in c or "cur_price" in c or "market_price" in c or "close" in c), None)

    # Check for Groww Holdings format:
    # columns usually: stock_name, symbol, shares, average_price, current_price, current_value, returns
    elif any("groww" in str(broker_hint).lower() for _ in [1]) or (any("shares" in c for c in cols) and any("average" in c for c in cols)):
        broker_detected = "GROWW"
        sym_col = next((c for c in cols if "symbol" in c or "stock" in c or "company" in c), cols[0])
        qty_col = next((c for c in cols if "shares" in c or "qty" in c), None)
        cost_col = next((c for c in cols if "average" in c or "avg" in c or "buy" in c), None)
        ltp_col = next((c for c in cols if "current" in c or "market" in c or "ltp" in c), None)
    else:
        sym_col = cols[0]
        qty_col = cols[1] if len(cols) > 1 else None
        cost_col = cols[2] if len(cols) > 2 else None
        ltp_col = cols[3] if len(cols) > 3 else None

    if not qty_col or not cost_col:
        return {"error": f"Could not identify quantity and average cost columns. Found headers: {orig_cols}"}

    for idx, row in df.iterrows():
        raw_sym = str(row.get(sym_col, "")).strip()
        if not raw_sym or raw_sym.lower() in ("nan", "total", "summary", "disclaimer"):
            continue
        try:
            qty = float(re.sub(r'[^\d\.]', '', str(row.get(qty_col, 0))))
            if qty <= 0:
                continue
            avg_cost = float(re.sub(r'[^\d\.]', '', str(row.get(cost_col, 0))))
            if avg_cost <= 0:
                continue
            ltp = float(re.sub(r'[^\d\.]', '', str(row.get(ltp_col, avg_cost)))) if ltp_col else avg_cost
            if ltp <= 0:
                ltp = avg_cost
        except Exception:
            continue

        std_sym = normalize_symbol(raw_sym)
        invested = round(qty * avg_cost, 2)
        cur_val = round(qty * ltp, 2)
        pnl = round(cur_val - invested, 2)
        pnl_pct = round((ltp - avg_cost) / max(0.01, avg_cost) * 100.0, 2)

        parsed_holdings.append({
            "symbol": std_sym,
            "raw_symbol": raw_sym,
            "shares": int(math.floor(qty)),
            "avg_cost": round(avg_cost, 2),
            "current_price": round(ltp, 2),
            "invested_amount": invested,
            "current_value": cur_val,
            "pnl": pnl,
            "pnl_pct": pnl_pct
        })

    if not parsed_holdings:
        return {"error": "No valid stock holdings could be extracted."}

    total_inv = sum(h["invested_amount"] for h in parsed_holdings)
    total_cur = sum(h["current_value"] for h in parsed_holdings)
    tot_pnl = round(total_cur - total_inv, 2)
    tot_pnl_pct = round(tot_pnl / max(0.01, total_inv) * 100.0, 2)

    return {
        "broker": broker_detected,
        "total_holdings_count": len(parsed_holdings),
        "total_invested": round(total_inv, 2),
        "current_value": round(total_cur, 2),
        "total_pnl": tot_pnl,
        "total_pnl_pct": tot_pnl_pct,
        "holdings": parsed_holdings
    }


def reconcile_portfolio_with_sip_radar(
    holdings_data: Dict,
    recommended_basket: Dict,
    monthly_wallet: float = 20000.0,
    enable_stepladders: bool = True,
    enable_parabolic_skims: bool = True
) -> Dict:
    """
    Cross-references actual broker holdings against the quantitative Monthly SIP basket & Sell Radar.
    Identifies:
      1. Pyramid average-up tranches for existing holdings in the top momentum basket
      2. New initiator positions to balance the monthly basket
      3. Sell / stop-loss reminder alerts on open broker positions
      4. Parabolic profit skim recommendations (+150% / +250%)
    """
    holdings = holdings_data.get("holdings", [])
    rec_assets = recommended_basket.get("assets", [])
    rec_sym_map = {a["symbol"]: a for a in rec_assets}

    owned_sym_map = {h["symbol"]: h for h in holdings}

    pyramid_recommendations = []
    new_initiations = []
    sell_alerts = []
    profit_skims = []
    active_compounding = []

    # 1. Audit all currently owned holdings
    for h in holdings:
        sym = h["symbol"]
        pnl_pct = h["pnl_pct"]
        ltp = h["current_price"]
        avg_cost = h["avg_cost"]
        shares = h["shares"]

        # Calculate structural trailing stops & stepladders
        # Calibrated baseline: -14% structural stop, +20% -> BE, +50% -> +25%, +100% -> +60%, +200% -> +130%
        structural_sl = round(avg_cost * 0.86, 2)
        stepladder_sl = structural_sl
        stepladder_level = "Structural Stop (-14%)"

        if enable_stepladders:
            if pnl_pct >= 200.0:
                stepladder_sl = round(avg_cost * 2.30, 2)
                stepladder_level = "🪜 Stepladder 4: Locked +130% Floor"
            elif pnl_pct >= 100.0:
                stepladder_sl = round(avg_cost * 1.60, 2)
                stepladder_level = "🪜 Stepladder 3: Locked +60% Floor"
            elif pnl_pct >= 50.0:
                stepladder_sl = round(avg_cost * 1.25, 2)
                stepladder_level = "🪜 Stepladder 2: Locked +25% Floor"
            elif pnl_pct >= 20.0:
                stepladder_sl = round(avg_cost * 1.02, 2)
                stepladder_level = "🪜 Stepladder 1: Break-Even + 2%"

        # Check Stop-Loss Breaches
        if ltp <= stepladder_sl:
            sell_alerts.append({
                "symbol": sym,
                "shares": shares,
                "avg_cost": avg_cost,
                "current_price": ltp,
                "pnl_pct": pnl_pct,
                "stop_loss": stepladder_sl,
                "level_name": stepladder_level,
                "action": "SELL_NOW",
                "urgency": "🚨 CRITICAL",
                "reason": f"LTP (₹{ltp}) breached {stepladder_level} (₹{stepladder_sl}). Protect capital immediately."
            })
            continue

        # Check Parabolic Profit Skims (+150% and +250%)
        if enable_parabolic_skims and shares >= 4:
            if pnl_pct >= 250.0:
                skim_shares = max(1, int(math.floor(shares * 0.15)))
                profit_skims.append({
                    "symbol": sym,
                    "shares_to_trim": skim_shares,
                    "remaining_shares": shares - skim_shares,
                    "current_price": ltp,
                    "pnl_pct": pnl_pct,
                    "milestone": "+250% Mega-Bag Milestone",
                    "action": f"TRIM 15% ({skim_shares} Shares)",
                    "freed_cash": round(skim_shares * ltp, 2),
                    "reason": f"Gain is +{pnl_pct:.1f}%. Bank risk-free capital into reserves while letting 85% compound under trailing stops."
                })
            elif pnl_pct >= 150.0:
                skim_shares = max(1, int(math.floor(shares * 0.15)))
                profit_skims.append({
                    "symbol": sym,
                    "shares_to_trim": skim_shares,
                    "remaining_shares": shares - skim_shares,
                    "current_price": ltp,
                    "pnl_pct": pnl_pct,
                    "milestone": "+150% Milestone",
                    "action": f"TRIM 15% ({skim_shares} Shares)",
                    "freed_cash": round(skim_shares * ltp, 2),
                    "reason": f"Gain is +{pnl_pct:.1f}%. Lock 15% profit to de-risk original capital."
                })

        # Check if holding qualifies for Winner Pyramiding in current month's basket
        if sym in rec_sym_map and pnl_pct > 0:
            rec_item = rec_sym_map[sym]
            pyramid_recommendations.append({
                "symbol": sym,
                "name": rec_item.get("name", sym),
                "sector": rec_item.get("sector", "General"),
                "current_shares": shares,
                "avg_cost": avg_cost,
                "current_price": ltp,
                "pnl_pct": pnl_pct,
                "recommended_new_shares": rec_item.get("shares", 0),
                "fresh_investment": rec_item.get("allocation", 0.0),
                "action": "🚀 PYRAMID (AVERAGE UP)",
                "reason": f"Stock is leading current momentum basket and already sitting at +{pnl_pct:.1f}% profit. Adding shares accelerates multi-year compounding."
            })
        else:
            active_compounding.append({
                "symbol": sym,
                "shares": shares,
                "current_price": ltp,
                "pnl_pct": pnl_pct,
                "stepladder_floor": stepladder_sl,
                "floor_status": stepladder_level,
                "status": "🟢 HEALTHY COMPOUNDING"
            })

    # 2. Check for New Initiations from the recommended basket (assets not currently owned)
    for rec_item in rec_assets:
        sym = rec_item["symbol"]
        if sym not in owned_sym_map and not rec_item.get("is_mf", False) and not rec_item.get("is_etf", False):
            new_initiations.append({
                "symbol": sym,
                "name": rec_item.get("name", sym),
                "sector": rec_item.get("sector", "General"),
                "tier": rec_item.get("tier", "MID"),
                "recommended_shares": rec_item.get("shares", 0),
                "allocation": rec_item.get("allocation", 0.0),
                "current_price": rec_item.get("current_price", 0.0),
                "action": "⭐ NEW INITIATION",
                "reason": "Top-ranked momentum candidate not yet in your portfolio. Initiate fresh tranche."
            })

    # 3. Formulate Exact Whole-Share Execution Order Sheet
    order_sheet = []
    for pyr in pyramid_recommendations:
        order_sheet.append({
            "symbol": pyr["symbol"],
            "type": "PYRAMID_BUY",
            "shares": pyr["recommended_new_shares"],
            "approx_price": pyr["current_price"],
            "approx_cost": pyr["fresh_investment"],
            "status": "EXECUTE_BUY"
        })
    for init in new_initiations:
        order_sheet.append({
            "symbol": init["symbol"],
            "type": "NEW_BUY",
            "shares": init["recommended_shares"],
            "approx_price": init["current_price"],
            "approx_cost": init["allocation"],
            "status": "EXECUTE_BUY"
        })
    for skim in profit_skims:
        order_sheet.append({
            "symbol": skim["symbol"],
            "type": "PROFIT_SKIM_SELL",
            "shares": skim["shares_to_trim"],
            "approx_price": skim["current_price"],
            "approx_cost": -skim["freed_cash"],
            "status": "EXECUTE_SELL"
        })
    for sl in sell_alerts:
        order_sheet.append({
            "symbol": sl["symbol"],
            "type": "STOP_LOSS_SELL",
            "shares": sl["shares"],
            "approx_price": sl["current_price"],
            "approx_cost": -round(sl["shares"] * sl["current_price"], 2),
            "status": "EXECUTE_SELL"
        })

    return {
        "portfolio_summary": {
            "total_invested": holdings_data.get("total_invested", 0.0),
            "current_value": holdings_data.get("current_value", 0.0),
            "total_pnl": holdings_data.get("total_pnl", 0.0),
            "total_pnl_pct": holdings_data.get("total_pnl_pct", 0.0),
            "holdings_count": len(holdings)
        },
        "pyramid_tranches": pyramid_recommendations,
        "new_initiations": new_initiations,
        "sell_alerts": sell_alerts,
        "profit_skims": profit_skims,
        "healthy_compounding": active_compounding,
        "execution_order_sheet": order_sheet
    }
