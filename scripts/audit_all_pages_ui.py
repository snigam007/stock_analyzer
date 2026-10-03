"""
scripts/audit_all_pages_ui.py
=============================
Scans all pages in pages/ to extract:
- Page title & header
- Tabs defined in each page
- Visual components (Plotly, metrics, tables, dataframes, forms)
- Styling patterns & potential UI debt
"""
import os
import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT_DIR / "pages"

def audit_pages():
    results = {}
    py_files = sorted(PAGES_DIR.glob("*.py"))
    
    for pf in py_files:
        content = pf.read_text(encoding="utf-8", errors="ignore")
        
        # Extract title
        title_match = re.search(r'st\.(?:header|title|subheader)\((["\'])(.*?)\1', content)
        title = title_match.group(2) if title_match else pf.stem
        
        # Extract tabs
        tabs_matches = re.findall(r'st\.tabs\(\s*\[(.*?)\]\s*\)', content, re.DOTALL)
        tab_list = []
        for tm in tabs_matches:
            # extract string literals in list
            raw_tabs = re.findall(r'["\'](.*?)["\']', tm)
            tab_list.extend(raw_tabs)
            
        # Count UI elements
        metrics_count = len(re.findall(r'st\.metric\(', content))
        plotly_count = len(re.findall(r'st\.plotly_chart\(', content))
        tables_count = len(re.findall(r'st\.(?:dataframe|table)\(', content))
        raw_html_count = len(re.findall(r'unsafe_allow_html\s*=\s*True', content))
        columns_count = len(re.findall(r'st\.columns\(', content))
        expander_count = len(re.findall(r'st\.expander\(', content))
        
        # Check potential UI issues
        raw_comment_leak = bool(re.search(r'<!--.*?-->', content))
        fixed_height_charts = re.findall(r'height\s*=\s*(\d+)', content)
        
        results[pf.name] = {
            "title": title,
            "tabs": tab_list,
            "metrics": metrics_count,
            "plotly_charts": plotly_count,
            "tables": tables_count,
            "raw_html": raw_html_count,
            "columns": columns_count,
            "expanders": expander_count,
            "raw_comment_leak": raw_comment_leak,
            "chart_heights": [int(h) for h in fixed_height_charts[:10]],
            "lines": len(content.splitlines())
        }
    
    return results

if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    res = audit_pages()
    for name, d in res.items():
        print(f"\n📄 {name} ({d['lines']} lines) - Title: {d['title']}")
        if d['tabs']:
            print(f"   📑 Tabs ({len(d['tabs'])}): {', '.join(d['tabs'][:8])}")
        else:
            print("   📑 Tabs: None (Single Flow)")
        print(f"   📊 UI Components: {d['metrics']} Metrics, {d['plotly_charts']} Charts, {d['tables']} Tables, {d['columns']} Column Blocks, {d['expanders']} Expanders, {d['raw_html']} HTML Blocks")
        if d['raw_comment_leak']:
            print("   ⚠️ Has raw HTML comments (potential Markdown leakage risk)")
