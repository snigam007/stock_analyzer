"""
Sector Cluster and Market Cap Tier Profiler
3 Cap-Tier x 4 Sector-Cluster Adaptive Quantitative Matrix

Clusters:
1. BFSI (Banking, Financial Services & Insurance)
2. CYCLICAL (Global Commodities, Metals & Mining, Energy, Chemicals)
3. DEFENSIVE (Pharma, FMCG, IT Services)
4. CAPEX_MOMENTUM (Capital Goods, Infrastructure, Auto, Realty, Logistics)
"""
from typing import Dict, Tuple

# ── Sector to Cluster Mapping ──────────────────────────────────────────────────
SECTOR_TO_CLUSTER_MAP = {
    # 1. BFSI
    "Banking & Finance": "BFSI",
    "Financial Services": "BFSI",
    "Banks": "BFSI",
    "NBFC": "BFSI",

    # 2. Global Cyclicals & Commodities
    "Metals & Mining": "CYCLICAL",
    "Energy & Power": "CYCLICAL",
    "Chemicals & Specialty": "CYCLICAL",
    "Oil & Gas": "CYCLICAL",

    # 3. Defensives & Quality Growth
    "Pharmaceuticals & Healthcare": "DEFENSIVE",
    "FMCG & Consumer Staples": "DEFENSIVE",
    "IT & Technology": "DEFENSIVE",

    # 4. Domestic Capex & Momentum
    "Capital Goods & Engineering": "CAPEX_MOMENTUM",
    "Construction & Infrastructure": "CAPEX_MOMENTUM",
    "Automobiles & Auto Ancillaries": "CAPEX_MOMENTUM",
    "Real Estate": "CAPEX_MOMENTUM",
    "Logistics & Transportation": "CAPEX_MOMENTUM",
    "Agriculture, Fertilizers & Agro": "CAPEX_MOMENTUM",
    "Telecom & Media": "CAPEX_MOMENTUM",
    "Consumer Discretionary & Retail": "CAPEX_MOMENTUM",
    "Textiles & Apparel": "CAPEX_MOMENTUM",
}

CLUSTER_METADATA = {
    "BFSI": {
        "label": "Banking & Finance",
        "icon": "🏦",
        "badge": "🏦 BFSI",
        "color": "#388bfd",
        "desc": "Rate-sensitive credit cycle; driven by F&O Max Pain, PCR, and credit quality.",
    },
    "CYCLICAL": {
        "label": "Global Cyclicals",
        "icon": "⛏️",
        "badge": "⛏️ Cyclical",
        "color": "#d29922",
        "desc": "Global commodity cycle; contrarian accumulation favored over breakout chasing.",
    },
    "DEFENSIVE": {
        "label": "Defensives & Quality",
        "icon": "🏰",
        "badge": "🏰 Defensive",
        "color": "#00c875",
        "desc": "High ROCE & steady compounding; strong Piotroski quality and low beta.",
    },
    "CAPEX_MOMENTUM": {
        "label": "Domestic Capex",
        "icon": "🏗️",
        "badge": "🏗️ Capex Momentum",
        "color": "#a371f7",
        "desc": "Order-book driven momentum; high Wyckoff VSA volume absorption and trend persistence.",
    },
}

# ── Cap Tier Calibration Parameters ───────────────────────────────────────────
CAP_TIER_PARAMETERS = {
    "large": {
        "buy_threshold": 57.0,       # More sensitive for slow, high-institutional grinders
        "sell_threshold": 44.0,
        "min_volume_ratio": 1.15,     # Steady block accumulation doesn't require retail volume spikes
        "target_1_floor_pct": 0.025,  # 2.5% Target 1 floor (calibrated to ~1.4% ATR)
        "target_1_atr_mult": 1.4,
        "target_2_floor_pct": 0.050,  # 5.0% Target 2 floor
        "target_2_atr_mult": 2.8,
        "target_3_floor_pct": 0.090,  # 9.0% Target 3 floor
        "target_3_atr_mult": 4.5,
        "sl_floor_pct": 0.018,        # 1.8% SL floor (avoids unnecessary capital drag)
        "default_atr_pct": 0.016,
    },
    "mid": {
        "buy_threshold": 59.5,       # Standard momentum sweet spot
        "sell_threshold": 42.0,
        "min_volume_ratio": 1.25,
        "target_1_floor_pct": 0.038,  # 3.8% Target 1 floor
        "target_1_atr_mult": 1.8,
        "target_2_floor_pct": 0.075,  # 7.5% Target 2 floor
        "target_2_atr_mult": 3.5,
        "target_3_floor_pct": 0.140,  # 14.0% Target 3 floor
        "target_3_atr_mult": 6.0,
        "sl_floor_pct": 0.032,        # 3.2% SL floor
        "default_atr_pct": 0.026,
    },
    "small": {
        "buy_threshold": 63.5,       # Strict filter against low-volume retail traps/fakeouts
        "sell_threshold": 38.0,
        "min_volume_ratio": 1.75,     # High volume expansion required before confirming small-cap breakout
        "target_1_floor_pct": 0.060,  # 6.0% Target 1 floor (high beta compensates for risk)
        "target_1_atr_mult": 2.4,
        "target_2_floor_pct": 0.120,  # 12.0% Target 2 floor
        "target_2_atr_mult": 4.5,
        "target_3_floor_pct": 0.200,  # 20.0% Target 3 floor
        "target_3_atr_mult": 7.5,
        "sl_floor_pct": 0.055,        # 5.5% SL floor (immune to intraday bid-ask noise sweeps)
        "default_atr_pct": 0.042,
    },
}


