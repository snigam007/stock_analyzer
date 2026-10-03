# Quantum Microstructure Swing Champion — TradingView Suite (Pine Script v5)

This directory contains the production-grade TradingView Pine Script v5 implementations of the **Quantum Microstructure Swing Strategy** (Ablation 7 Champion: Anchored VWAP + 30D Volume Profile VAL Retest + DFA Hurst Persistence + T1 Breakeven Ratchet).

---

## Files in this Directory

1. **[`quantum_microstructure_swing_indicator.pine`](file:///c:/Users/SNigam2/.gemini/antigravity/scratch/stock_analyzer/tradingview/quantum_microstructure_swing_indicator.pine)**:
   - **Primary Visual Indicator** for live charting.
   - Plots on-chart 30-Day Volume Profile Value Area (VAH, VWAP/POC, VAL), 60-Day Low Anchored VWAP, and Trend EMAs (50/200).
   - Generates visually distinct `LONG` and `SHORT` signal triangles.
   - Automatically projects active trade price levels: **Entry**, **Stop Loss**, **Target 1** (+1.0x ATR Breakeven Ratchet), **Target 2** (+2.8x ATR), and **Target 3** (+8.0x ATR Chandelier Runner).
   - Features an **On-Chart Institutional HUD Table** (top-right) displaying live NIFTY 50 Regime status, Macro Trend, AVWAP Support, Volume Profile state, Hurst persistence ($H$), Log Dollar-Volume Z-Score ($z$), and Momentum.
   - Includes full native TradingView alert conditions (`alertcondition`).

2. **[`quantum_microstructure_swing_strategy.pine`](file:///c:/Users/SNigam2/.gemini/antigravity/scratch/stock_analyzer/tradingview/quantum_microstructure_swing_strategy.pine)**:
   - **Strategy Backtester** for TradingView's built-in Strategy Tester tab.
   - Simulates orders (`strategy.entry`, `strategy.exit`) with partial position trims (25% at T1, 33% at T2), instant breakeven ratcheting when T1 is hit, and runner exits.
   - Displays real-time backtest statistics (Net Profit, Win Rate, Profit Factor, Max Drawdown, Trade List) directly on any stock chart.

---

## Core Quantitative Logic (1:1 with Python Engine)

| Component | Mathematical Definition / Logic | Purpose |
|---|---|---|
| **Macro Confluence** | NIFTY 50 $\text{Close} \ge \text{EMA}_{50} \ge \text{EMA}_{21}$ | Ensures market breadth supports risk-on long deployment. |
| **Trend Foundation** | $\text{Close} \ge \text{EMA}_{50} \ge \text{EMA}_{200} \times 0.98$ | Restricts swing trading to confirmed structural bull trends. |
| **60D Low AVWAP** | $\text{Close} \ge 0.992 \times \text{AVWAP}_{\text{60D Structural Low}}$ | Confirms price is above institutional accumulated cost basis. |
| **30D Volume Profile** | $\text{Low} \le 1.02 \times \text{VWAP}_{30\text{D}}$ and $\text{Close} \ge 0.99 \times \text{VAL}_{30\text{D}}$ | Auction Market Theory retest: buys pullbacks into Value Area Low. |
| **DFA / Hurst Exponent** | Rolling 60-bar Rescaled Range $H > 0.50$ | Filters out mean-reverting chop; validates trending persistence. |
| **Log Dollar-Volume** | $z_{\ln(P \times V)} \ge 0.15$ | Guarantees institutional liquidity participation. |
| **Stop Loss** | $\max(\text{Close} - 1.5 \times \text{ATR}, \min(\text{Close} \times 0.95, \text{VAL}_{30\text{D}} - 0.5 \times \text{ATR}))$ | Anchored behind institutional Volume Profile shelf. |
| **Target 1** | $\text{Close} + 1.00 \times \text{ATR}$ | Harvest 25% profit + **instant ratchet of Stop Loss to Breakeven (+0.2%)**. |
| **Target 2** | $\text{Close} + 2.80 \times \text{ATR}$ | Harvest 33% profit. |
| **Target 3 (Runner)**| $\text{Close} + 8.00 \times \text{ATR}$ | Chandelier trailing stop runner capture. |

---

## Quick Setup Instructions for TradingView

### Step 1: Open TradingView
1. Navigate to [TradingView](https://www.tradingview.com/chart/) and open any NSE stock chart (e.g., `NSE:TRENT`, `NSE:BEL`, `NSE:RELIANCE`).
2. Set the chart timeframe to **Daily (`1D`)**.

### Step 2: Open Pine Editor
1. Click on the **Pine Editor** tab at the bottom panel of the screen.
2. Click **New** $\to$ **Blank indicator script**.
3. Select all text (`Ctrl+A`) and delete it.

### Step 3: Paste and Save the Indicator
1. Open [`tradingview/quantum_microstructure_swing_indicator.pine`](file:///c:/Users/SNigam2/.gemini/antigravity/scratch/stock_analyzer/tradingview/quantum_microstructure_swing_indicator.pine).
2. Copy the entire contents and paste into the Pine Editor.
3. Click **Save** (name it `Quantum Microstructure Swing Champion`).
4. Click **Add to chart**.

### Step 4: (Optional) Add Strategy Backtester
1. In Pine Editor, click **New** $\to$ **Blank strategy script**.
2. Copy and paste [`tradingview/quantum_microstructure_swing_strategy.pine`](file:///c:/Users/SNigam2/.gemini/antigravity/scratch/stock_analyzer/tradingview/quantum_microstructure_swing_strategy.pine).
3. Click **Save** and **Add to chart**.
4. Click the **Strategy Tester** tab below the chart to view historical backtest performance, win rate, and profit factor on the selected stock.

---

## How to Set Up Real-Time TradingView Alerts

1. On the chart, click the **Alerts** icon (clock with plus) on the right sidebar or press `Alt + A`.
2. Under **Condition**, select: `Quantum Microstructure Swing Champion [Antigravity]`.
3. Select the desired alert trigger:
   - `Quantum Long Signal`: Fires whenever a validated institutional pullback entry triggers.
   - `Target 1 Reached (Lock BE)`: Fires when Target 1 (+1.0x ATR) is touched, notifying you to harvest 25% and ratchet Stop Loss to Breakeven.
   - `Target 2 Reached`: Fires when Target 2 (+2.8x ATR) is touched.
   - `Stop Loss Triggered`: Fires if price breaches the active stop loss.
4. Set **Trigger** to `Once Per Bar Close` (recommended for Daily swing trading to avoid intraday repainting).
5. Choose your notification preference (App popup, Email, or Webhook URL).
6. Click **Create**.
