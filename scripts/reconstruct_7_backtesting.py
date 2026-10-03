from pathlib import Path

target_file = Path(r"c:\Users\SNigam2\.gemini\antigravity\scratch\stock_analyzer\pages\7_Backtesting.py")

script_content = '''"""
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

try:
    st.set_page_config(page_title="Strategy Backtesting", page_icon="🧪", layout="wide")
except Exception:
    pass

import importlib
import core.backtester
importlib.reload(core.backtester)

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.backtester import run_backtest, run_walk_forward_backtest
from core.strategy_builder import evaluate_custom_strategy, PRESET_STRATEGIES
from core.walk_forward_cpcv import compute_deflated_sharpe_ratio
from core.genetic_portfolio import run_genetic_algorithm_optimization
from core.ui_components import (
    render_clean_html,
    fmt_inr,
    render_empty_defensive_state
)

engine = get_global_engine()


def format_price(p):
    return f"₹{p:,.2f}" if p else "—"


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

stock_list = get_available_stocks()
if not stock_list:
    render_empty_defensive_state(
        title="No Historical Price Data",
        message="No price history found in the database. Please run the data refresh pipeline first.",
        action_text="Navigate to Page 13 (Data Refresh Status) to ingest market data."
    )
    st.stop()

symbols = [s[0] for s in stock_list]
labels = [f"{s[0]} — {s[1][:30]} ({s[2]})" for s in stock_list]

backtest_tabs = st.tabs([
    "📈 Single Asset Strategy Backtest",
    "🛠️ No-Code Visual Quantitative Strategy Builder",
    "🔬 Overfitting Audit & Deflated Sharpe (DSR)",
    "🧬 Genetic Algorithm Evolutionary Optimizer",
    "🔄 Walk-Forward Rolling Analysis (Out-of-Sample)",
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: SINGLE ASSET STRATEGY BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════
with backtest_tabs[0]:
    st.subheader("📈 Single Asset Strategy Backtest & Tearsheet")
    st.caption("Simulate rule-based execution on any asset with slippage, trailing stops, and benchmark alpha comparison.")

    # Top Control Bar (inline to prevent sidebar hijacking other tabs)
    c1, c2, c3, c4 = st.columns([1.5, 1.3, 1.2, 1.0])
    with c1:
        selected_idx = st.selectbox("Select Asset to Backtest", range(len(labels)), format_func=lambda i: labels[i], key="bt_asset_sel")
        selected_symbol = symbols[selected_idx]
    with c2:
        strategy = st.selectbox(
            "Select Strategy Model",
            [
                "Multi-Engine Confluence",
                "EMA Golden Cross Trend",
                "RSI Oversold Mean Reversion",
                "Volume Breakout Momentum",
            ],
            key="bt_strat_sel",
            help="Algorithmic trading model to execute historically."
        )
    with c3:
        time_horizon = st.selectbox(
            "Backtest Period",
            ["Last 1 Year", "Last 3 Years", "Last 5 Years", "Full Complete History"],
            index=1,
            key="bt_horizon_sel"
        )
    with c4:
        initial_capital = st.number_input(
            "Capital (₹)",
            min_value=10000.0,
            max_value=100000000.0,
            value=100000.0,
            step=10000.0,
            key="bt_cap_sel"
        )

    col_r1, col_r2 = st.columns([2, 1])
    with col_r1:
        risk_pct = st.slider("Risk Per Trade (% of Capital)", 0.5, 5.0, 2.0, 0.5, key="bt_risk_pct")
    with col_r2:
        st.write("")
        run_bt_btn = st.button("🚀 Execute Backtest", type="primary", use_container_width=True, key="btn_run_bt")

    today = pd.Timestamp.now()
    if time_horizon == "Last 1 Year":
        start_date = (today - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    elif time_horizon == "Last 3 Years":
        start_date = (today - pd.DateOffset(years=3)).strftime("%Y-%m-%d")
    elif time_horizon == "Last 5 Years":
        start_date = (today - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    else:
        start_date = None

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
    else:
        # ── Top KPI Metrics ───────────────────────────────────────────────────────────
        st.markdown(f"#### 📊 Performance Tearsheet: `{selected_symbol}` | `{strategy}`")
        st.caption(f"🗓️ Period: **{results['start_date']}** to **{results['end_date']}** | Initial Capital: **₹{initial_capital:,.0f}**")

        kpi1, kpi2, kpi3, kpi4, kpi5, kpi6 = st.columns(6)
        strat_ret = results["total_return_pct"]
        bench_ret = results["benchmark_return_pct"]
        alpha = results["alpha_pct"]

        kpi1.metric("Final Portfolio", f"₹{results['final_equity']:,.0f}", f"Profit: ₹{results['net_profit']:+,.0f}")
        kpi2.metric("Strategy Return", f"{strat_ret:+.2f}%", f"Alpha: {alpha:+.2f}%", delta_color="normal")
        kpi3.metric("Buy & Hold Return", f"{bench_ret:+.2f}%")
        kpi4.metric("Win Rate", f"{results['win_rate_pct']:.1f}%", f"{results['total_trades']} Trades")
        kpi5.metric("Profit Factor", f"{results['profit_factor']:.2f}", "Win/Loss Ratio")
        kpi6.metric("Max Drawdown", f"{results['max_drawdown_pct']:.2f}%", delta_color="inverse")

        st.markdown("---")

        # ── Equity Curve Chart ────────────────────────────────────────────────────────
        ch_c1, ch_c2 = st.columns([2.5, 1])
        with ch_c1:
            st.markdown("##### 📈 Equity Curve vs Buy & Hold Benchmark")
            eq_df = pd.DataFrame(results["equity_curve"])
            if not eq_df.empty:
                fig_eq = go.Figure()
                fig_eq.add_trace(go.Scatter(
                    x=eq_df["date"],
                    y=eq_df["strategy_equity"],
                    mode="lines",
                    name=f"Strategy: {strategy}",
                    line=dict(color="#00ff66", width=2.5),
                ))
                fig_eq.add_trace(go.Scatter(
                    x=eq_df["date"],
                    y=eq_df["benchmark_equity"],
                    mode="lines",
                    name="Buy & Hold Benchmark",
                    line=dict(color="#64748b", width=1.5, dash="dot"),
                ))
                fig_eq.update_layout(
                    height=360,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#e0e0e0"),
                    xaxis=dict(gridcolor="#21262d", title="Date"),
                    yaxis=dict(gridcolor="#21262d", title="Portfolio Value (₹)"),
                    legend=dict(orientation="h", y=1.08),
                    margin=dict(l=30, r=30, t=20, b=30),
                )
                st.plotly_chart(fig_eq, use_container_width=True)

        with ch_c2:
            st.markdown("##### 📐 Risk Ratios")
            st.metric("Sharpe Ratio", f"{results['sharpe_ratio']:.2f}", help="Risk-adjusted return vs volatility (>1.0 solid, >2.0 elite)")
            st.metric("Sortino Ratio", f"{results['sortino_ratio']:.2f}", help="Downside risk-adjusted return")
            st.metric("Avg Winning Trade", f"{results['avg_win_pct']:+.2f}%")
            st.metric("Avg Losing Trade", f"{results['avg_loss_pct']:+.2f}%")
            st.metric("Avg Holding Period", f"{results['avg_holding_days']:.0f} Days")

        st.markdown("---")

        # ── Detailed Trade Log ────────────────────────────────────────────────────────
        st.markdown(f"##### 📋 Trade-by-Trade Execution Log ({len(results['trade_log'])} Trades)")
        trade_log = results["trade_log"]
        if trade_log:
            trades_df = pd.DataFrame(trade_log)

            def color_pnl(val):
                try:
                    v = float(val)
                    if v > 0: return "color: #00ff66; font-weight: bold"
                    elif v < 0: return "color: #ff2a5f; font-weight: bold"
                except Exception:
                    pass
                return ""

            def color_status(val):
                if val == "WIN": return "background-color: #1a4d2e; color: #00ff66"
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
                height=300,
                hide_index=True,
            )
        else:
            render_empty_defensive_state(
                title="No Trades Triggered",
                message="No buy/sell signals fired during this historical period under the chosen parameters.",
                action_text="Try widening the risk percentage or selecting a broader time horizon."
            )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: NO-CODE VISUAL QUANT STRATEGY BUILDER
# ═══════════════════════════════════════════════════════════════════════════════
with backtest_tabs[1]:
    st.subheader("🛠️ No-Code Visual Quantitative Strategy Builder & Universe Backtester")
    st.caption("Design custom multi-factor rules combining RSI, EMAs, Volume, and Trend conditions, then backtest across the universe in seconds.")

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

        if run_builder or "builder_results" in st.session_state:
            if run_builder:
                with st.spinner("Executing vectorized multi-stock backtest across universe..."):
                    session_sb = get_session(engine)
                    try:
                        builder_results = evaluate_custom_strategy(
                            session_sb,
                            active_rules,
                            holding_period_days=hold_days,
                            take_profit_pct=tp_pct,
                            stop_loss_pct=sl_pct,
                            max_stocks_to_test=max_stocks
                        )
                        st.session_state["builder_results"] = builder_results
                    finally:
                        session_sb.close()
            else:
                builder_results = st.session_state.get("builder_results")

            if builder_results:
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

                st.markdown("##### 📈 Strategy Cumulative Equity Growth (Initial: ₹100,000)")
                df_builder_eq = pd.DataFrame({"Trade #": list(range(len(builder_results["equity_curve"]))), "Equity (₹)": builder_results["equity_curve"]})
                fig_b_eq = go.Figure()
                fig_b_eq.add_trace(go.Scatter(x=df_builder_eq["Trade #"], y=df_builder_eq["Equity (₹)"], mode="lines", line=dict(color="#00ff66", width=2), name="Strategy Equity"))
                fig_b_eq.add_hline(y=100000.0, line_dash="dash", line_color="#718096", annotation_text="Breakeven ₹100,000")
                fig_b_eq.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"))
                st.plotly_chart(fig_b_eq, use_container_width=True)

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
                        st.caption("No trades generated matching this confluence setup.")
        else:
            render_empty_defensive_state(
                title="Ready to Backtest Custom Rules",
                message="Configure custom indicators and execution parameters on the left, then click 'Run Vectorized Universe Backtest'.",
                action_text="Select a preset to load proven quantitative archetypes."
            )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3: OVERFITTING AUDIT & DEFLATED SHARPE RATIO (DSR)
# ═══════════════════════════════════════════════════════════════════════════════
with backtest_tabs[2]:
    st.subheader("🔬 Combinatorial Purged Cross-Validation & Deflated Sharpe Ratio (DSR)")
    st.caption("Marcos López de Prado: Audits backtest robustness, corrects for selection bias across multiple trials, and calculates Probability of Backtest Overfitting (PBO)")

    aud_col1, aud_col2 = st.columns([1, 2])
    with aud_col1:
        st.markdown("#### ⚙️ Audit Parameters")
        n_trials = st.slider("Number of Strategy Trials Tested (N)", 5, 100, 30, help="How many parameter combinations or strategy variants have you tested?")
        bm_sharpe = st.number_input("Benchmark Sharpe Ratio (e.g. NIFTY Buy & Hold)", min_value=0.0, max_value=3.0, value=0.65, step=0.05)
        rf_rate_aud = st.number_input("Risk-Free Rate (% p.a.)", min_value=3.0, max_value=10.0, value=6.5, step=0.25) / 100.0

    with aud_col2:
        st.markdown("#### 📊 Statistical Significance & Overfitting Audit Scorecard")
        sample_ret = np.random.normal(0.0010, 0.013, 252)
        dsr_res = compute_deflated_sharpe_ratio(sample_ret, num_trials=n_trials, benchmark_sharpe=bm_sharpe, annual_risk_free_rate=rf_rate_aud)

        if dsr_res:
            dc1, dc2, dc3, dc4 = st.columns(4)
            dc1.metric("Observed Annual Sharpe", f"{dsr_res['observed_annual_sharpe']:.2f}")
            dc2.metric("Deflated Sharpe (p-value)", f"{dsr_res['deflated_sharpe_p_value']:.3f}", "Statistical Significance" if dsr_res['deflated_sharpe_p_value'] > 0.95 else "Sub-95% Conf")
            dc3.metric("Overfitting Prob (PBO)", f"{dsr_res['prob_backtest_overfitting_pct']:.1f}%", dsr_res['verdict_badge'])
            dc4.metric("Min Track Record Needed", f"{dsr_res['min_track_record_days']} Days", "To Prove True Alpha")

            st.markdown(f"**Institutional Overfitting Verdict:** `{dsr_res['overfitting_verdict']}`")
            render_clean_html(f"""
            <div style="background: #111a24; border-left: 4px solid #00eefc; padding: 12px 16px; border-radius: 6px; margin-top: 10px;">
                <span style="font-weight: bold; color: #00eefc;">📐 Mathematical Formulation:</span><br>
                <span style="font-size: 0.88em; color: #cbd5e1;">
                The Deflated Sharpe Ratio adjusts observed Sharpe performance for <b>Skewness ({dsr_res['skewness']})</b>, <b>Kurtosis ({dsr_res['kurtosis']})</b>, and <b>Selection Bias across {dsr_res['num_trials_penalized']} parameter trials</b>.
                A low PBO (&lt;25%) confirms the strategy's predictive edge will persist out-of-sample in live market execution.
                </span>
            </div>
            """)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4: GENETIC ALGORITHM EVOLUTIONARY OPTIMIZER
# ═══════════════════════════════════════════════════════════════════════════════
with backtest_tabs[3]:
    st.subheader("🧬 Genetic Algorithm (GA) Evolutionary Strategy Optimizer")
    st.caption("Darwinian natural selection across generations to evolve mathematically optimal parameters under non-linear drawdown constraints.")

    ga_col1, ga_col2 = st.columns([1, 2])
    with ga_col1:
        st.markdown("#### ⚙️ Evolution Settings")
        ga_gens = st.slider("Generations to Evolve", 10, 50, 25)
        ga_pop = st.slider("Population Chromosomes", 10, 40, 20)
        ga_mut = st.slider("Mutation Rate (%)", 5, 30, 15) / 100.0

        run_ga_btn = st.button("🚀 Evolve Champion Strategy", type="primary", use_container_width=True)

    with ga_col2:
        if run_ga_btn or "ga_results" in st.session_state:
            if run_ga_btn:
                with st.spinner("Simulating Darwinian evolutionary chromosome optimization across generations..."):
                    ga_res = run_genetic_algorithm_optimization(generations=ga_gens, population_size=ga_pop, mutation_rate=ga_mut)
                    st.session_state["ga_results"] = ga_res
            else:
                ga_res = st.session_state.get("ga_results")

            if ga_res:
                st.markdown("#### 🏆 Best Evolved Champion Strategy Chromosome")

        gac1, gac2, gac3, gac4 = st.columns(4)
        gac1.metric("Champion Fitness Score", f"{ga_res['best_fitness_score']:.3f}", "Optimal Genome")
        gac2.metric("Evolved Win Rate", f"{ga_res['optimized_win_rate_pct']:.1f}%")
        gac3.metric("Evolved Sharpe", f"{ga_res['optimized_sharpe_ratio']:.2f}")
        gac4.metric("Evolved Max DD", f"-{ga_res['optimized_max_drawdown_pct']:.1f}%", delta_color="inverse")

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

        st.markdown("##### 📈 Darwinian Fitness Progression Across Generations")
        df_fit = pd.DataFrame({
            "Generation": ga_res["fitness_progress"]["generation"],
            "Best Genome Fitness": ga_res["fitness_progress"]["best_fitness"],
            "Population Avg Fitness": ga_res["fitness_progress"]["avg_fitness"]
        })
        fig_fit = px.line(df_fit, x="Generation", y=["Best Genome Fitness", "Population Avg Fitness"], markers=True, color_discrete_sequence=["#00ff66", "#00eefc"])
        fig_fit.update_layout(height=280, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"))
        st.plotly_chart(fig_fit, use_container_width=True)
        else:
            render_empty_defensive_state(
                title="Ready for Evolutionary Optimization",
                message="Configure generation count, population size, and mutation rate on the left, then click 'Evolve Champion Strategy'.",
                action_text="Evolves RSI, ADX, and Volume thresholds using genetic algorithms."
            )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5: WALK-FORWARD ROLLING ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════
with backtest_tabs[4]:
    st.subheader("🔄 Walk-Forward Rolling Analysis (Out-of-Sample)")
    st.caption("Mitigate overfitting by sliding train/test windows across historical data and stitching true out-of-sample forward performance.")

    wf_col1, wf_col2 = st.columns([1, 3])

    with wf_col1:
        st.markdown("**Walk-Forward Settings:**")
        wf_symbol = st.selectbox("Asset for Walk-Forward", symbols, index=0, key="wf_symbol_select")
        wf_strat = st.selectbox(
            "Strategy Algorithm",
            [
                "Multi-Engine Confluence",
                "EMA Golden Cross Trend",
                "RSI Oversold Mean Reversion",
                "Volume Breakout Momentum",
            ],
            key="wf_strat_select"
        )
        wf_train = st.selectbox("In-Sample Train Window", [63, 126, 252], index=1, format_func=lambda x: f"{x} Days (~{x//21}m)", key="wf_train_sel")
        wf_test = st.selectbox("Out-of-Sample Test Window", [21, 42, 63], index=0, format_func=lambda x: f"{x} Days (~{x//21}m)", key="wf_test_sel")
        wf_cap = st.number_input("Starting Capital (₹)", value=100000.0, step=10000.0, key="wf_cap_input")

        run_wf_btn = st.button("🚀 Run Walk-Forward Analysis", type="primary", use_container_width=True)

    with wf_col2:
        if run_wf_btn or "wf_results" in st.session_state:
            if run_wf_btn:
                wf_sess = get_session(engine)
                with st.spinner(f"Computing rolling walk-forward slices for {wf_symbol}..."):
                    wf_res = run_walk_forward_backtest(
                        symbol=wf_symbol,
                        strategy_name=wf_strat,
                        session=wf_sess,
                        train_days=wf_train,
                        test_days=wf_test,
                        initial_capital=wf_cap,
                    )
                wf_sess.close()
                st.session_state["wf_results"] = wf_res

            wf_res = st.session_state.get("wf_results", {})

            if "error" in wf_res:
                st.error(wf_res["error"])
            elif wf_res:
                wk1, wk2, wk3, wk4 = st.columns(4)
                ret_color = "normal" if wf_res["total_oos_return_pct"] >= 0 else "inverse"
                wk1.metric("Total Out-of-Sample Return", f"{wf_res['total_oos_return_pct']:+.2f}%", delta_color=ret_color)
                wk2.metric("Window Consistency", f"{wf_res['window_consistency_pct']:.1f}%", f"{wf_res['profitable_windows']}/{wf_res['total_windows']} Profitable")
                wk3.metric("Avg Window Sharpe", f"{wf_res['avg_window_sharpe']:.2f}")
                wk4.metric("Ending Capital", f"₹{wf_res['final_capital']:,.0f}", f"Initial: ₹{wf_res['initial_capital']:,.0f}")

                st.markdown("---")

                st.markdown("##### 📈 Stitched Out-of-Sample Equity Curve (Pure Forward Performance)")
                df_eq = pd.DataFrame({
                    "Date": wf_res["stitched_dates"],
                    "Portfolio Value": wf_res["stitched_equity"]
                })
                fig_eq = px.line(df_eq, x="Date", y="Portfolio Value", color_discrete_sequence=["#00ff66"])
                fig_eq.update_layout(
                    height=300,
                    margin=dict(l=10, r=10, t=20, b=10),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#e0e0e0"),
                    yaxis=dict(gridcolor="#21262d", title="Capital (₹)"),
                    xaxis=dict(gridcolor="#21262d")
                )
                st.plotly_chart(fig_eq, use_container_width=True)

                st.markdown("##### 🔬 Window-by-Window Out-of-Sample Breakdown")
                df_win = pd.DataFrame(wf_res["windows"])
                st.dataframe(
                    df_win.rename(columns={
                        "window": "Window #",
                        "test_start": "Test Start",
                        "test_end": "Test End",
                        "return_pct": "Return %",
                        "sharpe": "Sharpe Ratio",
                        "trades": "Trades",
                        "win_rate": "Win Rate %",
                        "end_capital": "Ending Capital (₹)"
                    }).style.format({
                        "Return %": "{:+.2f}%",
                        "Sharpe Ratio": "{:.2f}",
                        "Win Rate %": "{:.1f}%",
                        "Ending Capital (₹)": "₹{:,.0f}"
                    }),
                    use_container_width=True,
                    hide_index=True
                )
        else:
            render_empty_defensive_state(
                title="Walk-Forward Rolling Analysis",
                message="Configure rolling window parameters on the left and click 'Run Walk-Forward Analysis' to test true out-of-sample robustness.",
                action_text="Select asset and sliding window sizes to begin."
            )
'''

target_file.write_text(script_content, encoding="utf-8")
print("Reconstructed 7_Backtesting.py successfully.")
