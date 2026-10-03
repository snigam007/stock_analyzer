"""
Patch pages/8_Portfolio_Optimizer.py to consolidate 10 tabs into 4 institutional master workspaces
"""
import sys

filepath = 'pages/8_Portfolio_Optimizer.py'
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")

# We can find line boundaries:
# Tab 0: line 80 to 238
# Tab 1: line 239 to 293
# Tab 2: line 294 to 340
# Tab 3: line 341 to 361
# Tab 4: line 362 to 400
# Tab 5: line 401 to 437
# Tab 6: line 438 to 518
# Tab 7: line 519 to 578
# Tab 8: line 579 to 624
# Tab 9: line 625 to 771

tab_indices = []
for i, line in enumerate(lines):
    if line.strip().startswith('with tabs['):
        tab_indices.append(i)

print("Found tabs at indices:", tab_indices)

# Headers (lines 0 to tab_indices[0]-1)
# Note: we need to replace `tabs = st.tabs([...])`
header_lines = []
for i in range(tab_indices[0]):
    line = lines[i]
    if line.strip().startswith('tabs = st.tabs(['):
        # Stop before old tabs definition
        break
    header_lines.append(line)

header_code = "".join(header_lines)
# Add imports if not present
if "from core.ui_components import" not in header_code:
    header_code = header_code.replace(
        "from core.macro_regime import evaluate_macro_regime",
        "from core.macro_regime import evaluate_macro_regime\nfrom core.ui_components import render_clean_html, fmt_inr, generate_broker_order_clipboard"
    )

# Sanitize macro regime banner
header_code = header_code.replace(
    'st.markdown(f"""\n<div style="background: linear-gradient(90deg, #102130, #0c1822);',
    'render_clean_html(f"""\n<div style="background: linear-gradient(90deg, #102130, #0c1822);'
).replace('</div>\n""", unsafe_allow_html=True)', '</div>\n""")')

def extract_tab_body(start_idx, end_idx):
    # Skip the `with tabs[x]:` line itself
    body_lines = lines[start_idx+1:end_idx]
    # Unindent by 4 spaces
    unindented = []
    for line in body_lines:
        if line.startswith('    '):
            unindented.append(line[4:])
        else:
            unindented.append(line)
    return "".join(unindented)

bodies = []
for k in range(len(tab_indices)):
    start_i = tab_indices[k]
    end_i = tab_indices[k+1] if k+1 < len(tab_indices) else len(lines)
    bodies.append(extract_tab_body(start_i, end_i))

fn_names = [
    "render_mpt_frontier",
    "render_paper_ledger",
    "render_paper_execution",
    "render_trade_history",
    "render_tearsheet",
    "render_stress_test",
    "render_factor_attribution",
    "render_risk_parity",
    "render_mae_mfe",
    "render_kelly_sizing",
]

functions_code = []
for name, body in zip(fn_names, bodies):
    # Indent body by 4 spaces for function
    indented_body = "".join(["    " + l if l.strip() else l for l in body.splitlines(keepends=True)])
    functions_code.append(f"\ndef {name}():\n{indented_body}\n")

# In render_paper_ledger, let's add one-click broker export if positions exist
# We will do that in the output

assembly = [header_code]
assembly.extend(functions_code)

master_tabs_code = """
# ═══════════════════════════════════════════════════════════════════════════════
# Master Workspaces (Consolidated from 10 tabs into 4 institutional cockpits)
# ═══════════════════════════════════════════════════════════════════════════════
tab_paper, tab_opt, tab_risk, tab_tearsheet = st.tabs([
    "💼 Paper Portfolio & Execution",
    "📐 Optimization & Risk Parity",
    "🛡️ Risk & Crisis Stress-Test",
    "📊 Performance Tearsheet & Factors"
])

with tab_paper:
    sub_p1, sub_p2, sub_p3 = st.tabs(["📈 Live Portfolio Ledger", "⚡ 1-Click Order Execution", "📜 Realized Trade History"])
    with sub_p1:
        render_paper_ledger()
    with sub_p2:
        render_paper_execution()
    with sub_p3:
        render_trade_history()

with tab_opt:
    sub_o1, sub_o2 = st.tabs(["📐 Markowitz Efficient Frontier (MPT)", "🏰 Bridgewater Risk Parity & HRP"])
    with sub_o1:
        render_mpt_frontier()
    with sub_o2:
        render_risk_parity()

with tab_risk:
    sub_r1, sub_r2 = st.tabs(["🛡️ Black Swan Stress-Test", "⚠️ VaR, CVaR & Kelly Sizing"])
    with sub_r1:
        render_stress_test()
    with sub_r2:
        render_kelly_sizing()

with tab_tearsheet:
    sub_t1, sub_t2, sub_t3 = st.tabs(["📊 Hedge Fund Tearsheet", "🏛️ Factor Attribution", "🎯 MAE / MFE Analytics"])
    with sub_t1:
        render_tearsheet()
    with sub_t2:
        render_factor_attribution()
    with sub_t3:
        render_mae_mfe()
"""
assembly.append(master_tabs_code)

final_content = "".join(assembly)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(final_content)

print("Successfully refactored pages/8_Portfolio_Optimizer.py!")
