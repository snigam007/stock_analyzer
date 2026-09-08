"""
core/portfolio_analyzer.py
User Multi-Asset Portfolio Ingestion, Health Audit, Risk Analytics & Actionable Advisory Engine
- Supports Stocks, Mutual Funds, Indexes / ETFs, and Commodities.
- Multi-Asset Search Catalog & Auto-Complete Builder.
- Parses user portfolio inputs (Interactive Search & Add Builder, Interactive Table, CSV upload, or Raw Text Paste).
- Enriches holdings with real-time quotes / NAVs, technical indicators, composite scores, signals, and ML forecasts.
- Evaluates Concentration Risk, Multi-Asset Tilt, Sector Concentration, and Market Cap Allocation.
- Generates concrete asset-by-asset Actionable Suggestions (Accumulate, Hold, Trim Profit, Exit / Review).
- Rebalancing Action Plan.
"""
import io
import re
import logging
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Canonical friendly names for Indexes and Commodities
_INDEX_NAMES = {
    "^NSEI": ("NIFTY 50 Benchmark Index", "Benchmark Core"),
    "^NSEBANK": ("NIFTY Bank Benchmark Index", "Banking"),
    "^BSESN": ("BSE SENSEX Index", "Benchmark Core"),
    "NIFTYBEES.NS": ("Nippon India ETF Nifty 50 BeES", "Large Cap Core"),
    "BANKBEES.NS": ("Nippon India ETF Nifty Bank BeES", "Banking"),
    "GOLDBEES.NS": ("Nippon India ETF Gold BeES", "Precious Metals"),
    "JUNIORBEES.NS": ("Nippon India ETF Nifty Next 50 BeES", "Mid/Large Cap"),
    "NIFTY_MIDCAP_100.NS": ("Nifty Midcap 100 Index", "Mid Cap Core"),
    "^CNXIT": ("NIFTY IT Sector Index", "Information Technology"),
    "^CNXAUTO": ("NIFTY Auto Sector Index", "Automobiles"),
    "^CNXPHARMA": ("NIFTY Pharma Sector Index", "Healthcare"),
    "^CNXFMCG": ("NIFTY FMCG Sector Index", "FMCG"),
    "^CNXENERGY": ("NIFTY Energy Sector Index", "Energy & Oil"),
    "^CNXMETAL": ("NIFTY Metal Sector Index", "Metals & Mining"),
    "^CNXREALTY": ("NIFTY Realty Sector Index", "Real Estate"),
    "^CNXINFRA": ("NIFTY Infrastructure Index", "Infrastructure"),
}

_COMMODITY_NAMES = {
    "GC=F": ("MCX Gold Futures / Spot", "Precious Metals"),
    "SI=F": ("MCX Silver Futures / Spot", "Precious Metals"),
    "CL=F": ("Crude Oil WTI Futures", "Energy Commodities"),
    "NG=F": ("Natural Gas Futures", "Energy Commodities"),
    "HG=F": ("Copper Futures", "Industrial Metals"),
    "ZW=F": ("Wheat / Agri Futures", "Agriculture"),
    "INRUSD=X": ("USD / INR Currency Pair", "Forex"),
}


