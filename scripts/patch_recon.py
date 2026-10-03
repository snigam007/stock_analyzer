from pathlib import Path

target = Path(r"c:\Users\SNigam2\.gemini\antigravity\scratch\stock_analyzer\scripts\reconstruct_7_backtesting.py")
content = target.read_text(encoding="utf-8")

old_text = """    with ga_col2:
        st.markdown("#### 🏆 Best Evolved Champion Strategy Chromosome")
        ga_res = run_genetic_algorithm_optimization(generations=ga_gens, population_size=ga_pop, mutation_rate=ga_mut)"""

new_text = """    with ga_col2:
        if run_ga_btn or "ga_results" in st.session_state:
            if run_ga_btn:
                with st.spinner("Simulating Darwinian evolutionary chromosome optimization across generations..."):
                    ga_res = run_genetic_algorithm_optimization(generations=ga_gens, population_size=ga_pop, mutation_rate=ga_mut)
                    st.session_state["ga_results"] = ga_res
            else:
                ga_res = st.session_state.get("ga_results")

            if ga_res:
                st.markdown("#### 🏆 Best Evolved Champion Strategy Chromosome")"""

old_end = """        st.plotly_chart(fig_fit, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5: WALK-FORWARD ROLLING ANALYSIS"""

new_end = """        st.plotly_chart(fig_fit, use_container_width=True)
        else:
            render_empty_defensive_state(
                title="Ready for Evolutionary Optimization",
                message="Configure generation count, population size, and mutation rate on the left, then click 'Evolve Champion Strategy'.",
                action_text="Evolves RSI, ADX, and Volume thresholds using genetic algorithms."
            )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5: WALK-FORWARD ROLLING ANALYSIS"""

content_norm = content.replace("\r\n", "\n")
old_norm = old_text.replace("\r\n", "\n")
new_norm = new_text.replace("\r\n", "\n")
old_end_norm = old_end.replace("\r\n", "\n")
new_end_norm = new_end.replace("\r\n", "\n")

if old_norm in content_norm and old_end_norm in content_norm:
    res = content_norm.replace(old_norm, new_norm).replace(old_end_norm, new_end_norm)
    target.write_text(res, encoding="utf-8")
    print("reconstruct_7_backtesting.py patched successfully!")
else:
    print("Match failed:", old_norm in content_norm, old_end_norm in content_norm)
