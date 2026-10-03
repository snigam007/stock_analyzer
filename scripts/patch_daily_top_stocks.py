"""
Patch 4_Daily_Top_Stocks.py safely with utf-8 encoding
"""
import sys

filepath = 'pages/4_Daily_Top_Stocks.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Fix the try/except block around st.set_page_config
target_start = 'try:\n    st.set_page_config(page_title="Daily Top Stocks", page_icon="🏆", layout="wide")'
replacement_start = '''try:
    st.set_page_config(page_title="Daily Top Stocks", page_icon="🏆", layout="wide")
except Exception:
    pass

from core.ui_components import (
    render_clean_html, fmt_inr,
    render_empty_defensive_state,
    generate_broker_order_clipboard
)'''

if target_start in content:
    content = content.replace(target_start, replacement_start, 1)
    print("Replaced start block")
else:
    print("Target start not found")

# Remove trailing except block
target_end = '''    mtf_filter = st.sidebar.selectbox(
        "Multi-Timeframe Alignment (Quantum Swing)",
        ["All Alignments", "⚛️ Quad Confluence (1H+1D+1W+1M) Only", "⭐⭐⭐ Triple Confluence or Better", "⭐⭐ Core Confluence or Better", "Exclude Counter-Trend"],
        help="Filter stocks by cross-timeframe alignment across 1-Hour Sniper, Core Daily, Weekly Structural, and Macro trends."
    )
except Exception:
    champion_alpha_filter = False'''

replacement_end = '''    mtf_filter = st.sidebar.selectbox(
        "Multi-Timeframe Alignment (Quantum Swing)",
        ["All Alignments", "⚛️ Quad Confluence (1H+1D+1W+1M) Only", "⭐⭐⭐ Triple Confluence or Better", "⭐⭐ Core Confluence or Better", "Exclude Counter-Trend"],
        help="Filter stocks by cross-timeframe alignment across 1-Hour Sniper, Core Daily, Weekly Structural, and Macro trends."
    )'''

if target_end in content:
    content = content.replace(target_end, replacement_end, 1)
    print("Replaced end block")
else:
    print("Target end not found")

# Unindent lines between replacement_start and replacement_end
# We can do this line-by-line:
lines = content.splitlines(keepends=True)
new_lines = []
in_unindent_zone = False

for line in lines:
    if 'from core.ui_components import (' in line:
        in_unindent_zone = True
        new_lines.append(line)
        continue
    if in_unindent_zone and 'earnings_filter = st.sidebar.selectbox(' in line:
        in_unindent_zone = False
        new_lines.append(line)
        continue
    
    if in_unindent_zone:
        # If line starts with 4 spaces, unindent 4 spaces
        if line.startswith('    '):
            new_lines.append(line[4:])
        else:
            new_lines.append(line)
    else:
        new_lines.append(line)

content = "".join(new_lines)

# 2. Add broker order export & defensive empty state in render_stock_table
target_filter_check = '''    if not filtered_rows:
        st.warning(f"No stocks match the institutional filter criteria (MTF: '{mtf_filter}' | Earnings: '{earnings_filter}').")
        return'''

replacement_filter_check = '''    if not filtered_rows:
        render_empty_defensive_state(
            regime=macro_info.get("regime", "Risk-Off / Neutral") if "macro_info" in globals() else "Neutral",
            suggested_allocation={"LiquidBees / Cash": "80%", "Gold (GOLDBEES)": "20%"},
            message=f"No stocks match institutional filter criteria (MTF: '{mtf_filter}' | Earnings: '{earnings_filter}'). Preserving dry powder in liquid instruments."
        )
        return

    # One-click broker order exporter for actionable picks
    if show_signal:
        buy_orders = []
        for r in filtered_rows[:10]:
            sym = r[0]
            pr = float(r[8] or 0)
            sig_action = r[6]
            if sig_action == "BUY" and pr > 0:
                qty = max(1, int(25000 / pr))
                buy_orders.append({"symbol": sym, "qty": qty, "price": pr, "action": "BUY"})
        
        if buy_orders:
            with st.expander(f"📋 One-Click Zerodha / Groww Whole-Share Order Exporter ({len(buy_orders)} Picks)", expanded=False):
                generate_broker_order_clipboard(buy_orders, key_prefix=f"broker_export_{filtered_rows[0][0]}")'''

if target_filter_check in content:
    content = content.replace(target_filter_check, replacement_filter_check, 1)
    print("Replaced filter check & added broker order export")
else:
    print("Target filter check not found")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch complete!")