def get_searchable_assets_catalog(session: Session, category: str = "ALL") -> List[Dict]:
    """
    Returns a unified searchable list of all investment instruments across:
    1. Stocks (366 NSE equities)
    2. Mutual Funds (28 funds across Equity, Hybrid, Debt)
    3. Indexes & ETFs (NIFTY, BANKNIFTY, GOLDBEES, NIFTYBEES, etc.)
    4. Commodities (Gold, Silver, Crude Oil, Natural Gas, Copper)
    """
    catalog = []
    cat_upper = category.upper()

    # 1. Stocks
    if any(k in cat_upper for k in ["ALL", "STOCK", "EQUITY"]):
        stk_rows = session.execute(text("""
            SELECT s.symbol, s.name, s.sector, s.market_cap_tier, p.close
            FROM stocks s
            LEFT JOIN (
                SELECT symbol, close FROM daily_prices WHERE (symbol, date) IN (
                    SELECT symbol, MAX(date) FROM daily_prices GROUP BY symbol
                )
            ) p ON s.symbol = p.symbol
            ORDER BY s.symbol ASC
        """)).fetchall()

        for r in stk_rows:
            sym, name, sec, tier, cmp = r
            cmp_val = float(cmp) if cmp else 0.0
            catalog.append({
                "symbol": sym,
                "name": name or sym,
                "asset_class": "Stock",
                "sector": sec or "General",
                "tier": tier or "Mid",
                "current_price": cmp_val,
                "display_label": f"[Stock] {sym} • {name} (₹{cmp_val:,.2f} • {sec})"
            })

    # 2. Mutual Funds
    if any(k in cat_upper for k in ["ALL", "MUTUAL", "MF", "FUND"]):
        mf_rows = session.execute(text("""
            SELECT m.scheme_code, m.scheme_name, m.category, n.nav
            FROM mutual_funds m
            LEFT JOIN (
                SELECT scheme_code, nav FROM mutual_fund_navs WHERE (scheme_code, date) IN (
                    SELECT scheme_code, MAX(date) FROM mutual_fund_navs GROUP BY scheme_code
                )
            ) n ON m.scheme_code = n.scheme_code
            ORDER BY m.scheme_name ASC
        """)).fetchall()

        for r in mf_rows:
            code, name, cat_name, nav = r
            nav_val = float(nav) if nav else 0.0
            catalog.append({
                "symbol": str(code),
                "name": name or f"Fund {code}",
                "asset_class": "Mutual Fund",
                "sector": f"MF ({cat_name or 'Equity'})",
                "tier": "Mutual Fund",
                "current_price": nav_val,
                "display_label": f"[MF] {name} (NAV: ₹{nav_val:,.2f} • {cat_name}) [{code}]"
            })

    # 3. Indexes & ETFs
    if any(k in cat_upper for k in ["ALL", "INDEX", "ETF"]):
        idx_rows = session.execute(text("""
            SELECT symbol, close FROM index_prices WHERE (symbol, date) IN (
                SELECT symbol, MAX(date) FROM index_prices GROUP BY symbol
            ) ORDER BY symbol ASC
        """)).fetchall()

        for r in idx_rows:
            sym, cmp = r
            cmp_val = float(cmp) if cmp else 0.0
            info = _INDEX_NAMES.get(sym, (sym, "Index / ETF"))
            catalog.append({
                "symbol": sym,
                "name": info[0],
                "asset_class": "Index / ETF",
                "sector": info[1],
                "tier": "Index / ETF",
                "current_price": cmp_val,
                "display_label": f"[ETF/Index] {sym} • {info[0]} (CMP: ₹{cmp_val:,.2f} • {info[1]})"
            })

    # 4. Commodities
    if any(k in cat_upper for k in ["ALL", "COMMODITY", "GOLD", "SILVER"]):
        comm_rows = session.execute(text("""
            SELECT symbol, close FROM commodity_prices WHERE (symbol, date) IN (
                SELECT symbol, MAX(date) FROM commodity_prices GROUP BY symbol
            ) ORDER BY symbol ASC
        """)).fetchall()

        for r in comm_rows:
            sym, cmp = r
            cmp_val = float(cmp) if cmp else 0.0
            info = _COMMODITY_NAMES.get(sym, (sym, "Commodities"))
            catalog.append({
                "symbol": sym,
                "name": info[0],
                "asset_class": "Commodity",
                "sector": info[1],
                "tier": "Commodity",
                "current_price": cmp_val,
                "display_label": f"[Commodity] {sym} • {info[0]} (CMP: ₹{cmp_val:,.2f} • {info[1]})"
            })

    return catalog


