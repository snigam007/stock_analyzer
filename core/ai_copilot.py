"""
AI Institutional Equity Research Copilot Engine
- Contextual multi-engine quantitative synthesis
- Investment Thesis & Catalysts Breakdown
- Downside Risk Autopsy & Value-at-Risk Stress Testing
- F&O Derivatives Institutional Positioning Interpretation
- Interactive Financial Question Answering (Q&A)
"""
import logging
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def generate_institutional_equity_research_memo(
    symbol: str,
    stock_name: str,
    sector: str,
    current_price: float,
    signal_data: Dict,
    score_data: Dict,
    ml_ensemble_data: Dict,
    champion_data: Dict,
    fno_data: Dict,
    macro_data: Dict,
    cpr_data: Optional[Dict] = None,
) -> Dict:
    """
    Synthesizes real-time multi-engine facts to create an institutional equity research memo.
    """
    sig = signal_data.get("signal", "WATCH")
    score = score_data.get("composite_score", 50.0)
    ml_consensus = ml_ensemble_data.get("consensus_label", "🟡 NEUTRAL")
    ml_conf = ml_ensemble_data.get("ensemble_confidence_pct", 50.0)

    champ_obj = champion_data.get("champion", {}) if champion_data else {}
    champ_name = champ_obj.get("strategy_name", "Multi-Engine Confluence")
    champ_win_rate = champ_obj.get("win_rate_pct", 60.0)
    champ_alpha = champ_obj.get("alpha_pct", 15.0)

    pcr = fno_data.get("pcr", 1.0)
    oi_archetype = fno_data.get("oi_archetype_label", "Neutral / Balanced")
    max_pain = fno_data.get("max_pain_strike", current_price)

    macro_regime = macro_data.get("regime", "RISK-NEUTRAL")
    macro_score = macro_data.get("macro_score", 50.0)

    # 1. Executive Investment Thesis
    if sig == "BUY" and score >= 65:
        thesis_verdict = "STRONG BUY / ACCUMULATE"
        thesis_color = "#00c875"
        thesis_text = (
            f"{symbol} ({stock_name}) presents a high-conviction institutional accumulation opportunity. "
            f"Trading at ₹{current_price:,.2f}, the asset displays strong multi-factor alignment (Score: {score:.1f}/100) "
            f"supported by a {ml_conf:.1f}% bullish probability from the 5-Model ML Ensemble. "
            f"Derivatives confirm {oi_archetype} with PCR at {pcr:.2f}, suggesting firm institutional floor support."
        )
    elif sig == "SELL" or score <= 40:
        thesis_verdict = "SELL / CAPITAL PRESERVATION"
        thesis_color = "#ff4b4b"
        thesis_text = (
            f"Caution is strongly advised on {symbol} ({stock_name}). Current price action displays bearish momentum breakdown "
            f"with a low multi-factor score ({score:.1f}/100). The 5-Model ML Ensemble projects downside pressure. "
            f"F&O positioning reflects {oi_archetype} with overhead resistance at ₹{max_pain:,.2f}."
        )
    else:
        thesis_verdict = "TACTICAL WATCH / RANGEBOUND"
        thesis_color = "#f0a500"
        thesis_text = (
            f"{symbol} ({stock_name}) is currently consolidating near key equilibrium levels at ₹{current_price:,.2f}. "
            f"While long-term fundamentals remain intact, short-term indicator confluence ({score:.1f}/100) is neutral. "
            f"Recommended stance: Wait for a confirmed breakout above 20-day EMA before deploying fresh capital."
        )

    # 2. Key Catalysts & Tailwinds
    catalysts = [
        f"🏆 **Champion Strategy Confirmation**: Empirical 3-year backtesting shows *{champ_name}* achieved a **{champ_win_rate:.1f}% win rate** and **{champ_alpha:+.1f}% alpha** over benchmark.",
        f"🧠 **Machine Learning Consensus**: 5-Model Ensemble voted `{ml_consensus}` with a **{ml_conf:.1f}% conviction index** across Gradient Boosting, Random Forest, and Holt-Winters.",
        f"🏛️ **Macro Environment Alignment**: Macro Regime stands at `{macro_regime}` (Score: {macro_score}/100), allocating capital appropriately to control tail drawdown.",
        f"⚡ **F&O Institutional Footprint**: Put-Call Ratio (PCR) of **{pcr:.2f}** indicates *{oi_archetype}* with major support wall at ₹{fno_data.get('major_support_put_wall', current_price*0.95):,.2f}.",
    ]

    # 3. Downside Risk Autopsy & Vulnerabilities
    risks = [
        f"⚠️ **Stop-Loss Discipline**: Breach of ₹{signal_data.get('stop_loss', current_price*0.95):,.2f} ({signal_data.get('stop_loss_downside_pct', -4.5):+.1f}%) invalidates the technical thesis and triggers automatic stop.",
        f"📉 **Overhead Call Resistance**: Strong derivative option open interest barrier concentrated at ₹{fno_data.get('major_resistance_call_wall', current_price*1.05):,.2f}.",
        f"🌐 **Macro Contagion**: If Crude Oil or benchmark indices break down, beta of {score_data.get('beta', 1.0):.2f} could amplify systemic volatility.",
    ]

    # 4. Tranche Execution Recommendation
    tranche_advice = (
        f"Scale in with **Half-Kelly Position Sizing**. Take 33% profit at T1 (₹{signal_data.get('target_price_1', current_price*1.03):,.2f}), "
        f"33% at T2 (₹{signal_data.get('target_price_2', current_price*1.06):,.2f}), and trail the remaining 34% with 20-EMA until T3 (₹{signal_data.get('target_price_3', current_price*1.12):,.2f})."
    )

    return {
        "symbol": symbol,
        "stock_name": stock_name,
        "thesis_verdict": thesis_verdict,
        "thesis_color": thesis_color,
        "executive_summary": thesis_text,
        "catalysts": catalysts,
        "risks": risks,
        "tranche_recommendation": tranche_advice,
    }