def get_sector_cluster(sector: str) -> str:
    """Returns one of BFSI, CYCLICAL, DEFENSIVE, CAPEX_MOMENTUM."""
    if not sector:
        return "CAPEX_MOMENTUM"
    clean_sec = sector.strip()
    if clean_sec in SECTOR_TO_CLUSTER_MAP:
        return SECTOR_TO_CLUSTER_MAP[clean_sec]
    
    # Partial matching
    clean_upper = clean_sec.upper()
    if any(k in clean_upper for k in ["BANK", "FINANC", "INSUR", "INVEST"]):
        return "BFSI"
    if any(k in clean_upper for k in ["METAL", "MINING", "STEEL", "ENERGY", "POWER", "CHEMIC", "OIL", "GAS"]):
        return "CYCLICAL"
    if any(k in clean_upper for k in ["PHARMA", "HEALTH", "FMCG", "STAPLE", "TECH", "IT"]):
        return "DEFENSIVE"
    return "CAPEX_MOMENTUM"


def get_cluster_metadata(cluster: str) -> Dict:
    """Returns display metadata for a cluster."""
    return CLUSTER_METADATA.get(cluster, CLUSTER_METADATA["CAPEX_MOMENTUM"])


def get_cluster_pillar_weights(cluster: str, has_fno: bool, has_news: bool) -> Dict[str, float]:
    """
    Returns adaptive 5-pillar weights (Technical, Smart Money, Fundamentals, Derivatives, AI/News)
    customized by sector cluster archetype.
    """
    if cluster == "BFSI":
        # Financials: F&O PCR/Max Pain & Smart Money flows dominate; balance sheet uses credit metrics
        base = {"tech": 0.30, "sm": 0.25, "fund": 0.15, "deriv": 0.20, "ai": 0.10}
    elif cluster == "CYCLICAL":
        # Cyclicals: Commodity momentum & news drift heavily impact sentiment; technicals anchor entry
        base = {"tech": 0.30, "sm": 0.30, "fund": 0.15, "deriv": 0.10, "ai": 0.15}
    elif cluster == "DEFENSIVE":
        # Defensives: High fundamental fortress & balance sheet solvency (Piotroski) are primary alpha
        base = {"tech": 0.30, "sm": 0.20, "fund": 0.25, "deriv": 0.10, "ai": 0.15}
    else:  # CAPEX_MOMENTUM
        # Capex & Momentum: Technical momentum & Wyckoff volume absorption lead
        base = {"tech": 0.35, "sm": 0.30, "fund": 0.15, "deriv": 0.10, "ai": 0.10}

    # Redistribute missing components if stock lacks F&O or live news
    missing_deriv = base["deriv"] if not has_fno else 0.0
    missing_ai = (base["ai"] * 0.5) if not has_news else 0.0
    total_missing = missing_deriv + missing_ai

    w_tech = base["tech"] + total_missing * 0.55
    w_sm = base["sm"] + total_missing * 0.30
    w_fund = base["fund"] + total_missing * 0.15
    w_deriv = 0.0 if not has_fno else base["deriv"]
    w_ai = base["ai"] * 0.5 if not has_news else base["ai"]

    tot = max(0.01, w_tech + w_sm + w_fund + w_deriv + w_ai)
    return {
        "w_tech": w_tech / tot,
        "w_sm": w_sm / tot,
        "w_fund": w_fund / tot,
        "w_deriv": w_deriv / tot,
        "w_ai": w_ai / tot,
    }


def get_tier_parameters(tier: str) -> Dict:
    """Returns threshold and target configuration for a given market cap tier."""
    clean_tier = (tier or "mid").strip().lower()
    return CAP_TIER_PARAMETERS.get(clean_tier, CAP_TIER_PARAMETERS["mid"])