def parse_portfolio_text(raw_text: str) -> List[Dict]:
    """
    Parses pasted portfolio text in common formats:
    Examples:
      RELIANCE, 50, 2850
      TCS 25 3900
      118955, 100, 290.50 (Mutual Fund)
      GOLDBEES.NS, 50, 125
    """
    holdings = []
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    for line in lines:
        if any(h in line.upper() for h in ["SYMBOL", "TICKER", "QUANTITY", "BUY PRICE"]):
            continue

        parts = [p.strip() for p in re.split(r"[,;\t]+", line) if p.strip()]
        if len(parts) < 2:
            parts = [p.strip() for p in line.split() if p.strip()]

        if len(parts) >= 2:
            sym = parts[0].strip().upper()
            if sym.endswith(".NS") and not ("BEES" in sym or "MIDCAP" in sym):
                sym = sym[:-3]
            sym = sym.replace(".BO", "").strip()

            try:
                qty = float(parts[1])
                price = float(parts[2]) if len(parts) >= 3 else 0.0

                # Detect asset class
                ac = "Stock"
                if sym.isdigit() or "FUND" in sym:
                    ac = "Mutual Fund"
                elif sym.startswith("^") or "BEES" in sym or "NIFTY" in sym:
                    ac = "Index / ETF"
                elif any(sym.startswith(x) for x in ["GC=", "SI=", "CL=", "NG=", "HG=", "ZW=", "INRUSD="]) or sym in ["GOLD", "SILVER", "CRUDE"]:
                    ac = "Commodity"

                holdings.append({
                    "symbol": sym,
                    "shares": qty,
                    "buy_price": price,
                    "asset_class": ac
                })
            except Exception:
                continue
    return holdings


def parse_portfolio_csv(file_bytes: bytes) -> List[Dict]:
    """
    Parses broker holding CSV files (Zerodha, Groww, AngelOne, Upstox, or standard CSV).
    """
    holdings = []
    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
        col_map = {c.strip().upper(): c for c in df.columns}

        sym_col = None
        for candidate in ["SYMBOL", "TICKER", "INSTRUMENT", "STOCK", "SECURITY", "SCHEME"]:
            if candidate in col_map:
                sym_col = col_map[candidate]
                break

        qty_col = None
        for candidate in ["QUANTITY", "QTY", "SHARES", "AVAILABLE QTY", "HOLDINGS", "UNITS"]:
            if candidate in col_map:
                qty_col = col_map[candidate]
                break

        price_col = None
        for candidate in ["BUY PRICE", "AVG PRICE", "AVG. PRICE", "BUY AVG", "COST PRICE", "PRICE", "AVERAGE PRICE", "AVG NAV"]:
            if candidate in col_map:
                price_col = col_map[candidate]
                break

        if sym_col and qty_col:
            for _, row in df.iterrows():
                sym = str(row[sym_col]).strip().upper()
                if not sym or sym == "NAN":
                    continue

                if sym.endswith(".NS") and not ("BEES" in sym or "MIDCAP" in sym):
                    sym = sym[:-3]
                sym = sym.replace(".BO", "").strip()

                try:
                    qty = float(str(row[qty_col]).replace(",", ""))
                    price = float(str(row[price_col]).replace(",", "")) if price_col and pd.notnull(row[price_col]) else 0.0
                    if qty > 0:
                        ac = "Stock"
                        if sym.isdigit() or "FUND" in sym.upper():
                            ac = "Mutual Fund"
                        elif sym.startswith("^") or "BEES" in sym.upper() or "NIFTY" in sym.upper():
                            ac = "Index / ETF"
                        elif any(sym.startswith(x) for x in ["GC=", "SI=", "CL=", "NG=", "HG=", "ZW="]) or sym.upper() in ["GOLD", "SILVER"]:
                            ac = "Commodity"

                        holdings.append({
                            "symbol": sym,
                            "shares": qty,
                            "buy_price": price,
                            "asset_class": ac
                        })
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"Error parsing portfolio CSV: {e}")
    return holdings


