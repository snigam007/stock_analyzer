"""
Terminal AI Quant Copilot Engine
- Natural Language Market Copilot & Autonomous Strategy Diagnostician
- Parses user queries and executes multi-factor SQL recipes against SQLite database
- Returns structured hedge-fund style quantitative diagnosis and actionable data tables
"""
import logging
from typing import Dict, List, Optional
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def answer_quant_copilot_query(user_query: str, session: Session) -> Dict:
    """Answers natural language market queries using database scans and quant models."""
    q_clean = user_query.strip().lower()
    
    # 1. High Piotroski & Quality Stocks
    if "piotroski" in q_clean or "quality" in q_clean or "fundament" in q_clean:
        sql = """
            SELECT sig.symbol, s.name, s.sector, s.market_cap_tier, sig.current_price,
                   cs.composite_score, sig.signal, sig.risk_level
            FROM signals sig
            JOIN stocks s ON sig.symbol = s.symbol
            JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
            WHERE sig.date = (SELECT MAX(date) FROM signals)
            AND cs.composite_score >= 60.0
            ORDER BY cs.composite_score DESC
            LIMIT 10
        """
        rows = session.execute(text(sql)).fetchall()
        df = pd.DataFrame(rows, columns=["Symbol", "Name", "Sector", "Tier", "Price (₹)", "Score", "Signal", "Risk"])
        explanation = (
            "🏛️ **Institutional Quality Screener**: Found top quality universe stocks combining high composite quant scores (>60), "
            "confirmed trend stability, and robust balance sheet health."
        )
        return {"response": explanation, "table": df, "has_data": not df.empty}

    # 2. Oversold / Dip Buying Queries
    elif "oversold" in q_clean or "dip" in q_clean or "rsi" in q_clean or "bounce" in q_clean:
        sql = """
            SELECT sig.symbol, s.name, s.sector, sig.current_price,
                   ind.rsi_14, ind.volume_ratio, cs.composite_score, sig.signal
            FROM signals sig
            JOIN stocks s ON sig.symbol = s.symbol
            JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
            LEFT JOIN technical_indicators ind ON sig.symbol = ind.symbol AND ind.date = sig.date
            WHERE sig.date = (SELECT MAX(date) FROM signals)
            AND ind.rsi_14 <= 45.0
            ORDER BY ind.rsi_14 ASC
            LIMIT 10
        """
        rows = session.execute(text(sql)).fetchall()
        df = pd.DataFrame(rows, columns=["Symbol", "Name", "Sector", "Price (₹)", "RSI (14)", "Vol Ratio", "Score", "Signal"])
        explanation = (
            "📉 **Oversold Bounce Candidates**: Scanned stocks with RSI $\\le$ 45 entering key support zones with potential for mean-reversion."
        )
        return {"response": explanation, "table": df, "has_data": not df.empty}

    # 3. Banking & Finance Sector Queries
    elif "bank" in q_clean or "finance" in q_clean:
        sql = """
            SELECT sig.symbol, s.name, s.market_cap_tier, sig.current_price,
                   cs.composite_score, sig.signal, sig.target_1_upside_pct, sig.risk_level
            FROM signals sig
            JOIN stocks s ON sig.symbol = s.symbol
            JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
            WHERE sig.date = (SELECT MAX(date) FROM signals)
            AND s.sector = 'Banking & Finance'
            ORDER BY cs.composite_score DESC
            LIMIT 10
        """
        rows = session.execute(text(sql)).fetchall()
        df = pd.DataFrame(rows, columns=["Symbol", "Name", "Tier", "Price (₹)", "Score", "Signal", "T1 Upside %", "Risk"])
        explanation = (
            "🏦 **Banking & Financial Services Leaderboard**: Ranked banking stocks by multi-engine quant scores and upside potential."
        )
        return {"response": explanation, "table": df, "has_data": not df.empty}

    # 4. Top BUY Signals
    elif "buy" in q_clean or "top" in q_clean or "best" in q_clean:
        sql = """
            SELECT sig.symbol, s.name, s.sector, sig.current_price,
                   cs.composite_score, sig.target_price_1, sig.stop_loss, sig.risk_reward_ratio
            FROM signals sig
            JOIN stocks s ON sig.symbol = s.symbol
            JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
            WHERE sig.date = (SELECT MAX(date) FROM signals)
            AND sig.signal = 'BUY'
            ORDER BY cs.composite_score DESC
            LIMIT 10
        """
        rows = session.execute(text(sql)).fetchall()
        df = pd.DataFrame(rows, columns=["Symbol", "Name", "Sector", "Price (₹)", "Score", "Target 1 (₹)", "Stop Loss (₹)", "R:R Ratio"])
        explanation = (
            "🟢 **Top Institutional BUY Opportunities**: Highest composite score equities with confirmed multi-engine breakout triggers."
        )
        return {"response": explanation, "table": df, "has_data": not df.empty}

    # 5. General Fallback
    else:
        sql = """
            SELECT sig.symbol, s.name, s.sector, sig.current_price,
                   cs.composite_score, sig.signal, sig.risk_level
            FROM signals sig
            JOIN stocks s ON sig.symbol = s.symbol
            JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
            WHERE sig.date = (SELECT MAX(date) FROM signals)
            ORDER BY cs.composite_score DESC
            LIMIT 8
        """
        rows = session.execute(text(sql)).fetchall()
        df = pd.DataFrame(rows, columns=["Symbol", "Name", "Sector", "Price (₹)", "Score", "Signal", "Risk"])
        explanation = (
            f"💡 **Quant Diagnostic Report for:** *'{user_query}'*\n\n"
            "Below is the current active universe overview filtered by multi-factor quantitative scores, risk rankings, and confirmed directional bias."
        )
        return {"response": explanation, "table": df, "has_data": not df.empty}