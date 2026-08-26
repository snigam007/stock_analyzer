"""
Bridgewater All-Weather Risk Parity & Hierarchical Risk Parity (HRP) Engine
- Equal Risk Contribution (ERC) portfolio allocation
- Marcos Lopez de Prado Hierarchical Risk Parity (HRP):
  1. Hierarchical tree clustering on correlation matrix
  2. Quasi-diagonalization matrix seriation
  3. Recursive bisection inverse-variance allocation
"""
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, dendrogram
from scipy.spatial.distance import squareform

logger = logging.getLogger(__name__)


def compute_hierarchical_risk_parity(
    returns_df: pd.DataFrame,
    symbols: Optional[List[str]] = None
) -> Dict:
    """Computes Hierarchical Risk Parity (HRP) and Equal Risk Contribution (ERC) weights."""
    if returns_df.empty or len(returns_df.columns) < 2:
        return {}

    df = returns_df.dropna()
    cols = symbols if symbols else list(df.columns)
    df = df[cols]

    cov_matrix = df.cov().values
    corr_matrix = df.corr().values
    n = len(cols)

    # 1. Distance matrix: d_i,j = sqrt(0.5 * (1 - rho_i,j))
    dist_matrix = np.sqrt(np.clip(0.5 * (1.0 - corr_matrix), 0.0, 1.0))
    np.fill_diagonal(dist_matrix, 0.0)

    # 2. Hierarchical Clustering Linkage
    condensed_dist = squareform(dist_matrix)
    link = linkage(condensed_dist, method="single")

    # 3. Quasi-Diagonalization (Sort clusters)
    def get_quasi_diag(link_matrix):
        link_matrix = link_matrix.astype(int)
        sort_ix = pd.Series([link_matrix[-1, 0], link_matrix[-1, 1]])
        num_items = link_matrix[-1, 3]
        while sort_ix.max() >= num_items:
            sort_ix.index = range(0, sort_ix.shape[0] * 2, 2)
            df0 = sort_ix[sort_ix >= num_items]
            i = df0.index
            j = df0.values - num_items
            sort_ix[i] = link_matrix[j, 0]
            df0 = pd.Series(link_matrix[j, 1], index=i + 1)
            sort_ix = pd.concat([sort_ix, df0]).sort_index()
            sort_ix.index = range(sort_ix.shape[0])
        return sort_ix.tolist()

    sorted_ix = get_quasi_diag(link)
    sorted_cols = [cols[i] for i in sorted_ix]

    # 4. Recursive Bisection Allocation
    def get_cluster_var(cov, c_items):
        cov_slice = cov[np.ix_(c_items, c_items)]
        w_ivp = 1.0 / np.diag(cov_slice)
        w_ivp /= np.sum(w_ivp)
        return float(np.dot(np.dot(w_ivp, cov_slice), w_ivp))

    weights = pd.Series(1.0, index=sorted_ix)
    clusters = [sorted_ix]

    while len(clusters) > 0:
        clusters = [c[start:end] for c in clusters for start, end in ((0, len(c) // 2), (len(c) // 2, len(c))) if len(c) > 1]
        for i in range(0, len(clusters), 2):
            c0 = clusters[i]
            c1 = clusters[i + 1]
            var0 = get_cluster_var(cov_matrix, c0)
            var1 = get_cluster_var(cov_matrix, c1)
            alpha = 1.0 - var0 / (var0 + var1)
            weights[c0] *= alpha
            weights[c1] *= 1.0 - alpha

    hrp_weights = {}
    for idx, w in zip(sorted_ix, weights):
        hrp_weights[cols[idx]] = round(float(w) * 100.0, 2)

    # 5. Inverse-Volatility Equal Risk Contribution (ERC) baseline
    vols = np.sqrt(np.diag(cov_matrix))
    inv_vols = 1.0 / np.maximum(vols, 1e-6)
    erc_raw = inv_vols / np.sum(inv_vols)
    erc_weights = {col: round(float(w) * 100.0, 2) for col, w in zip(cols, erc_raw)}

    # Expected Portfolio Metrics
    hrp_w_vec = np.array([hrp_weights[c] / 100.0 for c in cols])
    port_vol_hrp = float(np.sqrt(np.dot(np.dot(hrp_w_vec, cov_matrix * 252.0), hrp_w_vec))) * 100.0
    mean_ret = df.mean().values * 252.0
    port_ret_hrp = float(np.dot(hrp_w_vec, mean_ret)) * 100.0
    sharpe_hrp = round((port_ret_hrp - 6.5) / max(0.01, port_vol_hrp), 2)

    return {
        "hrp_weights": hrp_weights,
        "erc_weights": erc_weights,
        "expected_return_pct": round(port_ret_hrp, 2),
        "annual_volatility_pct": round(port_vol_hrp, 2),
        "sharpe_ratio": sharpe_hrp,
        "sorted_symbols": sorted_cols,
        "allocation_table": [
            {
                "symbol": c,
                "hrp_weight_pct": hrp_weights[c],
                "erc_weight_pct": erc_weights[c],
                "individual_annual_vol_pct": round(float(vols[i] * np.sqrt(252.0) * 100.0), 2)
            }
            for i, c in enumerate(cols)
        ]
    }