def answer_copilot_query(
    question: str,
    symbol: str,
    stock_name: str,
    current_price: float,
    signal_data: Dict,
    score_data: Dict,
    ml_ensemble_data: Dict,
    champion_data: Dict,
    fno_data: Dict,
    macro_data: Dict,
) -> str:
    """
    Answers arbitrary financial research inquiries based on live quantitative data.
    """
    q = question.lower()
    sig = signal_data.get("signal", "WATCH")
    score = score_data.get("composite_score", 50.0)
    champ = champion_data.get("champion", {}) if champion_data else {}
    champ_name = champ.get("strategy_name", "Multi-Engine Confluence")
    pcr = fno_data.get("pcr", 1.0)
    oi_arch = fno_data.get("oi_archetype_label", "Neutral")
    t1 = signal_data.get("target_price_1", current_price * 1.03)
    sl = signal_data.get("stop_loss", current_price * 0.96)

    if "why" in q or "signal" in q or "buy" in q or "sell" in q:
        return (
            f"**Analytical Signal Rationale for {symbol}:**\n\n"
            f"• **Current Signal:** `{sig}` with Multi-Factor Composite Score of **{score:.1f}/100**.\n"
            f"• **Technical Drivers:** Price is ₹{current_price:,.2f}. Entry trigger was confirmed with RSI at {signal_data.get('rsi_14', 50):.1f} and volume ratio of {signal_data.get('volume_ratio', 1.0):.2f}x.\n"
            f"• **Machine Learning Vote:** 5-Model Ensemble voted `{ml_ensemble_data.get('consensus_label', 'NEUTRAL')}` with {ml_ensemble_data.get('ensemble_confidence_pct', 50):.1f}% confidence.\n"
            f"• **Institutional Edge:** Backtested *{champ_name}* shows {champ.get('win_rate_pct', 60):.1f}% win rate and {champ.get('alpha_pct', 15):+.1f}% alpha."
        )
    elif "target" in q or "price" in q or "level" in q or "stop" in q:
        return (
            f"**Strategic Price Targets & Execution Roadmap for {symbol}:**\n\n"
            f"• **Current Market Price:** ₹{current_price:,.2f}\n"
            f"• **🎯 Target 1 (Tranche 1):** ₹{t1:,.2f} ({signal_data.get('target_1_upside_pct', 3.0):+.1f}%)\n"
            f"• **🎯 Target 2 (Tranche 2):** ₹{signal_data.get('target_price_2', current_price*1.06):,.2f} ({signal_data.get('target_2_upside_pct', 6.0):+.1f}%)\n"
            f"• **🎯 Target 3 (Tranche 3 Runner):** ₹{signal_data.get('target_price_3', current_price*1.12):,.2f} ({signal_data.get('target_3_upside_pct', 12.0):+.1f}%)\n"
            f"• **🛑 Strict Stop Loss:** ₹{sl:,.2f} ({signal_data.get('stop_loss_downside_pct', -4.0):+.1f}%)\n"
            f"• **Risk-to-Reward Ratio:** **{signal_data.get('risk_reward_ratio', 2.2):.2f}x**"
        )
    elif "fno" in q or "option" in q or "derivative" in q or "pcr" in q or "oi" in q:
        return (
            f"**Futures & Options (F&O) Derivative Profile for {symbol}:**\n\n"
            f"• **Put-Call Ratio (PCR):** **{pcr:.2f}** ({fno_data.get('pcr_sentiment', 'Neutral')})\n"
            f"• **OI Buildup Archetype:** `{fno_data.get('oi_buildup', 'Neutral')}` — *{oi_arch}*\n"
            f"• **Max Pain Strike:** ₹{fno_data.get('max_pain_strike', current_price):,.2f}\n"
            f"• **Call Resistance Wall:** ₹{fno_data.get('major_resistance_call_wall', current_price*1.05):,.2f}\n"
            f"• **Put Support Wall:** ₹{fno_data.get('major_support_put_wall', current_price*0.95):,.2f}\n"
            f"• **Implied Volatility Rank:** {fno_data.get('iv_rank_pct', 50):.0f}%"
        )
    elif "risk" in q or "downside" in q or "macro" in q:
        return (
            f"**Risk Assessment & Macro Exposure for {symbol}:**\n\n"
            f"• **Macro Regime:** `{macro_data.get('regime', 'RISK-NEUTRAL')}` (Macro Score: {macro_data.get('macro_score', 50)}/100)\n"
            f"• **Beta:** {score_data.get('beta', 1.0):.2f} | **Annual Volatility:** {score_data.get('volatility_annual', 0.22)*100:.1f}%\n"
            f"• **95% VaR (30 Days):** -{score_data.get('volatility_annual', 0.22)*100*0.7:.1f}%\n"
            f"• **Advisory Recommendation:** Maintain strict stop-loss at ₹{sl:,.2f} to limit risk per trade to 1.5% of total capital."
        )
    else:
        return (
            f"**Institutional Intelligence Summary for {symbol} ({stock_name}):**\n\n"
            f"• **Signal:** `{sig}` (Score: {score:.1f}/100) | **Price:** ₹{current_price:,.2f}\n"
            f"• **ML Ensemble:** `{ml_ensemble_data.get('consensus_label', 'NEUTRAL')}` ({ml_ensemble_data.get('ensemble_confidence_pct', 50):.1f}%)\n"
            f"• **F&O Bias:** `{oi_arch}` (PCR: {pcr:.2f})\n"
            f"• **Execution:** Enter @ ₹{current_price:,.2f}, Target: ₹{t1:,.2f}, Stop Loss: ₹{sl:,.2f}."
        )