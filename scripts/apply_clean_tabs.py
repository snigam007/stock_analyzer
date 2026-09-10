import re
from pathlib import Path

content = Path("app/pages/4_Daily_Top_Stocks.py").read_text(encoding="utf-8")

# 1. Replace the old tabs declaration
old_tabs_pattern = r"tabs\s*=\s*st\.tabs\(\[\s*\"🟢 Top BUY Stocks\"[\s\S]*?\"⚡ Pairs Trading & Stat Arb\"\s*\]\)"
m_old = re.search(old_tabs_pattern, content)
if not m_old:
    print("Could not find old tabs declaration")
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

header = content[:m_old.start()] + new_deck_decl
remaining = content[m_old.end():]

# Find all tabs in remaining
matches = list(re.finditer(r"^with tabs\[(\d+)\]:\s*$", remaining, re.MULTILINE))

tab_mapping = {
    0: ('"🎯 Core Stock Signals"', 'tab_buy'),
    1: ('"🎯 Core Stock Signals"', 'tab_sell'),
    2: ('"🌐 Multi-Asset & Breakouts"', 'tab_idx'),
    3: ('"🌐 Multi-Asset & Breakouts"', 'tab_comm'),
    4: ('"🌐 Multi-Asset & Breakouts"', 'tab_cpr'),
    5: ('"🎯 Core Stock Signals"', 'tab_safe'),
    6: ('"🎯 Core Stock Signals"', 'tab_risky'),
    7: ('"🎯 Core Stock Signals"', 'tab_watch'),
    8: ('"🐋 Institutional & Derivatives"', 'tab_audit'),
    9: ('"🐋 Institutional & Derivatives"', 'tab_scr'),
    10: ('"🌐 Multi-Asset & Breakouts"', 'tab_mtf'),
    11: ('"🐋 Institutional & Derivatives"', 'tab_opt'),
    12: ('"🐋 Institutional & Derivatives"', 'tab_sm'),
    13: ('"🐋 Institutional & Derivatives"', 'tab_pairs'),
}

# The text between m_old.end() and matches[0].start() belongs to the middle section (e.g. COMMODITY_NAMES, helper funcs)
middle_section = remaining[:matches[0].start()]

transformed_blocks = []
for i, m in enumerate(matches):
    tab_num = int(m.group(1))
    deck_cat, tab_var = tab_mapping[tab_num]
    start_body = m.end()
    end_body = matches[i+1].start() if i + 1 < len(matches) else len(remaining)
    body = remaining[start_body:end_body]

    # Indent body by 4 spaces
    indented_body_lines = []
    for line in body.splitlines(keepends=True):
        if line.strip():
            indented_body_lines.append("    " + line)
        else:
            indented_body_lines.append(line)
    indented_body = "".join(indented_body_lines)

    block = f"if deck_category == {deck_cat}:\n    with {tab_var}:{indented_body}"
    transformed_blocks.append(block)

final_code = header + middle_section + "".join(transformed_blocks)

out_file = Path("app/pages/4_Daily_Top_Stocks.py")
out_file.write_text(final_code, encoding="utf-8")
print("Transformed app/pages/4_Daily_Top_Stocks.py successfully!")
