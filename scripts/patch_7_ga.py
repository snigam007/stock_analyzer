from pathlib import Path

target = Path(r"c:\Users\SNigam2\.gemini\antigravity\scratch\stock_analyzer\pages\7_Backtesting.py")
content = target.read_text(encoding="utf-8")

old_block = """    with ga_col2:
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
        fig_fit = px.line(df_fit, x="Generation", y=["Best Genome Fitness", "Population Avg Fitness"], markers=True, color_discrete_sequence=["#00ff66", "#00eefc"])
        fig_fit.update_layout(height=280, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"))
        st.plotly_chart(fig_fit, use_container_width=True)"""

new_block = """    with ga_col2:
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
                fig_fit = px.line(df_fit, x="Generation", y=["Best Genome Fitness", "Population Avg Fitness"], markers=True, color_discrete_sequence=["#00ff66", "#00eefc"])
                fig_fit.update_layout(height=280, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"))
                st.plotly_chart(fig_fit, use_container_width=True)
        else:
            render_empty_defensive_state(
                title="Ready for Evolutionary Optimization",
                message="Configure generation count, population size, and mutation rate on the left, then click 'Evolve Champion Strategy'.",
                action_text="Evolves RSI, ADX, and Volume thresholds using genetic algorithms."
            )"""

content_normalized = content.replace("\r\n", "\n")
old_normalized = old_block.replace("\r\n", "\n")
new_normalized = new_block.replace("\r\n", "\n")

if old_normalized in content_normalized:
    updated = content_normalized.replace(old_normalized, new_normalized)
    target.write_text(updated, encoding="utf-8")
    print("GA gated successfully!")
else:
    print("WARNING: old_block not found in content!")
