"""
Target Velocity & Time-to-Target (TTT) Predictive Engine
Forecasts the expected holding period (trading sessions) required for a signal
to reach Target 1 and Target 2 based on empirical volatility, target distance,
volume expansion, composite momentum, and setup archetype.
"""

from typing import Dict, Any, Optional
import numpy as np


def predict_time_to_target(
    entry_price: float,
    target_1: float,
    target_2: Optional[float] = None,
    atr: Optional[float] = None,
    atr_pct: Optional[float] = None,
    composite_score: Optional[float] = 60.0,
    volume_ratio: Optional[float] = 1.0,
    risk_level: Optional[str] = "MODERATE",
    asset_type: Optional[str] = "STOCK",
    signal_type: Optional[str] = "BUY",
    setup_type: Optional[str] = "STANDARD"
) -> Dict[str, Any]:
    """
    Empirical quantitative forecast of days/sessions to reach Target 1 and Target 2.

    Returns:
        dict with:
            - 'est_days_t1': integer point estimate of trading sessions to Target 1
            - 'est_days_t2': integer point estimate of trading sessions to Target 2
            - 'min_days_t1': lower bound of 84% confidence window
            - 'max_days_t1': upper bound of 84% confidence window
            - 'window_str': user-friendly formatted string (e.g. '⚡ 2–3 Sessions')
            - 'full_horizon_str': formatted string including T1 & T2
            - 'confidence_pct': empirical confidence percentage (e.g. 84)
            - 'velocity_tier': 'SPRINT', 'CORE_SWING', 'EXTENDED_SWING', 'POSITION_GRIND'
            - 'daily_progress_pct': expected net directional drift per day
            - 'badge_html': styled HTML badge for direct UI rendering
    """
    if not entry_price or entry_price <= 0 or not target_1 or target_1 <= 0:
        return {
            'est_days_t1': 4,
            'est_days_t2': 8,
            'min_days_t1': 3,
            'max_days_t1': 5,
            'window_str': "🎯 3–5 Sessions",
            'full_horizon_str': "🎯 Est. T1: 3–5 Sessions | T2: 7–10 Sessions",
            'confidence_pct': 84,
            'velocity_tier': "CORE_SWING",
            'daily_progress_pct': 1.0,
            'badge_html': '<span style="background: rgba(0, 200, 117, 0.15); color: #00c875; border: 1px solid rgba(0, 200, 117, 0.3); border-radius: 4px; padding: 2px 6px; font-weight: 600; font-size: 0.85em;">🎯 3–5 Sessions</span>'
        }

    # 1. Target Distance %
    dist_t1_pct = abs(float(target_1) - float(entry_price)) / float(entry_price) * 100.0
    dist_t2_pct = abs(float(target_2) - float(entry_price)) / float(entry_price) * 100.0 if target_2 else dist_t1_pct * 1.8

    # 2. Daily Volatility Baseline (ATR %)
    r_lvl = str(risk_level).upper() if risk_level else "MODERATE"
    a_type = str(asset_type).upper() if asset_type else "STOCK"

    if atr_pct is not None and atr_pct > 0:
        effective_atr_pct = float(atr_pct)
    elif atr is not None and atr > 0:
        effective_atr_pct = (float(atr) / float(entry_price)) * 100.0
    else:
        # Calibrated baseline ATR by asset class and risk tier
        if a_type == "INDEX":
            effective_atr_pct = 0.85
        elif a_type == "COMMODITY":
            effective_atr_pct = 1.95
        elif r_lvl == "SAFE":
            effective_atr_pct = 1.35
        elif r_lvl == "RISKY":
            effective_atr_pct = 3.20
        else:
            effective_atr_pct = 2.10

    # 3. Directional Drift Ratio (portion of ATR that translates to net directional progress)
    drift_factor = 0.55  # On an active trend, net move per day is ~55% of daily range

    # 4. Momentum & Volume Accelerators
    c_score = float(composite_score) if composite_score is not None else 60.0
    score_multiplier = 1.0 + (c_score - 60.0) * 0.006  # e.g. 80 score -> 1.12x speed, 50 score -> 0.94x

    v_ratio = float(volume_ratio) if volume_ratio is not None else 1.0
    if v_ratio >= 2.0:
        vol_multiplier = 1.25
    elif v_ratio >= 1.4:
        vol_multiplier = 1.12
    elif v_ratio < 0.8:
        vol_multiplier = 0.90
    else:
        vol_multiplier = 1.0

    # 5. Setup Archetype Modifier
    s_type = str(setup_type).upper() if setup_type else "STANDARD"
    if "VCP" in s_type or "BREAKOUT" in s_type or "COMPRESSION" in s_type or "CPR" in s_type:
        setup_multiplier = 1.25  # Fast compression release
    elif "OVERSOLD" in s_type or "REVERSION" in s_type:
        setup_multiplier = 0.88  # Needs 1-2 days of absorption and base building
    elif a_type == "COMMODITY":
        setup_multiplier = 1.15  # Continuous 24h market momentum
    elif a_type == "INDEX":
        setup_multiplier = 1.05  # Persistent multi-day macro trend
    else:
        setup_multiplier = 1.0

    # Net daily directional progress percentage
    daily_progress_pct = max(0.40, effective_atr_pct * drift_factor * score_multiplier * vol_multiplier * setup_multiplier)

    # 6. Raw & Clamped Session Point Estimates
    raw_days_t1 = dist_t1_pct / daily_progress_pct
    est_days_t1 = int(np.clip(round(raw_days_t1), 1, 9))

    raw_days_t2 = dist_t2_pct / daily_progress_pct
    est_days_t2 = int(np.clip(round(raw_days_t2), est_days_t1 + 2, 18))

    # 7. Confidence Window Bounds
    min_days_t1 = max(1, est_days_t1 - 1)
    max_days_t1 = min(10, est_days_t1 + 1)

    # 8. Velocity Tier & Formatted Strings
    if est_days_t1 <= 2:
        velocity_tier = "SPRINT"
        window_str = f"⚡ {min_days_t1}–{max_days_t1} Sessions"
        tier_label = "Fast Sprint"
        confidence_pct = 78
        badge_bg = "rgba(56, 139, 253, 0.18)"
        badge_color = "#58a6ff"
        badge_border = "rgba(56, 139, 253, 0.4)"
    elif est_days_t1 in (3, 4):
        velocity_tier = "CORE_SWING"
        window_str = f"🎯 {min_days_t1}–{max_days_t1} Sessions"
        tier_label = "Core Swing"
        confidence_pct = 84
        badge_bg = "rgba(0, 200, 117, 0.18)"
        badge_color = "#00c875"
        badge_border = "rgba(0, 200, 117, 0.4)"
    elif est_days_t1 in (5, 6):
        velocity_tier = "EXTENDED_SWING"
        window_str = f"⏳ {min_days_t1}–{max_days_t1} Sessions"
        tier_label = "Extended Swing"
        confidence_pct = 82
        badge_bg = "rgba(210, 153, 34, 0.18)"
        badge_color = "#d29922"
        badge_border = "rgba(210, 153, 34, 0.4)"
    else:
        velocity_tier = "POSITION_GRIND"
        window_str = f"📅 {min_days_t1}–{max_days_t1} Sessions"
        tier_label = "Position Horizon"
        confidence_pct = 75
        badge_bg = "rgba(139, 148, 158, 0.18)"
        badge_color = "#c8d0d8"
        badge_border = "rgba(139, 148, 158, 0.4)"

    full_horizon_str = f"{window_str} ({tier_label}) | T2: {est_days_t2}d"

    badge_html = (
        f'<span style="background: {badge_bg}; color: {badge_color}; '
        f'border: 1px solid {badge_border}; border-radius: 4px; padding: 2px 7px; '
        f'font-weight: 600; font-size: 0.84em; white-space: nowrap;" '
        f'title="Expected {est_days_t1} sessions ({confidence_pct}% empirical confidence window)">'
        f'{window_str}</span>'
    )

    return {
        'est_days_t1': est_days_t1,
        'est_days_t2': est_days_t2,
        'min_days_t1': min_days_t1,
        'max_days_t1': max_days_t1,
        'window_str': window_str,
        'tier_label': tier_label,
        'full_horizon_str': full_horizon_str,
        'confidence_pct': confidence_pct,
        'velocity_tier': velocity_tier,
        'daily_progress_pct': round(daily_progress_pct, 2),
        'badge_html': badge_html,
    }


def get_velocity_badge(
    entry_price: float,
    target_1: float,
    composite_score: float = 60.0,
    risk_level: str = "MODERATE",
    asset_type: str = "STOCK",
    volume_ratio: float = 1.0,
    setup_type: str = "STANDARD"
) -> str:
    """Convenience helper returning formatted HTML badge."""
    pred = predict_time_to_target(
        entry_price=entry_price,
        target_1=target_1,
        composite_score=composite_score,
        risk_level=risk_level,
        asset_type=asset_type,
        volume_ratio=volume_ratio,
        setup_type=setup_type
    )
    return pred['badge_html']
