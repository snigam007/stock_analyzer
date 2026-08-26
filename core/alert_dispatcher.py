"""
Automated Telegram / Discord Morning Briefing & Trade Alert Dispatcher
- Generates 8:45 AM IST Pre-Market Morning Intelligence Briefing
- Formats High-Probability Trade Trigger Alerts & Stop Loss notifications
- Dispatches webhooks directly to Telegram Bot API or Discord Webhook URLs
"""
import logging
import json
import urllib.request
import urllib.error
from typing import Dict, List, Optional
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def generate_morning_briefing(session: Session) -> Dict:
    """
    Generates a pre-market morning institutional briefing formatted for Telegram/Discord.
    """
    from core.macro_regime import evaluate_macro_regime
    from core.global_markets import analyze_global_market_spillovers

    macro = evaluate_macro_regime(session)
    global_mkt = analyze_global_market_spillovers(session)

    # Fetch Top 3 BUY Opportunities
    top_buys = session.execute(text("""
        SELECT sig.symbol, s.name, s.sector, sig.current_price,
               sig.target_price_1, sig.stop_loss, cs.composite_score
        FROM signals sig
        JOIN stocks s ON sig.symbol = s.symbol
        JOIN composite_scores cs ON sig.symbol = cs.symbol AND sig.date = cs.date
        WHERE sig.date = (SELECT MAX(date) FROM signals)
        AND sig.signal = 'BUY'
        ORDER BY cs.composite_score DESC
        LIMIT 3
    """)).fetchall()

    briefing_text = (
        f"☀️ **INDIAN MARKETS MORNING INTELLIGENCE BRIEFING**\n"
        f"📅 Date: {pd.Timestamp.now().strftime('%d %b %Y, %I:%M %p')}\n\n"
        f"🌐 **Global Overnight Sentiment:** {global_mkt.get('global_sentiment_index', 0):+.1f} / 100 ({global_mkt.get('sentiment_verdict', 'Neutral')})\n"
        f"🏛️ **Macro Market Regime:** {macro.get('regime', 'RISK-NEUTRAL')} (Score: {macro.get('macro_score', 50)}/100)\n"
        f"💼 **Advisory Allocation:** Equities: {macro['recommended_allocation']['Equities %']}% | Gold: {macro['recommended_allocation']['Gold & Commodities %']}% | Cash: {macro['recommended_allocation']['Cash & Liquid %']}%\n\n"
        f"🔥 **TOP HIGH-CONVICTION PICKS FOR TODAY:**\n"
    )

    for idx, b in enumerate(top_buys, start=1):
        sym, name, sec, price, t1, sl, sc = b
        t1_gain = ((t1 - price) / price * 100) if price and t1 else 3.5
        briefing_text += (
            f"  {idx}. **{sym}** ({name[:20]}) — ₹{price:,.2f}\n"
            f"     🎯 Target 1: ₹{t1:,.2f} (+{t1_gain:.1f}%) | 🛑 Stop Loss: ₹{sl:,.2f} | Score: {sc:.0f}/100\n"
        )

    briefing_text += (
        f"\n💡 *Strict Risk Protocol: Execute with 3-Tranche Scaling & Half-Kelly position sizing.*"
    )

    return {
        "title": "☀️ Indian Markets Morning Intelligence Briefing",
        "timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "raw_text": briefing_text,
        "global_sentiment": global_mkt.get("global_sentiment_index", 0),
        "macro_score": macro.get("macro_score", 50),
        "top_picks": [b[0] for b in top_buys],
    }


def send_webhook_alert(
    webhook_url: str,
    message_text: str,
    platform: str = "discord",
) -> Dict:
    """
    Sends message payload to Telegram Bot API or Discord Webhook.
    """
    if not webhook_url or not webhook_url.startswith("http"):
        return {"status": "ERROR", "message": "Invalid Webhook URL provided."}

    try:
        if platform.lower() == "discord":
            payload = json.dumps({"content": message_text}).encode("utf-8")
            headers = {"Content-Type": "application/json", "User-Agent": "StockAnalyzer/2.0"}
        elif platform.lower() == "telegram":
            # For Telegram webhook: URL should be https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=<TEXT>
            payload = json.dumps({"text": message_text, "parse_mode": "Markdown"}).encode("utf-8")
            headers = {"Content-Type": "application/json"}
        else:
            payload = json.dumps({"text": message_text}).encode("utf-8")
            headers = {"Content-Type": "application/json"}

        req = urllib.request.Request(webhook_url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as response:
            code = response.getcode()
            if code in [200, 204]:
                return {"status": "SUCCESS", "message": "Alert dispatched successfully!"}
            else:
                return {"status": "WARNING", "message": f"Server returned response code {code}"}

    except Exception as e:
        logger.error(f"Webhook dispatch error: {e}")
        return {"status": "ERROR", "message": str(e)}