from pathlib import Path

target_file = Path(r"c:\Users\SNigam2\.gemini\antigravity\scratch\stock_analyzer\pages\18_Quantum_Engine.py")
content = target_file.read_text(encoding="utf-8")

# Add ui_components import
old_imp = "from core.hourly_fetcher import get_hourly_data_status, get_hourly_data"
new_imp = """from core.hourly_fetcher import get_hourly_data_status, get_hourly_data
from core.ui_components import (
    render_clean_html,
    generate_broker_order_clipboard,
    render_empty_defensive_state
)"""

if old_imp in content:
    content = content.replace(old_imp, new_imp)
    print("Added ui_components import.")

# Add clipboard copy button to Apex Swing trades
old_buttons = """        # Broker Export Buttons
        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            zerodha_csv = export_execution_plan_to_broker_csv(plan, "ZERODHA")
            st.download_button(
                label="📥 Export Zerodha Kite Basket CSV",
                data=zerodha_csv,
                file_name=f"apex_swing_zerodha_basket_{reg_info.get('date', 'today')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        with col_exp2:
            groww_csv = export_execution_plan_to_broker_csv(plan, "GROWW")
            st.download_button(
                label="📥 Export Groww / Excel Order Sheet CSV",
                data=groww_csv,
                file_name=f"apex_swing_groww_orders_{reg_info.get('date', 'today')}.csv",
                mime="text/csv",
                use_container_width=True
            )"""

new_buttons = """        # Broker Export & One-Click Clipboard
        col_exp1, col_exp2, col_exp3 = st.columns([1.2, 1.2, 1.6])
        with col_exp1:
            zerodha_csv = export_execution_plan_to_broker_csv(plan, "ZERODHA")
            st.download_button(
                label="📥 Zerodha Kite CSV",
                data=zerodha_csv,
                file_name=f"apex_swing_zerodha_basket_{reg_info.get('date', 'today')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        with col_exp2:
            groww_csv = export_execution_plan_to_broker_csv(plan, "GROWW")
            st.download_button(
                label="📥 Groww / Excel CSV",
                data=groww_csv,
                file_name=f"apex_swing_groww_orders_{reg_info.get('date', 'today')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        with col_exp3:
            b_orders = []
            for t in active_trades:
                b_orders.append({
                    "symbol": t["symbol"],
                    "shares": t.get("shares", 1),
                    "current_price": t.get("current_price", 0),
                    "action": t.get("order_action", "BUY")
                })
            generate_broker_order_clipboard(b_orders, label="📋 Copy Broker Orders (Zerodha/Groww)")"""

if old_buttons in content:
    content = content.replace(old_buttons, new_buttons)
    print("Replaced broker buttons with 3-way export.")

# Add else branch for active_trades
old_active_end = """        with col_exp3:
            b_orders = []
            for t in active_trades:
                b_orders.append({
                    "symbol": t["symbol"],
                    "shares": t.get("shares", 1),
                    "current_price": t.get("current_price", 0),
                    "action": t.get("order_action", "BUY")
                })
            generate_broker_order_clipboard(b_orders, label="📋 Copy Broker Orders (Zerodha/Groww)")

    st.markdown("---")"""

new_active_end = """        with col_exp3:
            b_orders = []
            for t in active_trades:
                b_orders.append({
                    "symbol": t["symbol"],
                    "shares": t.get("shares", 1),
                    "current_price": t.get("current_price", 0),
                    "action": t.get("order_action", "BUY")
                })
            generate_broker_order_clipboard(b_orders, label="📋 Copy Broker Orders (Zerodha/Groww)")
    else:
        render_empty_defensive_state(
            title="Capital Fully Protected in Overnight Parking",
            message="No high-conviction apex setups currently satisfy the strict 4-timeframe confluence threshold.",
            action_text="100% of capital is deployed into LiquidBees generating 6.5% overnight yield until next market cycle."
        )

    st.markdown("---")"""

if old_active_end in content:
    content = content.replace(old_active_end, new_active_end)
    print("Added defensive empty state for active_trades.")

target_file.write_text(content, encoding="utf-8")
print("Updated 18_Quantum_Engine.py successfully.")
