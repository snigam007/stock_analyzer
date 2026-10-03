import re
from pathlib import Path

target_file = Path(r"c:\Users\SNigam2\.gemini\antigravity\scratch\stock_analyzer\pages\14_Watchlist_and_Alerts.py")
content = target_file.read_text(encoding="utf-8")

# 1. Update imports
old_imp = """from core.watchlist_manager import (
    get_all_watchlists, create_watchlist, update_watchlist, delete_watchlist,
    get_watchlist_items, add_item_to_watchlist, update_watchlist_item, remove_item_from_watchlist,
    get_52_week_high_low_radar, evaluate_and_generate_alerts, get_recent_alerts
)"""

new_imp = """from core.watchlist_manager import (
    get_all_watchlists, create_watchlist, update_watchlist, delete_watchlist,
    get_watchlist_items, add_item_to_watchlist, update_watchlist_item, remove_item_from_watchlist,
    get_52_week_high_low_radar, evaluate_and_generate_alerts, get_recent_alerts
)
from core.ui_components import (
    render_clean_html,
    generate_broker_order_clipboard,
    render_empty_defensive_state
)"""

if old_imp in content:
    content = content.replace(old_imp, new_imp)
    print("Updated imports.")

# 2. Add broker export in Tab 1 right before the dataframe or after the dataframe
table_code = """        st.dataframe(
            df_disp.style.format({
                "Price (₹)": "₹{:,.2f}",
                "1D Return %": "{:+.2f}%",
                "Score": "{:.1f}",
                "Target Buy (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) and x else "—",
                "Target Sell (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) and x else "—",
                "Dist to Buy %": lambda x: f"{x:+.2f}%" if pd.notnull(x) and x is not None else "—",
                "Stop Loss (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) and x else "—",
            }),
            use_container_width=True,
            height=380,
            hide_index=True
        )"""

broker_export_addon = """        st.dataframe(
            df_disp.style.format({
                "Price (₹)": "₹{:,.2f}",
                "1D Return %": "{:+.2f}%",
                "Score": "{:.1f}",
                "Target Buy (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) and x else "—",
                "Target Sell (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) and x else "—",
                "Dist to Buy %": lambda x: f"{x:+.2f}%" if pd.notnull(x) and x is not None else "—",
                "Stop Loss (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) and x else "—",
            }),
            use_container_width=True,
            height=380,
            hide_index=True
        )

        # ── Institutional Broker Order Exporter ──────────────────────────────
        with st.expander("📋 One-Click Broker Order Sheet (Zerodha / Groww)", expanded=False):
            st.caption("Generate formatted execution orders for all tracked assets in this watchlist.")
            b_orders = []
            for it in items:
                act = "BUY" if it.get("signal") == "BUY" else "WATCH"
                b_orders.append({
                    "symbol": it["symbol"],
                    "shares": 1,
                    "current_price": it.get("current_price", 0),
                    "action": act
                })
            generate_broker_order_clipboard(b_orders, label="📋 Copy Watchlist to Broker Clipboard")"""

if table_code in content:
    content = content.replace(table_code, broker_export_addon)
    print("Added broker order exporter to Tab 1.")

# 3. Replace empty states with render_empty_defensive_state
old_empty_1 = 'st.info(f"Watchlist \'{selected_wl_name}\' is currently empty. Add stocks above to begin tracking!")'
new_empty_1 = 'render_empty_defensive_state(title=f"Watchlist \'{selected_wl_name}\' is Empty", message="No stocks or instruments are currently tracked in this watchlist.", action_text="Use the \'Add Stock(s)\' panel above to add tickers or bulk import.")'

if old_empty_1 in content:
    content = content.replace(old_empty_1, new_empty_1)
    print("Replaced empty state 1.")

old_empty_2 = 'st.info("No stocks currently within 3.5% of 52W High.")'
new_empty_2 = 'render_empty_defensive_state(title="No 52W Breakouts Detected", message="No active stocks are currently within 3.5% of their 52-week high.", action_text="Check back after the next market session.")'

if old_empty_2 in content:
    content = content.replace(old_empty_2, new_empty_2)
    print("Replaced empty state 2.")

old_empty_3 = 'st.info("No stocks currently within 3.5% of 52W Low.")'
new_empty_3 = 'render_empty_defensive_state(title="No 52W Breakdown Distress", message="No active stocks are currently within 3.5% of their 52-week low.", action_text="Universe is trading above historic support levels.")'

if old_empty_3 in content:
    content = content.replace(old_empty_3, new_empty_3)
    print("Replaced empty state 3.")

old_empty_4 = 'st.info("No active alerts logged yet. Create watchlists with target prices or wait for 52W breakouts!")'
new_empty_4 = 'render_empty_defensive_state(title="No Active Alerts Logged", message="No price targets, 52W breakouts, or stop loss breaches have fired yet.", action_text="Click \'Re-evaluate All Alert Triggers Now\' or configure watchlist targets.")'

if old_empty_4 in content:
    content = content.replace(old_empty_4, new_empty_4)
    print("Replaced empty state 4.")

target_file.write_text(content, encoding="utf-8")
print("Patched 14_Watchlist_and_Alerts.py successfully.")
