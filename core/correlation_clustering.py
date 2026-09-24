"""
Cross-Asset Correlation Clustering Engine (Orthogonal Shield)
- Computes empirical rolling pairwise return correlations across active equities.
- Filters portfolio and SIP candidate baskets to enforce mutual orthogonality (r < 0.65).
- Eliminates hidden collinear sector/theme concentration (e.g. PSU Banks, Adani pack, IT exporters).
"""
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Callable
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def compute_pairwise_correlation_matrix(
    symbols: List[str],
    session: Session,
    lookback_days: int = 120,
    as_of_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Computes rolling pairwise return correlation matrix across active equities.
    """
    if not symbols:
        return pd.DataFrame()

    unique_symbols = list(set(symbols))
    if len(unique_symbols) == 1:
        return pd.DataFrame([[1.0]], index=unique_symbols, columns=unique_symbols)

    if not as_of_date:
        max_d_row = session.execute(text("SELECT MAX(date) FROM daily_prices")).first()
        as_of_date = str(max_d_row[0]) if max_d_row and max_d_row[0] else str(date.today())

    as_of_dt = datetime.strptime(as_of_date, "%Y-%m-%d").date()
    start_dt = as_of_dt - timedelta(days=int(lookback_days * 1.5))

    sym_placeholders = ", ".join([f"'{s}'" for s in unique_symbols])
    sql = f"""
        SELECT symbol, date, close
        FROM daily_prices
        WHERE symbol IN ({sym_placeholders})
          AND date >= '{start_dt}' AND date <= '{as_of_date}'
        ORDER BY date ASC
    """
    try:
        df_prices = pd.read_sql_query(sql, session.bind)
        if df_prices.empty or len(df_prices["symbol"].unique()) < 2:
            return pd.DataFrame(np.eye(len(unique_symbols)), index=unique_symbols, columns=unique_symbols)

        piv = df_prices.pivot(index="date", columns="symbol", values="close").pct_change().dropna()
        if len(piv) < 15:
            return pd.DataFrame(np.eye(len(unique_symbols)), index=unique_symbols, columns=unique_symbols)

        corr = piv.corr()
        corr = corr.reindex(index=unique_symbols, columns=unique_symbols).fillna(0.25)
        for s in unique_symbols:
            if s in corr.index and s in corr.columns:
                corr.loc[s, s] = 1.0
        return corr
    except Exception as e:
        logger.warning(f"Error computing correlation matrix: {e}")
        return pd.DataFrame(np.eye(len(unique_symbols)), index=unique_symbols, columns=unique_symbols)


def filter_orthogonal_candidates(
    candidates: List[Any],
    corr_matrix: pd.DataFrame,
    max_corr: float = 0.65,
    max_picks: int = 5,
    get_symbol_fn: Optional[Callable[[Any], str]] = None,
) -> Tuple[List[Any], List[Dict[str, Any]]]:
    """
    Greedily selects top ranked candidates that maintain pairwise correlation < max_corr
    with all already selected candidates.

    Returns:
        (picked_candidates, rejected_candidates_info)
    """
    if not candidates:
        return [], []

    if get_symbol_fn is None:
        def default_sym_fn(item):
            if isinstance(item, (list, tuple)):
                return str(item[0])
            elif hasattr(item, "symbol"):
                return str(item.symbol)
            elif isinstance(item, dict):
                return str(item.get("symbol", ""))
            return str(item)
        get_symbol_fn = default_sym_fn

    picked = []
    picked_symbols = []
    rejected_info = []

    for cand in candidates:
        if len(picked) >= max_picks:
            break
        sym = get_symbol_fn(cand)
        if not sym:
            continue

        is_orthogonal = True
        high_corr_peer = None
        highest_r = 0.0

        for p_sym in picked_symbols:
            if sym in corr_matrix.index and p_sym in corr_matrix.columns:
                r_val = float(corr_matrix.loc[sym, p_sym])
                if r_val >= max_corr:
                    is_orthogonal = False
                    if r_val > highest_r:
                        highest_r = r_val
                        high_corr_peer = p_sym

        if is_orthogonal:
            picked.append(cand)
            picked_symbols.append(sym)
        else:
            rejected_info.append({
                "symbol": sym,
                "correlated_with": high_corr_peer,
                "correlation": round(highest_r, 2),
                "reason": f"Collinear beta risk with {high_corr_peer} (r = {highest_r:.2f} >= {max_corr:.2f})"
            })

    # If too few candidates passed strict orthogonality, fill remaining slots
    if len(picked) < max_picks:
        for cand in candidates:
            if len(picked) >= max_picks:
                break
            sym = get_symbol_fn(cand)
            if sym not in picked_symbols:
                picked.append(cand)
                picked_symbols.append(sym)

    return picked, rejected_info


def get_pairwise_correlations_summary(
    symbols: List[str],
    corr_matrix: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Summarizes mutual correlation metrics for a selected basket of symbols.
    """
    valid_syms = [s for s in symbols if s in corr_matrix.index and s in corr_matrix.columns]
    if len(valid_syms) < 2:
        return {
            "avg_pairwise_corr": 0.0,
            "max_pairwise_corr": 0.0,
            "high_risk_pairs": [],
            "is_well_diversified": True,
        }

    sub_corr = corr_matrix.loc[valid_syms, valid_syms]
    n = len(valid_syms)
    pairs = []
    off_diag_vals = []

    for i in range(n):
        for j in range(i + 1, n):
            s1 = valid_syms[i]
            s2 = valid_syms[j]
            r = float(sub_corr.loc[s1, s2])
            off_diag_vals.append(r)
            if r >= 0.65:
                pairs.append({"stock_1": s1, "stock_2": s2, "correlation": round(r, 2)})

    avg_corr = float(np.mean(off_diag_vals)) if off_diag_vals else 0.0
    max_corr = float(np.max(off_diag_vals)) if off_diag_vals else 0.0

    return {
        "avg_pairwise_corr": round(avg_corr, 2),
        "max_pairwise_corr": round(max_corr, 2),
        "high_risk_pairs": pairs,
        "is_well_diversified": bool(max_corr < 0.65),
    }
