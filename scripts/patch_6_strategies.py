from pathlib import Path

target_file = Path(r"c:\Users\SNigam2\.gemini\antigravity\scratch\stock_analyzer\pages\6_Strategies.py")
content = target_file.read_text(encoding="utf-8")

# 1. Update imports
old_imp = "from core.apex_swing_engine import check_nifty_regime, scan_apex_swing_candidates, generate_apex_swing_execution_plan"
new_imp = """from core.apex_swing_engine import check_nifty_regime, scan_apex_swing_candidates, generate_apex_swing_execution_plan
from core.ui_components import (
    render_clean_html,
    generate_broker_order_clipboard,
    render_empty_defensive_state,
    fmt_inr
)"""

if old_imp in content:
    content = content.replace(old_imp, new_imp)
    print("Updated imports.")

# 2. Add broker export under execution orders in Tab 0
target_after_orders = """    if exec_plan['liquidbees_sweep']['active']:
        st.markdown(f\"\"\"
        <div style="background: rgba(245, 158, 11, 0.1); border: 1px dashed #f59e0b; border-radius: 8px; padding: 12px 18px; margin-top: 10px; margin-bottom: 20px;">
            <span style="font-weight: bold; color: #f59e0b;">🛡️ Bear Fortress Cash Sweep Order:</span>
            <span style="color: #e2e8f0; margin-left: 8px;">Allocate remaining <b>₹{exec_plan['liquidbees_sweep']['sweep_capital']:,.2f}</b> into <b>LIQUIDBEES</b>. Accrues ~6.5% risk-free annualized yield while keeping capital 100% liquid for instant deployment when NIFTY reclaims its 21/50 EMAs.</span>
        </div>
        \"\"\", unsafe_allow_html=True)"""

broker_export_block = """    # ── Broker One-Click Exporter ──────────────────────────────────────────
    if exec_plan["active_trades"]:
        b_orders = []
        for tr in exec_plan["active_trades"]:
            act = "SELL" if tr.get("side") == "SHORT" else "BUY"
            b_orders.append({
                "symbol": tr["symbol"],
                "shares": tr.get("shares", 1),
                "current_price": tr.get("current_price", 0),
                "action": act
            })
        generate_broker_order_clipboard(b_orders, label="📋 Copy Apex Swing Orders (Zerodha / Groww)")

    if exec_plan['liquidbees_sweep']['active']:
        render_clean_html(f\"\"\"
        <div style="background: rgba(245, 158, 11, 0.1); border: 1px dashed #f59e0b; border-radius: 8px; padding: 12px 18px; margin-top: 10px; margin-bottom: 20px;">
            <span style="font-weight: bold; color: #f59e0b;">🛡️ Bear Fortress Cash Sweep Order:</span>
            <span style="color: #e2e8f0; margin-left: 8px;">Allocate remaining <b>₹{exec_plan['liquidbees_sweep']['sweep_capital']:,.2f}</b> into <b>LIQUIDBEES</b>. Accrues ~6.5% risk-free annualized yield while keeping capital 100% liquid for instant deployment when NIFTY reclaims its 21/50 EMAs.</span>
        </div>
        \"\"\")"""

if target_after_orders in content:
    content = content.replace(target_after_orders, broker_export_block)
    print("Added broker order exporter and updated liquidbees banner.")

# 3. Defensive empty state when no active trades
old_no_trades = """    if not exec_plan["active_trades"]:
        st.info("No candidates currently pass the strict screening criteria. Remaining in 100% Cash / LiquidBees preservation mode.")"""

new_no_trades = """    if not exec_plan["active_trades"]:
        render_empty_defensive_state(
            title="Capital Fully Protected in LiquidBees",
            message="No stock candidates currently pass the strict multi-lookback momentum, trend, and RSI screening criteria.",
            action_text="100% of capital is parked in LiquidBees earning ~6.5% overnight yield."
        )"""

if old_no_trades in content:
    content = content.replace(old_no_trades, new_no_trades)
    print("Replaced no trades info with defensive state.")

target_file.write_text(content, encoding="utf-8")
print("Updated 6_Strategies.py successfully.")
