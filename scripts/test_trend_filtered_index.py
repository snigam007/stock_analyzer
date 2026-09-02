import sys
import io
from pathlib import Path
import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from sqlalchemy import text

engine = get_global_engine()
session = get_session(engine)

dates_idx = [str(r[0]) for r in session.execute(text("SELECT DISTINCT date FROM index_prices WHERE date >= '2026-08-25' ORDER BY date")).fetchall()]
symbols_rows = session.execute(text("SELECT DISTINCT symbol FROM index_prices")).fetchall()

gains, losses = [], []
for dt in dates_idx:
    for (sym,) in symbols_rows:
        p_row = session.execute(text("SELECT close FROM index_prices WHERE symbol=:s AND date=:d"), {'s': sym, 'd': dt}).fetchone()
        if not p_row or not p_row[0]: continue
        curr_p = float(p_row[0])
        
        past_closes = [float(r[0]) for r in session.execute(text("""
            SELECT close FROM index_prices WHERE symbol=:s AND date < :d ORDER BY date DESC LIMIT 20
        """), {'s': sym, 'd': dt}).fetchall() if r[0]]
        if len(past_closes) < 5: continue
        
        sma_20 = np.mean(past_closes)
        ret_3d = (curr_p - past_closes[2]) / past_closes[2] * 100.0
        
        if curr_p > sma_20 and ret_3d > 0.3:
            sig = 'BUY'
        elif curr_p < sma_20 and ret_3d < -0.3:
            sig = 'SELL'
        else:
            sig = 'WATCH'
            
        if sig == 'WATCH': continue
        
        t1 = curr_p * 1.020 if sig == 'BUY' else curr_p * 0.980
        sl = curr_p * 0.982 if sig == 'BUY' else curr_p * 1.018
        
        fwd = session.execute(text("""
            SELECT high, low, close FROM index_prices WHERE symbol=:s AND date > :d ORDER BY date ASC LIMIT 10
        """), {'s': sym, 'd': dt}).fetchall()
        if not fwd: continue
        
        outcome = None
        for bar in fwd:
            h = float(bar[0] or curr_p)
            l = float(bar[1] or curr_p)
            c = float(bar[2] or curr_p)
            if sig == 'BUY':
                if c <= sl or l <= sl * 0.995:
                    outcome = -1.8
                    break
                if h >= t1:
                    outcome = 2.0
                    break
            else:
                if c >= sl or h >= sl * 1.005:
                    outcome = -1.8
                    break
                if l <= t1:
                    outcome = 2.0
                    break
        if outcome is not None:
            if outcome > 0: gains.append(outcome)
            else: losses.append(abs(outcome))

pf = sum(gains) / max(0.01, sum(losses)) if gains else 0
print(f"Trend-Filtered Index Signals: {len(gains)} Wins, {len(losses)} Losses | Win Rate: {len(gains)/(len(gains)+len(losses))*100:.1f}% | Profit Factor: {pf:.2f}x")
