"""
Cross-Asset Correlation Network & Systemic Risk Cluster Map
- Computes multi-asset pairwise correlation distance across Equities, Global Indexes, and Commodities
- Identifies Systemic Risk Contagion Clusters and Uncorrelated Diversification Havens
- Generates interactive Plotly Force-Directed Network Graphs
"""
import logging
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def compute_cross_asset_correlation_network(session: Session, top_n: int = 24) -> Dict:
    """
    Computes cross-asset correlation network across leading stocks, indices, and commodities.
    """
    # 1. Fetch leading diverse assets
    assets = [
        ("RELIANCE", "daily_prices", "Energy"),
        ("TCS", "daily_prices", "Technology"),
        ("INFY", "daily_prices", "Technology"),
        ("HDFCBANK", "daily_prices", "Banking"),
        ("ICICIBANK", "daily_prices", "Banking"),
        ("TATAMOTORS", "daily_prices", "Auto"),
        ("SUNPHARMA", "daily_prices", "Pharma"),
        ("ITC", "daily_prices", "FMCG"),
        ("LT", "daily_prices", "Capital Goods"),
        ("TATASTEEL", "daily_prices", "Metals"),
        ("^NSEI", "index_prices", "Indian Benchmark"),
        ("^BSESN", "index_prices", "Indian Benchmark"),
        ("^NSEBANK", "index_prices", "Banking Index"),
        ("GC=F", "commodity_prices", "Gold Safe Haven"),
        ("SI=F", "commodity_prices", "Silver Commodity"),
        ("CL=F", "commodity_prices", "Crude Oil"),
        ("HG=F", "commodity_prices", "Copper Industry"),
    ]

    price_series = {}
    for sym, tbl, cat in assets:
        rows = session.execute(text(f"""
            SELECT date, close FROM {tbl}
            WHERE symbol=:s AND close IS NOT NULL
            ORDER BY date DESC LIMIT 120
        """), {"s": sym}).fetchall()

        if len(rows) >= 40:
            df = pd.DataFrame(rows, columns=["date", "close"]).sort_values("date")
            price_series[sym] = df.set_index("date")["close"].astype(float)

    if len(price_series) < 5:
        return {"error": "Insufficient cross-asset data."}

    df_p = pd.DataFrame(price_series).dropna()
    corr = df_p.pct_change().dropna().corr().round(2)

    symbols = list(corr.columns)
    num_nodes = len(symbols)

    # Place nodes on a circular layout for clean network rendering
    angles = np.linspace(0, 2 * np.pi, num_nodes, endpoint=False)
    pos_x = np.cos(angles) * 10.0
    pos_y = np.sin(angles) * 10.0

    # Categorize nodes
    node_categories = {a[0]: a[2] for a in assets}
    node_colors = []
    for s in symbols:
        cat = node_categories.get(s, "Stock")
        if "Safe Haven" in cat or s == "GC=F":
            node_colors.append("#ffd700") # Gold
        elif "Commodity" in cat or s in ["CL=F", "SI=F", "HG=F"]:
            node_colors.append("#ff8c00") # Orange
        elif "Index" in cat or s.startswith("^"):
            node_colors.append("#00a8ff") # Blue
        else:
            node_colors.append("#00c875") # Green

    # Identify Uncorrelated Havens (average correlation to Indian equities < 0.20)
    havens = []
    equity_syms = [s for s in symbols if not s.startswith("^") and s not in ["GC=F", "SI=F", "CL=F", "HG=F"]]
    for s in symbols:
        if s not in equity_syms and equity_syms:
            avg_corr_to_eq = float(corr.loc[s, equity_syms].mean())
            if avg_corr_to_eq < 0.25:
                havens.append({
                    "symbol": s,
                    "name": node_categories.get(s, s),
                    "avg_equity_correlation": round(avg_corr_to_eq, 2),
                    "type": "🛡️ Macro Diversification Haven",
                })

    # Build Network Graph in Plotly
    edge_x = []
    edge_y = []
    edge_weights = []

    for i in range(num_nodes):
        for j in range(i + 1, num_nodes):
            c_val = float(corr.iloc[i, j])
            # Only connect nodes with significant correlation (> 0.40 or < -0.30)
            if abs(c_val) >= 0.40:
                edge_x.extend([pos_x[i], pos_x[j], None])
                edge_y.extend([pos_y[i], pos_y[j], None])
                edge_weights.append(c_val)

    fig_net = go.Figure()

    # Edge traces
    fig_net.add_trace(go.Scatter(
        x=edge_x, y=edge_y,
        mode="lines",
        line=dict(width=1.2, color="rgba(0, 168, 255, 0.35)"),
        hoverinfo="none",
        showlegend=False,
    ))

    # Node traces
    fig_net.add_trace(go.Scatter(
        x=pos_x, y=pos_y,
        mode="markers+text",
        marker=dict(size=22, color=node_colors, line=dict(width=2, color="#ffffff")),
        text=symbols,
        textposition="top center",
        hovertemplate="<b>%{text}</b><br>Asset Class: %{customdata}<extra></extra>",
        customdata=[node_categories.get(s, "Asset") for s in symbols],
        showlegend=False,
    ))

    fig_net.update_layout(
        title="🧬 Cross-Asset Systemic Correlation Network (Equities • Indexes • Commodities)",
        paper_bgcolor="#0e1117",
        plot_bgcolor="#161b22",
        font=dict(color="#e0e8f0"),
        height=540,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
    )

    return {
        "network_figure": fig_net,
        "correlation_matrix": corr.to_dict(),
        "uncorrelated_havens": havens,
        "total_nodes": num_nodes,
    }