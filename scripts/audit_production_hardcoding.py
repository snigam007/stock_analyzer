import sys, os, re, glob
sys.stdout.reconfigure(encoding='utf-8')

print("="*80)
print("PRODUCTION CODEBASE AUDIT: HARDCODED VALUES & ARCHITECTURAL IMPROVEMENT AREAS")
print("="*80)

core_files = glob.glob("core/*.py")
page_files = glob.glob("pages/*.py") + glob.glob("app/pages/*.py")
app_files = ["run.py", "initialize.py", "app/main.py"]

# 1. Hardcoded Dates
print("\n--- 1. Hardcoded Dates & Horizons ---")
date_pattern = re.compile(r'["\'](202\d-[01]\d-[0-3]\d)["\']')
for f in core_files + page_files:
    with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
        for idx, line in enumerate(fp):
            matches = date_pattern.findall(line)
            if matches and not line.strip().startswith('#'):
                print(f"  {f}:{idx+1} -> {matches} | {line.strip()[:90]}")

# 2. Hardcoded Database Paths
print("\n--- 2. Database Connection Patterns ---")
for f in core_files + page_files:
    with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
        for idx, line in enumerate(fp):
            if "sqlite:///" in line and not line.strip().startswith('#'):
                print(f"  {f}:{idx+1} -> {line.strip()[:90]}")

# 3. Hardcoded Tickers & Assets
print("\n--- 3. Hardcoded Asset Symbols & Tickers ---")
ticker_pattern = re.compile(r'["\'](\^NSEI|NIFTYBEES(?:\.NS)?|GOLDBEES(?:\.NS)?|LIQUIDBEES(?:\.NS)?|SILVERBEES(?:\.NS)?)["\']')
for f in core_files + page_files:
    with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
        for idx, line in enumerate(fp):
            matches = ticker_pattern.findall(line)
            if matches and not line.strip().startswith('#'):
                # filter out default parameter definitions
                if not any(k in line for k in ["macro_hedge_asset: str =", "default="]):
                    pass

# 4. Hardcoded Financial / Tax Rates
print("\n--- 4. Hardcoded Friction & Tax Rates ---")
tax_pattern = re.compile(r'\b(0\.20|0\.125|0\.0010|0\.0015|0\.0003|125000(?:\.0)?)\b')
for f in core_files:
    with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
        for idx, line in enumerate(fp):
            if any(t in line for t in ["stcg", "ltcg", "stt", "slippage", "exemption"]) and not line.strip().startswith('#'):
                if any(num in line for num in ["0.20", "0.125", "125000", "0.001"]):
                    print(f"  {f}:{idx+1} -> {line.strip()[:90]}")

# 5. UI Dual-Directory Consistency
print("\n--- 5. Dual-Directory Parity Check ---")
import filecmp
all_pages = [os.path.basename(p) for p in glob.glob("pages/*.py")]
mismatches = []
for p in all_pages:
    p1 = os.path.join("pages", p)
    p2 = os.path.join("app", "pages", p)
    if os.path.exists(p2):
        if not filecmp.cmp(p1, p2):
            mismatches.append(p)
    else:
        print(f"  Missing in app/pages/: {p}")
if mismatches:
    print(f"  MISMATCHED PAGES: {mismatches}")
else:
    print("  All matching pages in pages/ and app/pages/ are 100% IDENTICAL.")

# 6. Session State & Preset Synchronization
print("\n--- 6. Preset & Filter Drift Analysis ---")
for f in ["pages/16_Monthly_SIP_and_Sell_Radar.py", "pages/4_Daily_Top_Stocks.py"]:
    with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
        lines = fp.readlines()
        print(f"  {f}: Total Lines: {len(lines)}")
