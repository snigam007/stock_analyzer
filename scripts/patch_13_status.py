from pathlib import Path

target_file = Path(r"c:\Users\SNigam2\.gemini\antigravity\scratch\stock_analyzer\pages\13_Data_Refresh_Status.py")
content = target_file.read_text(encoding="utf-8")

# 1. Update imports
old_imp = """from core.data_status import (
    get_database_status_summary,
    get_daily_stock_counts_history,
    get_searchable_universe_directory,
)"""

new_imp = """from core.data_status import (
    get_database_status_summary,
    get_daily_stock_counts_history,
    get_searchable_universe_directory,
)
from core.ui_components import (
    render_clean_html,
    fmt_inr,
    render_empty_defensive_state
)"""

if old_imp in content:
    content = content.replace(old_imp, new_imp)
    print("Updated imports.")

# 2. Top Refresh Banner using render_clean_html
old_banner = """# Top Refresh Banner
st.markdown(f\"\"\"
<div class="status-card">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
        <div>
            <span style="font-size: 1.25em; font-weight: bold; color: #00c875;">
                📅 Data Refresh Date: {summary['max_date']} (Latest Market Close Session)
            </span><br>
            <span style="font-size: 0.95em; color: #c8d0d8;">
                Telemetry Status: <b>{summary['status_badge']}</b> • <b>{summary['latest_session_stock_count']}</b> / <b>{summary['stock_count']}</b> Equities Active • <b>{summary['total_bars']:,}</b> Total Historical Bars
            </span>
        </div>
        <div style="text-align: right; margin-top: 6px;">
            <span style="background-color: #238636; color: white; padding: 5px 12px; border-radius: 16px; font-weight: 600; font-size: 0.85em;">
                ⚡ Auto-Refresh Scheduled: 08:00 AM IST
            </span>
        </div>
    </div>
</div>
\"\"\", unsafe_allow_html=True)"""

new_banner = """# Top Refresh Banner
render_clean_html(f\"\"\"
<div style="background: linear-gradient(90deg, #101c28, #0e141e); border: 1px solid rgba(0,255,102,0.25); border-left: 5px solid #00ff66; padding: 14px 20px; border-radius: 8px; margin-bottom: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.3);">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
        <div>
            <span style="font-size: 1.25em; font-weight: bold; color: #00ff66;">
                📅 Data Refresh Date: {summary['max_date']} (Latest Market Close Session)
            </span><br>
            <span style="font-size: 0.92em; color: #cbd5e1; font-family: 'JetBrains Mono', monospace;">
                Telemetry Status: <b style="color: #00eefc;">{summary['status_badge']}</b> • <b style="color: #00ff66;">{summary['latest_session_stock_count']}</b> / <b>{summary['stock_count']}</b> Equities Active • <b>{summary['total_bars']:,}</b> Total Historical Bars
            </span>
        </div>
        <div style="text-align: right;">
            <span style="background: rgba(0, 255, 102, 0.15); border: 1px solid #00ff66; color: #00ff66; padding: 5px 12px; border-radius: 16px; font-weight: 700; font-size: 0.85em; font-family: 'JetBrains Mono', monospace;">
                ⚡ Auto-Refresh Scheduled: 08:00 AM IST
            </span>
        </div>
    </div>
</div>
\"\"\")"""

if old_banner in content:
    content = content.replace(old_banner, new_banner)
    print("Replaced top banner.")

# 3. Summary pills
old_pills = """# Summary pills
cat_counts = filtered_df["asset_type"].value_counts().to_dict()
st.markdown(f\"\"\"
<div style="margin-bottom: 10px;">
    <b>Matching Results: {len(filtered_df)} Assets</b> • 
    <span class="badge-stock">🏢 {cat_counts.get('Stock', 0)} Stocks</span> • 
    <span class="badge-index">📊 {cat_counts.get('Index', 0)} Indexes</span> • 
    <span class="badge-commodity">🪙 {cat_counts.get('Commodity', 0)} Commodities</span>
</div>
\"\"\", unsafe_allow_html=True)"""

new_pills = """# Summary pills
cat_counts = filtered_df["asset_type"].value_counts().to_dict()
render_clean_html(f\"\"\"
<div style="margin-bottom: 12px; font-family: 'JetBrains Mono', monospace; font-size: 0.9em; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
    <b style="color: #f8fafc;">Matching Results: {len(filtered_df)} Assets</b> • 
    <span style="background: rgba(56,189,248,0.15); border: 1px solid #38bdf8; color: #38bdf8; padding: 2px 8px; border-radius: 4px; font-weight: 700;">🏢 {cat_counts.get('Stock', 0)} Stocks</span> • 
    <span style="background: rgba(168,85,247,0.15); border: 1px solid #a855f7; color: #c084fc; padding: 2px 8px; border-radius: 4px; font-weight: 700;">📊 {cat_counts.get('Index', 0)} Indexes</span> • 
    <span style="background: rgba(245,158,11,0.15); border: 1px solid #f59e0b; color: #fbbf24; padding: 2px 8px; border-radius: 4px; font-weight: 700;">🪙 {cat_counts.get('Commodity', 0)} Commodities</span>
</div>
\"\"\")"""

if old_pills in content:
    content = content.replace(old_pills, new_pills)
    print("Replaced summary pills.")

target_file.write_text(content, encoding="utf-8")
print("Updated 13_Data_Refresh_Status.py successfully.")
