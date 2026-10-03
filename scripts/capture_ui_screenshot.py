"""
scripts/capture_ui_screenshot.py
================================
Autonomous browser verification utility for Antigravity.
Captures full-page screenshots of local Streamlit or web apps
using headless Chrome directly, eliminating the need for user screenshots.
"""
import sys
import os
import subprocess
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def capture(url="http://localhost:8501/Monthly_SIP_and_Sell_Radar", output_name="page16_latest.png", height=8500, wait_time=12000):
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_path):
        raise FileNotFoundError(f"Chrome not found at {chrome_path}")

    root_dir = Path(__file__).resolve().parent.parent
    out_path = root_dir / "scratch" / output_name
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        chrome_path,
        "--headless=new",
        "--disable-gpu",
        f"--virtual-time-budget={wait_time}",
        f"--screenshot={str(out_path)}",
        f"--window-size=1600,{height}",
        url
    ]

    print(f"📸 Capturing {url} to {out_path}...")
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
    if res.returncode != 0:
        print(f"Error capturing screenshot: {res.stderr}")
        return None

    if out_path.exists():
        size = out_path.stat().st_size
        print(f"✅ Successfully captured screenshot: {out_path} ({size:,} bytes)")
        return str(out_path)
    else:
        print("❌ Screenshot file was not created.")
        return None

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501/Monthly_SIP_and_Sell_Radar"
    out = sys.argv[2] if len(sys.argv) > 2 else "page16_verified.png"
    capture(url, out)
