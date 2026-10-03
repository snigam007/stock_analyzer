import re
from pathlib import Path

target_file = Path(r"c:\Users\SNigam2\.gemini\antigravity\scratch\stock_analyzer\pages\11_Portfolio_Advisor.py")
content = target_file.read_text(encoding="utf-8")

# 1. Fix the top try/except block
old_top = """try:
    st.set_page_config(page_title="Institutional Portfolio Advisor", page_icon="💼", layout="wide")
    
    import importlib
    import core.portfolio_analyzer
    importlib.reload(core.portfolio_analyzer)
    
    from db.database import get_global_engine, get_session
    from sqlalchemy import text
    from core.portfolio_advisor import generate_institutional_portfolio
    from core.portfolio_optimizer import execute_paper_buy
    from core.macro_regime import evaluate_macro_regime
    from core.portfolio_analyzer import (
        parse_portfolio_text,
        parse_portfolio_csv,
        analyze_custom_portfolio,
        get_searchable_assets_catalog
    )
except Exception:
    pass"""

new_top = """try:
    st.set_page_config(page_title="Institutional Portfolio Advisor", page_icon="💼", layout="wide")
except Exception:
    pass

import importlib
import core.portfolio_analyzer
importlib.reload(core.portfolio_analyzer)

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.portfolio_advisor import generate_institutional_portfolio
from core.portfolio_optimizer import execute_paper_buy
from core.macro_regime import evaluate_macro_regime
from core.portfolio_analyzer import (
    parse_portfolio_text,
    parse_portfolio_csv,
    analyze_custom_portfolio,
    get_searchable_assets_catalog
)
from core.ui_components import (
    render_clean_html,
    fmt_inr,
    generate_broker_order_clipboard,
    render_empty_defensive_state
)"""

if old_top in content:
    content = content.replace(old_top, new_top)
    print("Replaced top block successfully.")
else:
    print("WARNING: Top block not found exactly as expected.")

# 2. Fix macro regime banner to use render_clean_html
old_macro_banner = """st.markdown(f\"\"\"
<div style="background: #101c28; border-left: 4px solid #38bdf8; padding: 10px 16px; border-radius: 6px; margin-bottom: 15px;">
    <span style="font-weight: bold; color: #38bdf8;">🏛️ Current Macro Regime: {macro_info['regime']} (Score: {macro_info['macro_score']}/100)</span> &nbsp;•&nbsp; 
    <span style="color: #cbd5e1; font-size: 0.9em;">Recommended Strategic Tilt: Equities <b>{macro_info['recommended_allocation']['Equities %']}%</b> | Gold/Commodities <b>{macro_info['recommended_allocation']['Gold & Commodities %']}%</b> | Cash <b>{macro_info['recommended_allocation']['Cash & Liquid %']}%</b></span>
</div>
\"\"\", unsafe_allow_html=True)"""

new_macro_banner = """render_clean_html(f\"\"\"
<div style="background: #101c28; border-left: 4px solid #00eefc; padding: 12px 18px; border-radius: 8px; margin-bottom: 16px; box-shadow: 0 4px 14px rgba(0,238,252,0.06);">
    <span style="font-weight: bold; color: #00eefc; font-size: 1.02em;">🏛️ Current Macro Regime: {macro_info['regime']} (Score: {macro_info['macro_score']}/100)</span> &nbsp;•&nbsp; 
    <span style="color: #cbd5e1; font-size: 0.9em;">Recommended Strategic Tilt: Equities <b style="color: #00ff66;">{macro_info['recommended_allocation']['Equities %']}%</b> | Gold/Commodities <b style="color: #f59e0b;">{macro_info['recommended_allocation']['Gold & Commodities %']}%</b> | Cash <b style="color: #38bdf8;">{macro_info['recommended_allocation']['Cash & Liquid %']}%</b></span>
</div>
\"\"\")"""

if old_macro_banner in content:
    content = content.replace(old_macro_banner, new_macro_banner)
    print("Replaced macro banner successfully.")

# 3. Fix unindented lines 673-810 in tab_model_port
# Look for the boundary where de-indentation happened:
split_marker = "# ── Asset Class & Sector Allocation Donut Charts ─────────────────────────────"
if split_marker in content:
    pre_split, post_split = content.split(split_marker, 1)
    
    # We want post_split to be indented with 4 spaces for each line, and before the table or action buttons, add broker export!
    # Let's inspect post_split
    lines = post_split.splitlines()
    indented_lines = []
    for line in lines:
        if line.strip():
            indented_lines.append("    " + line)
        else:
            indented_lines.append("")
    
    rebuilt_post = "\n".join(indented_lines)
    
    # Also in action buttons:
    old_buttons = """    act_col1, act_col2, act_col3 = st.columns([1.5, 1.5, 2])"""
    new_buttons = """    act_col1, act_col2, act_col3, act_col4 = st.columns([1.2, 1.2, 1.3, 1.5])"""
    
    broker_btn_code = """
    with act_col4:
        broker_order_items = []
        for it in portfolio.get("assets", []):
            if it.get("shares_to_buy", 0) > 0:
                broker_order_items.append({
                    "symbol": it["symbol"],
                    "shares": it["shares_to_buy"],
                    "current_price": it.get("current_price", 0),
                    "action": "BUY"
                })
        if broker_order_items:
            generate_broker_order_clipboard(broker_order_items, label="📋 Copy Broker Orders (Zerodha / Groww)")
        else:
            st.info("No active equity share allocations to export.")
"""
    
    if old_buttons in rebuilt_post:
        rebuilt_post = rebuilt_post.replace(old_buttons, new_buttons)
        # Add act_col4 after act_col3 block
        act_col3_marker = "st.success(f\"✅ Mandate #{mid} saved! You can follow live trailing stops and daily shift alerts in Page 16.\")"
        if act_col3_marker in rebuilt_post:
            rebuilt_post = rebuilt_post.replace(act_col3_marker, act_col3_marker + "\n" + broker_btn_code)
            print("Added broker order export button to Tab 3.")
    
    content = pre_split + "    " + split_marker + "\n" + rebuilt_post
    print("Indented Tab 3 content successfully.")
else:
    print("WARNING: split_marker not found!")

target_file.write_text(content, encoding="utf-8")
print("Updated 11_Portfolio_Advisor.py successfully.")
