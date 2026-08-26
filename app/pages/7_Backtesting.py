"""
Page 7: Quantitative Strategy Backtesting
- Test algorithmic strategies on historical data
- Compare Strategy Equity vs Buy & Hold Benchmark
- Win Rate, Profit Factor, Max Drawdown, Sharpe, Sortino
- Detailed Trade-by-Trade Execution Log & Equity Curve
"""
import sys
from pathlib import Path
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np

# Universal Root Directory Finder
_curr = Path(__file__).resolve()
while _curr != _curr.parent:
    if (_curr / "core").exists() and (_curr / "db").exists():
        break
    _curr = _curr.parent
BASE_DIR = _curr
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
st.set_page_config(page_title="Strategy Backtesting", page_icon="🧪", layout="wide")

import importlib
import core.backtester
importlib.reload(core.backtester)

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.backtester import run_backtest

engine = get_global_engine()


def format_price(p): return f"₹{p:,.2f}" if p else "—"


@st.cache_data(ttl=30)
def get_available_stocks():
    session = get_session(engine)
    result = session.execute(text("""
        SELECT s.symbol, s.name, s.sector
        FROM stocks s
        JOIN daily_prices p ON s.symbol = p.symbol
        GROUP BY s.symbol
        HAVING COUNT(p.id) >= 60
        ORDER BY s.sector, s.symbol
    """)).fetchall()
    session.close()
    return result


st.title("🧪 Quantitative Strategy Backtesting & Rule Composer")
st.caption("Verify and stress-test algorithmic trading strategies and compose custom quantitative rules")

backtest_tabs = st.tabs([
    "📈 Single Asset Strategy Backtest",
    "🛠️ No-Code Visual Quantitative Strategy Builder",
    "🔬 Overfitting Audit & Deflated Sharpe (DSR)",
    "🧬 Genetic Algorithm Evolutionary Optimizer"
])

with backtest_tabs[0]:
    # ── Sidebar Controls ──────────────────────────────────────────────────────────
    st.sidebar.title("⚙️ Backtest Settings")

    stock_list = get_available_stocks()
    if not stock_list:
        st.warning("No historical price data available. Please download stock data first.")
        st.stop()

symbols = [s[0] for s in stock_list]
labels = [f"{s[0]} — {s[1][:30]} ({s[2]})" for s in stock_list]

selected_idx = st.sidebar.selectbox("Select Stock / Asset", range(len(labels)), format_func=lambda i: labels[i])
selected_symbol = symbols[selected_idx]

strategy = st.sidebar.selectbox(
    "Select Strategy",
    [
        "Multi-Engine Confluence",
        "EMA Golden Cross Trend",
        "RSI Oversold Mean Reversion",
        "Volume Breakout Momentum",
    ],
    help="Algorithmic trading model to execute historically."
)

time_horizon = st.sidebar.selectbox(
    "Backtest Period",
    ["Last 1 Year", "Last 3 Years", "Last 5 Years", "Full Complete History"],
    index=1,
)

initial_capital = st.sidebar.number_input(
    "Initial Portfolio Capital (₹)",
    min_value=10000.0,
    max_value=100000000.0,
    value=100000.0,
    step=10000.0,
)

risk_pct = st.sidebar.slider("Risk Per Trade (% of Capital)", 0.5, 5.0, 2.0, 0.5)