def analyze_custom_portfolio(holdings: List[Dict], session: Session) -> Dict:
    """
    Performs full institutional diagnostic audit and actionable advisory on user's punched-in portfolio
    across Stocks, Mutual Funds, Indexes / ETFs, and Commodities.
    """
    if not holdings:
        return {"status": "EMPTY", "holdings": [], "summary": {}}

    enriched_items = []
    total_invested = 0.0
    total_current = 0.0
    today_pnl = 0.0

    for h in holdings:
        sym = str(h["symbol"]).strip()
        shares = float(h.get("shares") if h.get("shares") is not None else (h.get("quantity") if h.get("quantity") is not None else 1.0))
        buy_p = float(h.get("buy_price", 0.0) or 0.0)
        asset_class = h.get("asset_class")

        # Auto-detect asset class if missing
        if not asset_class:
            if sym.isdigit() or "FUND" in sym.upper():
                asset_class = "Mutual Fund"
            elif sym.startswith("^") or "BEES" in sym.upper() or "NIFTY" in sym.upper():
                asset_class = "Index / ETF"
            elif any(sym.startswith(x) for x in ["GC=", "SI=", "CL=", "NG=", "HG=", "ZW=", "INRUSD="]) or sym.upper() in ["GOLD", "SILVER", "CRUDE"]:
                asset_class = "Commodity"
            else:
                asset_class = "Stock"

        name = sym
        sector = "General"
        tier = "Mid"
        cmp = buy_p
        day_ret_pct = 0.0
        composite_score = 55.0
        signal = "HOLD"
        strength = "NEUTRAL"
        risk_lvl = "MODERATE"
        stop_loss = round(buy_p * 0.88, 2)
        target_p = round(buy_p * 1.15, 2)
        momentum_6m_pct = 0.0
        ml_1m_pct = None
        is_above_50 = True
        is_above_200 = True
        advice = "HOLD"
        advice_badge = "🟢 HOLD"
        advice_reason = "Compounding within safe risk bounds."

        # ── 1. MUTUAL FUND RESOLUTION ──────────────────────────────────────────
        if asset_class == "Mutual Fund" or sym.isdigit():
            asset_class = "Mutual Fund"
            tier = "Mutual Fund"
            mf_row = session.execute(text("""
                SELECT scheme_name, category FROM mutual_funds WHERE scheme_code = :s
            """), {"s": sym}).first()
            if not mf_row:
                mf_row = session.execute(text("""
                    SELECT scheme_name, category FROM mutual_funds WHERE scheme_name LIKE :s LIMIT 1
                """), {"s": f"%{sym}%"}).first()

            name = mf_row[0] if mf_row else f"Mutual Fund ({sym})"
            sector = f"MF: {mf_row[1]}" if (mf_row and mf_row[1]) else "MF: Equity"

            nav_row = session.execute(text("""
                SELECT nav, daily_return FROM mutual_fund_navs WHERE scheme_code = :s ORDER BY date DESC LIMIT 1
            """), {"s": sym}).first()
            if nav_row and nav_row[0]:
                cmp = float(nav_row[0])
                day_ret_pct = float(nav_row[1] or 0.0)

            # 6M momentum from NAV
            past_nav = session.execute(text("""
                SELECT nav FROM mutual_fund_navs
                WHERE scheme_code = :s AND date <= date((SELECT MAX(date) FROM mutual_fund_navs), '-180 days')
                ORDER BY date DESC LIMIT 1
            """), {"s": sym}).scalar()
            if past_nav and float(past_nav) > 0 and cmp > 0:
                momentum_6m_pct = round((cmp - float(past_nav)) / float(past_nav) * 100.0, 1)

            composite_score = round(min(95.0, max(40.0, 55.0 + momentum_6m_pct * 1.5)), 1)
            stop_loss = round(cmp * 0.88, 2)
            target_p = round(cmp * 1.18, 2)

            if momentum_6m_pct >= 8.0:
                signal = "BUY"
                advice = "ACCUMULATE"
                advice_badge = "🚀 ACCUMULATE (SIP)"
                advice_reason = f"Top-tier institutional fund: +{momentum_6m_pct:.1f}% 6M growth. Prime candidate for steady SIP accumulation."
            elif momentum_6m_pct >= 0.0:
                signal = "HOLD"
                advice = "HOLD"
                advice_badge = "🟢 HOLD"
                advice_reason = f"Healthy compounder pacing benchmark (+{momentum_6m_pct:.1f}% 6M). Let units accumulate."
            else:
                signal = "WATCH"
                advice = "REBALANCE"
                advice_badge = "⚠️ REVIEW FUND"
                advice_reason = f"Fund in drawdown ({momentum_6m_pct:.1f}% 6M). Consider reviewing fund manager track record."

        # ── 2. INDEX / ETF RESOLUTION ──────────────────────────────────────────
        elif asset_class == "Index / ETF" or sym.startswith("^") or "BEES" in sym.upper():
            asset_class = "Index / ETF"
            tier = "Index / ETF"
            info = _INDEX_NAMES.get(sym, (sym, "Index / ETF"))
            name = info[0]
            sector = info[1]

            pr_row = session.execute(text("""
                SELECT close, daily_return FROM index_prices WHERE symbol = :s ORDER BY date DESC LIMIT 1
            """), {"s": sym}).first()
            if pr_row and pr_row[0]:
                cmp = float(pr_row[0])
                day_ret_pct = float(pr_row[1] or 0.0)

            past_p = session.execute(text("""
                SELECT close FROM index_prices
                WHERE symbol = :s AND date <= date((SELECT MAX(date) FROM index_prices), '-180 days')
                ORDER BY date DESC LIMIT 1
            """), {"s": sym}).scalar()
            if past_p and float(past_p) > 0 and cmp > 0:
                momentum_6m_pct = round((cmp - float(past_p)) / float(past_p) * 100.0, 1)

            composite_score = round(min(90.0, max(50.0, 60.0 + momentum_6m_pct * 1.0)), 1)
            stop_loss = round(cmp * 0.90, 2)
            target_p = round(cmp * 1.15, 2)
            advice = "HOLD"
            advice_badge = "💎 CORE COMPOUNDER"
            advice_reason = "Core index / ETF bedrock anchor. Minimizes unsystematic stock risk; ride long-term trend."

        # ── 3. COMMODITY RESOLUTION ────────────────────────────────────────────
        elif asset_class == "Commodity" or any(sym.startswith(x) for x in ["GC=", "SI=", "CL=", "NG=", "HG=", "ZW="]) or sym.upper() in ["GOLD", "SILVER"]:
            asset_class = "Commodity"
            tier = "Commodity"
            c_sym = "GC=F" if sym.upper() in ["GOLD", "MCX_GOLD"] else ("SI=F" if sym.upper() in ["SILVER", "MCX_SILVER"] else sym)
            info = _COMMODITY_NAMES.get(c_sym, (c_sym, "Commodities"))
            name = info[0]
            sector = info[1]

            pr_row = session.execute(text("""
                SELECT close, daily_return FROM commodity_prices WHERE symbol = :s ORDER BY date DESC LIMIT 1
            """), {"s": c_sym}).first()
            if pr_row and pr_row[0]:
                cmp = float(pr_row[0])
                day_ret_pct = float(pr_row[1] or 0.0)

            composite_score = 65.0
            stop_loss = round(cmp * 0.88, 2)
            target_p = round(cmp * 1.15, 2)
            advice = "HOLD"
            advice_badge = "🛡️ STRATEGIC HEDGE"
            advice_reason = "Commodity defensive tilt: protects capital against currency depreciation & macro volatility."

        # ── 4. DIRECT EQUITY / STOCK RESOLUTION ────────────────────────────────
        else:
            asset_class = "Stock"
            stk_row = session.execute(text("""
                SELECT name, sector, market_cap_tier FROM stocks WHERE symbol = :s
            """), {"s": sym}).first()

            name = stk_row[0] if stk_row else sym
            sector = stk_row[1] if stk_row else "Other / Diversified"
            tier = stk_row[2] if stk_row else "Mid"

            pr_row = session.execute(text("""
                SELECT close, daily_return FROM daily_prices WHERE symbol = :s ORDER BY date DESC LIMIT 1
            """), {"s": sym}).first()
            if pr_row and pr_row[0]:
                cmp = float(pr_row[0])
                day_ret_pct = float(pr_row[1] or 0.0)

            # Technicals
            ti_row = session.execute(text("""
                SELECT ema_50, ema_200, rsi_14, adx FROM technical_indicators WHERE symbol = :s ORDER BY date DESC LIMIT 1
            """), {"s": sym}).first()
            ema_50 = float(ti_row[0]) if (ti_row and ti_row[0]) else None
            ema_200 = float(ti_row[1]) if (ti_row and ti_row[1]) else None
            rsi = float(ti_row[2]) if (ti_row and ti_row[2]) else 50.0
            adx = float(ti_row[3]) if (ti_row and ti_row[3]) else 20.0

            # Signal & Score
            sig_row = session.execute(text("""
                SELECT signal, signal_strength, risk_level, stop_loss, target_price_1
                FROM signals WHERE symbol = :s ORDER BY date DESC LIMIT 1
            """), {"s": sym}).first()
            signal = sig_row[0] if sig_row else "WATCH"
            strength = sig_row[1] if sig_row else "NEUTRAL"
            risk_lvl = sig_row[2] if sig_row else "MODERATE"
            stop_loss = float(sig_row[3]) if (sig_row and sig_row[3]) else round(cmp * 0.92, 2)
            target_p = float(sig_row[4]) if (sig_row and sig_row[4]) else round(cmp * 1.15, 2)

            score_row = session.execute(text("""
                SELECT composite_score FROM composite_scores WHERE symbol = :s ORDER BY date DESC LIMIT 1
            """), {"s": sym}).scalar()
            composite_score = float(score_row or 50.0)

            # 6M momentum
            past_p = session.execute(text("""
                SELECT close FROM daily_prices
                WHERE symbol = :s AND date <= date((SELECT MAX(date) FROM daily_prices), '-180 days')
                ORDER BY date DESC LIMIT 1
            """), {"s": sym}).scalar()
            momentum_6m_pct = round((cmp - float(past_p)) / float(past_p) * 100.0, 1) if (past_p and float(past_p) > 0) else 0.0

            # ML Forecast
            fc_row = session.execute(text("""
                SELECT forecast_1m_change_pct, forecast_3m_change_pct FROM forecasts
                WHERE symbol = :s ORDER BY generated_date DESC LIMIT 1
            """), {"s": sym}).first()
            ml_1m_pct = float(fc_row[0]) if (fc_row and fc_row[0] is not None) else None

            is_above_50 = bool(ema_50 and cmp >= ema_50)
            is_above_200 = bool(ema_200 and cmp >= ema_200)

            # Advice logic for Stocks
            if (not is_above_200 and signal == "SELL") or (cmp <= stop_loss) or (composite_score < 42.0):
                advice = "EXIT"
                advice_badge = "🛑 EXIT / CUT LOSS"
                advice_reason = f"Structural breakdown: below 200 EMA or breached stop loss (₹{stop_loss:,.2f}). Score degraded to {composite_score:.1f}/100."
            elif (buy_p > 0 and (cmp - buy_p) / buy_p * 100.0 >= 50.0) or (rsi > 76.0 and adx < 24.0):
                advice = "TRIM"
                advice_badge = "💰 TRIM / BOOK PROFIT"
                advice_reason = f"Parabolic milestone reached: +{(cmp - buy_p) / buy_p * 100.0:.1f}% profit. Lock 20-30% capital."
            elif signal == "BUY" and composite_score >= 63.0 and is_above_50 and (ml_1m_pct is None or ml_1m_pct >= 0):
                advice = "ACCUMULATE"
                advice_badge = "🚀 ACCUMULATE"
                advice_reason = f"High conviction momentum: Score {composite_score:.1f}/100 with confirmed upward price velocity (+{momentum_6m_pct:.1f}% 6M)."
            elif momentum_6m_pct < -8.0 and not is_above_50:
                advice = "REBALANCE"
                advice_badge = "⚠️ WEAK / REBALANCE"
                advice_reason = "Intermediate lag: Stock down over 6 months below 50 EMA. Consider reallocating capital to top sector leaders."

        if buy_p <= 0.0:
            buy_p = cmp

        invested_val = round(buy_p * shares, 2)
        current_val = round(cmp * shares, 2)
        unrealized_pnl_inr = round(current_val - invested_val, 2)
        unrealized_pnl_pct = round((cmp - buy_p) / buy_p * 100.0, 2) if buy_p > 0 else 0.0
        day_pnl_inr = round(current_val * (day_ret_pct / 100.0), 2)

        total_invested += invested_val
        total_current += current_val
        today_pnl += day_pnl_inr

        enriched_items.append({
            "symbol": sym,
            "name": name,
            "asset_class": asset_class,
            "sector": sector,
            "tier": tier,
            "shares": shares,
            "buy_price": buy_p,
            "cmp": cmp,
            "invested_val": invested_val,
            "current_val": current_val,
            "unrealized_pnl_inr": unrealized_pnl_inr,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "day_pnl_inr": day_pnl_inr,
            "day_ret_pct": day_ret_pct,
            "composite_score": composite_score,
            "signal": signal,
            "strength": strength,
            "risk_level": risk_lvl,
            "stop_loss": stop_loss,
            "target_price": target_p,
            "momentum_6m_pct": momentum_6m_pct,
            "ml_1m_pct": ml_1m_pct,
            "is_above_50": is_above_50,
            "is_above_200": is_above_200,
            "advice": advice,
            "advice_badge": advice_badge,
            "advice_reason": advice_reason,
        })

    # Portfolio Allocation Weights
    for it in enriched_items:
        it["weight_pct"] = round(it["current_val"] / max(1.0, total_current) * 100.0, 2)

    enriched_items.sort(key=lambda x: x["current_val"], reverse=True)

    # ── Portfolio-Level Health & Risk Diagnostics ──────────────────────────────
    total_pnl_inr = round(total_current - total_invested, 2)
    total_pnl_pct = round(total_pnl_inr / max(1.0, total_invested) * 100.0, 2)
    today_pnl_pct = round(today_pnl / max(1.0, total_current) * 100.0, 2)

    # Concentration Metrics
    weights = [it["weight_pct"] for it in enriched_items]
    top3_weight = round(sum(weights[:3]), 1)
    top5_weight = round(sum(weights[:5]), 1)
    hhi_score = round(sum((w) ** 2 for w in weights), 0)

    concentration_risk = "LOW (Well Diversified)" if hhi_score < 1500 else (
        "MODERATE (Balanced)" if hhi_score < 2500 else "HIGH (Over-Concentrated)"
    )

    overweight_alerts = [
        f"⚠️ **{it['symbol']}** accounts for **{it['weight_pct']:.1f}%** of portfolio (Exceeds institutional 15-18% cap)"
        for it in enriched_items if it["weight_pct"] > 18.0
    ]

    # Sector Distribution
    sector_exposure = {}
    for it in enriched_items:
        sec = it["sector"]
        sector_exposure[sec] = sector_exposure.get(sec, 0.0) + it["current_val"]

    sector_breakdown = []
    sector_alerts = []
    for sec, val in sector_exposure.items():
        pct = round(val / max(1.0, total_current) * 100.0, 2)
        sector_breakdown.append({"sector": sec, "value": val, "weight_pct": pct})
        if pct > 30.0:
            sector_alerts.append(f"⚠️ Sector **{sec}** is **{pct:.1f}%** of portfolio (Institutional cap is 25%)")

    sector_breakdown.sort(key=lambda x: x["weight_pct"], reverse=True)

    # Asset Class Breakdown (Multi-Asset Tilt)
    ac_exposure = {}
    for it in enriched_items:
        ac = it["asset_class"]
        ac_exposure[ac] = ac_exposure.get(ac, 0.0) + it["current_val"]

    asset_class_breakdown = [
        {"asset_class": k, "value": v, "weight_pct": round(v / max(1.0, total_current) * 100.0, 1)}
        for k, v in ac_exposure.items()
    ]
    asset_class_breakdown.sort(key=lambda x: x["value"], reverse=True)

    # Market Cap Tier Distribution
    tier_exposure = {"Large": 0.0, "Mid": 0.0, "Small": 0.0, "Mutual Fund": 0.0, "Index / ETF": 0.0, "Commodity": 0.0}
    for it in enriched_items:
        t = it["tier"]
        tier_exposure[t] = tier_exposure.get(t, 0.0) + it["current_val"]

    tier_breakdown = {
        k: round(v / max(1.0, total_current) * 100.0, 1) for k, v in tier_exposure.items() if v > 0
    }

    # Diagnostics
    bullish_cnt = sum(1 for it in enriched_items if it["is_above_50"] and it["is_above_200"])
    weak_cnt = sum(1 for it in enriched_items if not it["is_above_200"])
    avg_score = round(np.average([it["composite_score"] for it in enriched_items], weights=weights), 1)

    health_rating = "🌟 EXCELLENT" if avg_score >= 65 and weak_cnt == 0 else (
        "🟢 HEALTHY" if avg_score >= 58 else (
            "🟡 CAUTION / REBALANCE NEEDED" if avg_score >= 50 else "🔴 HIGH RISK / DETERIORATING"
        )
    )

    advice_counts = {
        "ACCUMULATE": sum(1 for it in enriched_items if it["advice"] == "ACCUMULATE"),
        "HOLD": sum(1 for it in enriched_items if it["advice"] == "HOLD"),
        "TRIM": sum(1 for it in enriched_items if it["advice"] == "TRIM"),
        "REBALANCE": sum(1 for it in enriched_items if it["advice"] == "REBALANCE"),
        "EXIT": sum(1 for it in enriched_items if it["advice"] == "EXIT"),
    }

    summary = {
        "total_holdings": len(enriched_items),
        "total_invested": total_invested,
        "total_current": total_current,
        "total_pnl_inr": total_pnl_inr,
        "total_pnl_pct": total_pnl_pct,
        "today_pnl_inr": today_pnl,
        "today_pnl_pct": today_pnl_pct,
        "weighted_avg_score": avg_score,
        "health_rating": health_rating,
        "top3_weight_pct": top3_weight,
        "top5_weight_pct": top5_weight,
        "hhi_score": hhi_score,
        "concentration_risk": concentration_risk,
        "overweight_alerts": overweight_alerts,
        "sector_alerts": sector_alerts,
        "sector_breakdown": sector_breakdown,
        "asset_class_breakdown": asset_class_breakdown,
        "tier_breakdown": tier_breakdown,
        "advice_counts": advice_counts,
        "bullish_trend_pct": round(bullish_cnt / max(1, len(enriched_items)) * 100.0, 1),
        "weak_trend_pct": round(weak_cnt / max(1, len(enriched_items)) * 100.0, 1),
    }

    return {
        "status": "SUCCESS",
        "summary": summary,
        "holdings": enriched_items,
    }
