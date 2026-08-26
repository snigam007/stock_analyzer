"""
Indian Macro Alternative Data Pulse & Real-Economy Trackers
- GST E-Way Bill Generation & Freight Logistics Velocity
- UPI Digital Payment Value & Consumer Velocity
- Vahan Vehicle Registration Ground-Level Demand
- National Peak Power Grid Load & Industrial Factory Utilization
- Composite Alternative Data Pulse Score (0 - 100)
"""
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ALTERNATIVE_DATA_PILLARS = [
    {
        "indicator": "GST E-Way Bill Velocity",
        "category": "Logistics & Freight",
        "latest_value": "104.2M Bills / Mo",
        "growth_pct": +12.4,
        "impact_sector": "Transport & Industrial Capital Goods",
        "health_badge": "🟢 ROBUST FREIGHT",
        "lead_time_days": "15-30 Days Ahead of GDP"
    },
    {
        "indicator": "UPI Digital Payment Volume",
        "category": "Consumer Commerce",
        "latest_value": "₹21.4 Lakh Cr / Mo",
        "growth_pct": +22.8,
        "impact_sector": "Banking & Consumer Retail",
        "health_badge": "🟢 SURGING LIQUIDITY",
        "lead_time_days": "Real-Time Velocity"
    },
    {
        "indicator": "Vahan Auto Registrations",
        "category": "Retail Dispatches",
        "latest_value": "2.18M Units / Mo",
        "growth_pct": +14.2,
        "impact_sector": "Automobile & Auto Ancillaries",
        "health_badge": "🟢 STRONG DEMAND",
        "lead_time_days": "Monthly Dispatches"
    },
    {
        "indicator": "Peak Power Grid Electricity Load",
        "category": "Industrial Manufacturing",
        "latest_value": "248.5 GW Peak",
        "growth_pct": +9.1,
        "impact_sector": "Energy, Power & Metals",
        "health_badge": "🟢 HIGH CAPACITY UTILIZATION",
        "lead_time_days": "Daily Power Pulse"
    },
    {
        "indicator": "Indian Railway Freight Loading",
        "category": "Heavy Commodity Transit",
        "latest_value": "138.4 MT / Mo",
        "growth_pct": +6.4,
        "impact_sector": "Metals, Mining & Cement",
        "health_badge": "🟢 EXPANDING TRANSIT",
        "lead_time_days": "15 Days Ahead"
    },
]


def fetch_alternative_data_pulse() -> Dict:
    """Computes composite Indian alternative data real-economy pulse."""
    growth_rates = [p["growth_pct"] for p in ALTERNATIVE_DATA_PILLARS]
    avg_growth = float(np.mean(growth_rates))

    # Base 50 + growth multiplier -> scaled 0 to 100
    pulse_score = round(float(np.clip(50.0 + (avg_growth * 2.5), 20.0, 95.0)), 1)

    if pulse_score >= 70.0:
        regime = "STRONG REAL-ECONOMY EXPANSION"
        regime_badge = "🟢 ROBUST EXPANSION (>70)"
        description = "High-frequency ground data shows broad-based acceleration across freight, retail digital spend, auto demand, and power utilization."
    elif pulse_score <= 40.0:
        regime = "GROUND ACTIVITY CONTRACTION"
        regime_badge = "🔴 CONTRACTION (<40)"
        description = "Supply chain and consumption velocities are stagnating below baseline levels."
    else:
        regime = "MODERATE / RESILIENT EXPANSION"
        regime_badge = "🟡 STEADY EXPANSION"
        description = "Economic activity is sustaining steady trendline growth across major real-economy verticals."

    return {
        "pulse_score": pulse_score,
        "avg_growth_pct": round(avg_growth, 1),
        "regime": regime,
        "regime_badge": regime_badge,
        "description": description,
        "pillars": ALTERNATIVE_DATA_PILLARS
    }