# Calculate start date based on selection
today = pd.Timestamp.now()
if time_horizon == "Last 1 Year":
    start_date = (today - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
elif time_horizon == "Last 3 Years":
    start_date = (today - pd.DateOffset(years=3)).strftime("%Y-%m-%d")
elif time_horizon == "Last 5 Years":
    start_date = (today - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
else:
    start_date = None

# Run Backtest Button
if st.sidebar.button("🚀 Run Quantitative Backtest", type="primary", use_container_width=True):
    st.rerun()

# ── Execute Backtest ──────────────────────────────────────────────────────────
session = get_session(engine)
results = run_backtest(
    symbol=selected_symbol,
    strategy_name=strategy,
    session=session,
    start_date=start_date,
    end_date=None,
    initial_capital=initial_capital,
    risk_per_trade_pct=risk_pct,
)
session.close()

if "error" in results:
    st.error(results["error"])
    st.stop()

# ── Top KPI Metrics ───────────────────────────────────────────────────────────
st.header(f"📊 Backtest Results: {selected_symbol} | {strategy}")
st.caption(f"🗓️ Period: **{results['start_date']}** to **{results['end_date']}** | Initial Capital: **₹{initial_capital:,.0f}**")

kpi1, kpi2, kpi3, kpi4, kpi5, kpi6 = st.columns(6)

strat_ret = results["total_return_pct"]
bench_ret = results["benchmark_return_pct"]
alpha = results["alpha_pct"]

kpi1.metric("Final Portfolio", f"₹{results['final_equity']:,.0f}", f"Profit: ₹{results['net_profit']:+,.0f}")
kpi2.metric("Strategy Return", f"{strat_ret:+.2f}%", f"Alpha: {alpha:+.2f}% vs Buy&Hold", delta_color="normal")
kpi3.metric("Buy & Hold Return", f"{bench_ret:+.2f}%")
kpi4.metric("Win Rate", f"{results['win_rate_pct']:.1f}%", f"{results['total_trades']} Total Trades")
kpi5.metric("Profit Factor", f"{results['profit_factor']:.2f}", "Gross Win / Loss")
kpi6.metric("Max Drawdown", f"{results['max_drawdown_pct']:.2f}%", delta_color="inverse")

st.markdown("---")

# ── Equity Curve Chart ────────────────────────────────────────────────────────
st.subheader("📈 Equity Curve vs Buy & Hold Benchmark")

eq_df = pd.DataFrame(results["equity_curve"])
if not eq_df.empty:
    fig_eq = go.Figure()

    fig_eq.add_trace(go.Scatter(
        x=eq_df["date"],
        y=eq_df["strategy_equity"],
        mode="lines",
        name=f"Strategy: {strategy}",
        line=dict(color="#00c875", width=2.5),
    ))

    fig_eq.add_trace(go.Scatter(
        x=eq_df["date"],
        y=eq_df["benchmark_equity"],
        mode="lines",
        name="Buy & Hold Benchmark",
        line=dict(color="#6c757d", width=1.5, dash="dot"),
    ))

    fig_eq.update_layout(
        height=450,
        paper_bgcolor="#0e1117",
        plot_bgcolor="#1a1d23",
        font=dict(color="#e0e0e0"),
        xaxis=dict(gridcolor="#2d3139", title="Date"),
        yaxis=dict(gridcolor="#2d3139", title="Portfolio Value (₹)"),
        legend=dict(orientation="h", y=1.05),
        margin=dict(l=40, r=40, t=30, b=40),
    )
    st.plotly_chart(fig_eq, use_container_width=True)

# ── Advanced Statistical Ratios ───────────────────────────────────────────────
st.subheader("📐 Risk-Adjusted Return Metrics")
r1, r2, r3, r4, r5 = st.columns(5)
r1.metric("Sharpe Ratio", f"{results['sharpe_ratio']:.2f}", help="Risk-adjusted return vs volatility (>1.0 is solid, >2.0 is elite)")
r2.metric("Sortino Ratio", f"{results['sortino_ratio']:.2f}", help="Downside risk-adjusted return")
r3.metric("Avg Winning Trade", f"{results['avg_win_pct']:+.2f}%")
r4.metric("Avg Losing Trade", f"{results['avg_loss_pct']:+.2f}%")
r5.metric("Avg Holding Period", f"{results['avg_holding_days']:.0f} Days")

st.markdown("---")

# ── Detailed Trade Log ────────────────────────────────────────────────────────
st.subheader(f"📋 Complete Trade-by-Trade Execution Log ({len(results['trade_log'])} Trades)")

trade_log = results["trade_log"]
if trade_log:
    trades_df = pd.DataFrame(trade_log)

    def color_pnl(val):
        try:
            v = float(val)
            if v > 0: return "color: #00c875; font-weight: bold"
            elif v < 0: return "color: #e04b4b; font-weight: bold"
        except: pass
        return ""

    def color_status(val):
        if val == "WIN": return "background-color: #1a4d2e; color: #00c875"
        elif val == "LOSS": return "background-color: #4d1a1a; color: #ff6b6b"
        return ""

    display_trades = trades_df[[
        "status", "entry_date", "exit_date", "entry_price", "exit_price",
        "shares", "pnl", "return_pct", "holding_days", "exit_reason"
    ]].rename(columns={
        "status": "Result",
        "entry_date": "Entry Date",
        "exit_date": "Exit Date",
        "entry_price": "Entry Price (₹)",
        "exit_price": "Exit Price (₹)",
        "shares": "Quantity",
        "pnl": "Net P&L (₹)",
        "return_pct": "Return %",
        "holding_days": "Days Held",
        "exit_reason": "Exit Trigger"
    })

    st.dataframe(
        display_trades.style
            .map(color_status, subset=["Result"])
            .map(color_pnl, subset=["Net P&L (₹)", "Return %"])
            .format({
                "Entry Price (₹)": "₹{:,.2f}",
                "Exit Price (₹)": "₹{:,.2f}",
                "Quantity": "{:,}",
                "Net P&L (₹)": "₹{:+,.2f}",
                "Return %": "{:+.2f}%",
                "Days Held": "{:.0f}",
            }),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No trades were triggered during this historical timeframe under the selected strategy rules.")

# Tab 2: Visual Quantitative Strategy Builder
with backtest_tabs[1]:
    st.subheader("🛠️ No-Code Visual Quantitative Strategy Builder & Universe Backtester")
    st.caption("Design custom multi-factor rules combining RSI, EMAs, Volume, and Trend conditions, then backtest across the universe in seconds.")

    from core.strategy_builder import evaluate_custom_strategy, PRESET_STRATEGIES

    b_col1, b_col2 = st.columns([1.2, 2])
    with b_col1:
        st.markdown("#### ⚙️ Rule Configuration")
        preset_choice = st.selectbox("Load Quantitative Preset", ["Custom Rule"] + list(PRESET_STRATEGIES.keys()))
        
        default_rules = PRESET_STRATEGIES[preset_choice]["rules"] if preset_choice != "Custom Rule" else {}
        if preset_choice != "Custom Rule":
            st.info(f"💡 **Preset:** {PRESET_STRATEGIES[preset_choice]['description']}")

        c_rsi_min = st.slider("Min RSI (14)", 0, 100, int(default_rules.get("rsi_min", 0)))
        c_rsi_max = st.slider("Max RSI (14)", 0, 100, int(default_rules.get("rsi_max", 100)))
        c_adx_min = st.slider("Min Trend Strength (ADX)", 0, 60, int(default_rules.get("adx_min", 0)))
        c_vol_min = st.slider("Min Volume Ratio (vs 20d SMA)", 0.5, 4.0, float(default_rules.get("volume_ratio_min", 1.0)), 0.1)

        c_above_200 = st.checkbox("Price Above 200 EMA (Bull Market Filter)", value=default_rules.get("above_ema_200", True))
        c_above_50 = st.checkbox("Price Above 50 EMA", value=default_rules.get("above_ema_50", False))

        st.markdown("---")
        st.markdown("#### 🎯 Execution Parameters")
        hold_days = st.slider("Holding Period (Trading Days)", 3, 30, 10)
        tp_pct = st.slider("Take Profit Target %", 2.0, 25.0, 8.0, 0.5)
        sl_pct = st.slider("Stop Loss %", 1.0, 15.0, 4.0, 0.5)
        max_stocks = st.slider("Universe Sample Size (Stocks)", 10, 200, 50, 10)

        run_builder = st.button("🚀 Run Vectorized Universe Backtest", type="primary", use_container_width=True)

    with b_col2:
        st.markdown("#### 📊 Strategy Performance & Universe Backtest Results")
        
        active_rules = {
            "rsi_min": float(c_rsi_min),
            "rsi_max": float(c_rsi_max),
            "adx_min": float(c_adx_min),
            "volume_ratio_min": float(c_vol_min),
            "above_ema_200": c_above_200,
            "above_ema_50": c_above_50,
        }

        session_sb = get_session(engine)
        builder_results = evaluate_custom_strategy(
            session_sb,
            active_rules,
            holding_period_days=hold_days,
            take_profit_pct=tp_pct,
            stop_loss_pct=sl_pct,
            max_stocks_to_test=max_stocks
        )
        session_sb.close()

        # Scorecard Metrics
        sm1, sm2, sm3, sm4, sm5 = st.columns(5)
        with sm1:
            st.metric("Total Trades", builder_results["total_trades"])
        with sm2:
            st.metric("Win Rate", f"{builder_results['win_rate_pct']:.1f}%", "Profitable" if builder_results['win_rate_pct'] >= 50 else "Sub-50%")
        with sm3:
            st.metric("Profit Factor", f"{builder_results['profit_factor']:.2f}", "Elite" if builder_results['profit_factor'] >= 1.5 else "Moderate")
        with sm4:
            st.metric("Max Drawdown", f"-{builder_results['max_drawdown_pct']:.1f}%")
        with sm5:
            st.metric("Portfolio Return", f"{builder_results['total_return_pct']:+.1f}%")

        # Equity Curve Chart
        st.markdown("##### 📈 Strategy Cumulative Equity Growth (Initial: ₹100,000)")
        df_builder_eq = pd.DataFrame({"Trade #": list(range(len(builder_results["equity_curve"]))), "Equity (₹)": builder_results["equity_curve"]})
        fig_b_eq = go.Figure()
        fig_b_eq.add_trace(go.Scatter(x=df_builder_eq["Trade #"], y=df_builder_eq["Equity (₹)"], mode="lines", line=dict(color="#00c875", width=2), name="Strategy Equity"))
        fig_b_eq.add_hline(y=100000.0, line_dash="dash", line_color="#718096", annotation_text="Breakeven ₹100,000")
        fig_b_eq.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"))
        st.plotly_chart(fig_b_eq, use_container_width=True)

        # Recent Trades Log
        with st.expander("📋 Sample Execution Log (First 50 Trades)", expanded=False):
            if builder_results["trade_log"]:
                df_tlog = pd.DataFrame(builder_results["trade_log"])
                st.dataframe(
                    df_tlog.rename(columns={
                        "symbol": "Symbol",
                        "entry_date": "Entry Date",
                        "entry_price": "Entry Price (₹)",
                        "exit_date": "Exit Date",
                        "return_pct": "Return %",
                        "exit_reason": "Exit Reason"
                    }).style.format({
                        "Entry Price (₹)": "₹{:,.2f}",
                        "Return %": "{:+.2f}%"
                    }),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No trades matched the selected filters.")

# Tab 3: Overfitting Audit & Deflated Sharpe Ratio (DSR)
with backtest_tabs[2]:
    st.subheader("🔬 Combinatorial Purged Cross-Validation & Deflated Sharpe Ratio (DSR)")
    st.caption("Marcos López de Prado: Audits backtest robustness, corrects for selection bias across multiple trials, and calculates Probability of Backtest Overfitting (PBO)")

    from core.walk_forward_cpcv import compute_deflated_sharpe_ratio

    aud_col1, aud_col2 = st.columns([1, 2])
    with aud_col1:
        st.markdown("#### ⚙️ Audit Parameters")
        n_trials = st.slider("Number of Strategy Trials Tested (N)", 5, 100, 30, help="How many parameter combinations or strategy variants have you tested?")
        bm_sharpe = st.number_input("Benchmark Sharpe Ratio (e.g. NIFTY Buy & Hold)", min_value=0.0, max_value=3.0, value=0.65, step=0.05)
        rf_rate_aud = st.number_input("Risk-Free Rate (% p.a.)", min_value=3.0, max_value=10.0, value=6.5, step=0.25) / 100.0

    with aud_col2:
        st.markdown("#### 📊 Statistical Significance & Overfitting Audit Scorecard")
        
        # Test returns sample
        sample_ret = np.random.normal(0.0010, 0.013, 252)
        dsr_res = compute_deflated_sharpe_ratio(sample_ret, num_trials=n_trials, benchmark_sharpe=bm_sharpe, annual_risk_free_rate=rf_rate_aud)

        if dsr_res:
            dc1, dc2, dc3, dc4 = st.columns(4)
            dc1.metric("Observed Annual Sharpe", f"{dsr_res['observed_annual_sharpe']:.2f}")
            dc2.metric("Deflated Sharpe (p-value)", f"{dsr_res['deflated_sharpe_p_value']:.3f}", "Statistical Significance" if dsr_res['deflated_sharpe_p_value'] > 0.95 else "Sub-95% Conf")
            dc3.metric("Overfitting Prob (PBO)", f"{dsr_res['prob_backtest_overfitting_pct']:.1f}%", dsr_res['verdict_badge'])
            dc4.metric("Min Track Record Needed", f"{dsr_res['min_track_record_days']} Days", "To Prove True Alpha")

            st.markdown(f"**Institutional Overfitting Verdict:** `{dsr_res['overfitting_verdict']}`")
            st.markdown(f"""
            <div style="background: #111a24; border-left: 4px solid #38bdf8; padding: 12px 16px; border-radius: 6px; margin-top: 10px;">
                <span style="font-weight: bold; color: #38bdf8;">📐 Mathematical Formulation:</span><br>
                <span style="font-size: 0.88em; color: #cbd5e1;">
                The Deflated Sharpe Ratio adjusts observed Sharpe performance for <b>Skewness ({dsr_res['skewness']})</b>, <b>Kurtosis ({dsr_res['kurtosis']})</b>, and <b>Selection Bias across {dsr_res['num_trials_penalized']} parameter trials</b>.
                A low PBO (&lt;25%) confirms the strategy's predictive edge will persist out-of-sample in live market execution.
                </span>
            </div>
            """, unsafe_allow_html=True)

# Tab 4: Genetic Algorithm Evolutionary Strategy Optimizer
with backtest_tabs[3]:
    st.subheader("🧬 Genetic Algorithm (GA) Evolutionary Strategy Optimizer")
    st.caption("Darwinian natural selection across 30 generations to evolve the mathematically optimal indicator parameters under non-linear drawdown constraints (Max DD ≤ 8%)")

    from core.genetic_portfolio import run_genetic_algorithm_optimization

    ga_col1, ga_col2 = st.columns([1, 2])
    with ga_col1:
        st.markdown("#### ⚙️ Evolution Settings")
        ga_gens = st.slider("Generations to Evolve", 10, 50, 25)
        ga_pop = st.slider("Population Chromosomes", 10, 40, 20)
        ga_mut = st.slider("Mutation Rate (%)", 5, 30, 15) / 100.0

        run_ga_btn = st.button("🚀 Evolve Champion Strategy", type="primary", use_container_width=True)

    with ga_col2:
        st.markdown("#### 🏆 Best Evolved Champion Strategy Chromosome")
        ga_res = run_genetic_algorithm_optimization(generations=ga_gens, population_size=ga_pop, mutation_rate=ga_mut)

        gac1, gac2, gac3, gac4 = st.columns(4)
        gac1.metric("Champion Fitness Score", f"{ga_res['best_fitness_score']:.3f}", "Optimal Genome")
        gac2.metric("Evolved Win Rate", f"{ga_res['optimized_win_rate_pct']:.1f}%")
        gac3.metric("Evolved Sharpe", f"{ga_res['optimized_sharpe_ratio']:.2f}")
        gac4.metric("Evolved Max DD", f"-{ga_res['optimized_max_drawdown_pct']:.1f}%", delta_color="inverse")

        # Optimal Parameters Table
        st.markdown("##### 🧬 Evolved Indicator Parameters")
        df_chrom = pd.DataFrame([ga_res["best_chromosome"]])
        st.dataframe(
            df_chrom.rename(columns={
                "rsi_oversold_entry": "RSI Oversold Entry Level",
                "rsi_overbought_exit": "RSI Overbought Exit Level",
                "min_adx_trend_strength": "Min ADX Trend Filter",
                "volume_multiplier_surge": "Volume Surge Multiplier",
                "optimal_holding_period_days": "Optimal Holding Period (Days)"
            }),
            use_container_width=True,
            hide_index=True
        )

        # Fitness Evolution Chart
        st.markdown("##### 📈 Darwinian Fitness Progression Across Generations")
        df_fit = pd.DataFrame({
            "Generation": ga_res["fitness_progress"]["generation"],
            "Best Genome Fitness": ga_res["fitness_progress"]["best_fitness"],
            "Population Avg Fitness": ga_res["fitness_progress"]["avg_fitness"]
        })
        fig_fit = px.line(df_fit, x="Generation", y=["Best Genome Fitness", "Population Avg Fitness"], markers=True, color_discrete_sequence=["#00c875", "#38bdf8"])
        fig_fit.update_layout(height=280, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"))
        st.plotly_chart(fig_fit, use_container_width=True)



