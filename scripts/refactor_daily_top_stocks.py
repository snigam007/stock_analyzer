import re
from pathlib import Path

target = Path("app/pages/4_Daily_Top_Stocks.py")
content = target.read_text(encoding="utf-8")

# 1. Replace the giant tabs = st.tabs([...]) block
old_tabs_decl = re.search(r"tabs\s*=\s*st\.tabs\(\[\s*\"🟢 Top BUY Stocks\"[\s\S]*?\"⚡ Pairs Trading & Stat Arb\"\s*\]\)", content)
if not old_tabs_decl:
    print("Could not find old_tabs_decl")
    exit(1)

new_deck_decl = '''st.markdown("""
<style>
    div[data-testid="stSegmentedControl"] {
        margin-bottom: 12px;
    }
</style>
""", unsafe_allow_html=True)

deck_category = st.segmented_control(
    "Signal Deck",
    options=["🎯 Core Stock Signals", "🌐 Multi-Asset & Breakouts", "🐋 Institutional & Derivatives"],
    default="🎯 Core Stock Signals",
    label_visibility="collapsed"
)

if deck_category == "🎯 Core Stock Signals":
    tab_buy, tab_sell, tab_safe, tab_risky, tab_watch = st.tabs([
        "🟢 Top BUY Stocks",
        "🔴 SELL Alerts",
        "🛡️ Safe Investments",
        "⚡ Risky Plays",
        "🟡 Watchlist"
    ])
elif deck_category == "🌐 Multi-Asset & Breakouts":
    tab_idx, tab_comm, tab_cpr, tab_mtf = st.tabs([
        "📊 Index Signals",
        "🪙 Commodity Signals",
        "⚡ CPR & VSA Breakouts",
        "💎 MTF Confluence"
    ])
else:
    tab_sm, tab_opt, tab_pairs, tab_scr, tab_audit = st.tabs([
        "🐋 Smart Money Footprint",
        "⚡ Option Chain & Max Pain",
        "⚡ Pairs Trading & Stat Arb",
        "🎯 Custom Screener & Presets",
        "🎯 Signal Accuracy & Audit"
    ])'''

content = content[:old_tabs_decl.start()] + new_deck_decl + content[old_tabs_decl.end():]

# 2. Replace each `with tabs[X]:` with `if deck_category == ...: with tab_XYZ:`
replacements = [
    ('with tabs[0]:', 'if deck_category == "🎯 Core Stock Signals":\n    with tab_buy:'),
    ('with tabs[1]:', 'if deck_category == "🎯 Core Stock Signals":\n    with tab_sell:'),
    ('with tabs[2]:', 'if deck_category == "🌐 Multi-Asset & Breakouts":\n    with tab_idx:'),
    ('with tabs[3]:', 'if deck_category == "🌐 Multi-Asset & Breakouts":\n    with tab_comm:'),
    ('with tabs[4]:', 'if deck_category == "🌐 Multi-Asset & Breakouts":\n    with tab_cpr:'),
    ('with tabs[5]:', 'if deck_category == "🎯 Core Stock Signals":\n    with tab_safe:'),
    ('with tabs[6]:', 'if deck_category == "🎯 Core Stock Signals":\n    with tab_risky:'),
    ('with tabs[7]:', 'if deck_category == "🎯 Core Stock Signals":\n    with tab_watch:'),
    ('with tabs[8]:', 'if deck_category == "🐋 Institutional & Derivatives":\n    with tab_audit:'),
    ('with tabs[9]:', 'if deck_category == "🐋 Institutional & Derivatives":\n    with tab_scr:'),
    ('with tabs[10]:', 'if deck_category == "🌐 Multi-Asset & Breakouts":\n    with tab_mtf:'),
    ('with tabs[11]:', 'if deck_category == "🐋 Institutional & Derivatives":\n    with tab_opt:'),
    ('with tabs[12]:', 'if deck_category == "🐋 Institutional & Derivatives":\n    with tab_sm:'),
    ('with tabs[13]:', 'if deck_category == "🐋 Institutional & Derivatives":\n    with tab_pairs:'),
]

for old_s, new_s in replacements:
    if old_s not in content:
        print(f"Error: {old_s} not found!")
        exit(1)
    content = content.replace(old_s, new_s, 1)

target.write_text(content, encoding="utf-8")
print("Successfully refactored app/pages/4_Daily_Top_Stocks.py")
