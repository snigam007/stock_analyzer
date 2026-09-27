"""
config/retro_theme.py
🕹️ Retro Terminal Quant Design System
Emulates 1980s arcade cabinet operational UI, late-century CRT computer terminals,
and high-frequency algorithmic finance.

Aesthetic Pillars:
- Chunky Pixel Architecture (0px border-radius, stepped 3px-4px borders, 4px hard drop shadows).
- CRT Phosphor Glow & Scanlines (1px scanline texture, high-voltage neon emissions).
- Game-Loop Feedback (Discrete segmented health/mana bars, [ 1UP ] / [ S-RANK ] badges, blinking cursor).
- Precision Density (Space Grotesk uppercase headings + JetBrains Mono tabular figures).
"""

from typing import Dict, List, Optional, Any
import streamlit as st


# ─── COLOR PALETTE TOKENS ─────────────────────────────────────────────────────
RETRO_COLORS = {
    "surface": "#0f131d",
    "surface_dim": "#0f131d",
    "surface_container_lowest": "#0a0e18",
    "surface_container_low": "#171b26",
    "surface_container": "#1c1f2a",
    "surface_container_high": "#262a35",
    "surface_container_highest": "#313540",
    "on_surface": "#dfe2f1",
    "on_surface_bright": "#f8fafc",
    "outline": "#849581",
    "outline_variant": "#3b4b3a",
    "primary": "#00ff66",        # Neon Arcade Green (Bullish / 1UP)
    "primary_glow": "#6bff83",
    "secondary": "#00eefc",      # Cyber Mana Cyan (Technicals / Links)
    "tertiary": "#ffd700",       # Supercharged Gold Coins (High Scores / S-Rank)
    "error": "#ff2a5f",          # Boss HP / Critical Drawdown Crimson
    "quantum": "#bd00ff",        # 8-bit Neon Violet (Quantum / Volatility)
    "amber_warn": "#f59e0b",     # Phosphor Amber Warning
    "shadow_ink": "#030712",     # Pure Black 4px Flat Shadow Block
}


# ─── MASTER CSS STYLESHEET ────────────────────────────────────────────────────
RETRO_TERMINAL_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,400;0,500;0,700;1,400&family=Space+Grotesk:wght@600;700;800&display=swap');

/* ── 1. GLOBAL CANVAS & SCANLINES ── */
html, body, [data-testid="stAppViewContainer"], .stApp {{
    background-color: {RETRO_COLORS['surface']} !important;
    background-image: repeating-linear-gradient(
        0deg,
        rgba(0, 0, 0, 0.18) 0px,
        rgba(0, 0, 0, 0.18) 1px,
        transparent 1px,
        transparent 2px
    ) !important;
    color: {RETRO_COLORS['on_surface']} !important;
    font-family: 'JetBrains Mono', monospace !important;
}}

/* ── 2. SIDEBAR STYLING ── */
[data-testid="stSidebar"] {{
    background-color: {RETRO_COLORS['surface_container_lowest']} !important;
    border-right: 3px solid {RETRO_COLORS['surface_container']} !important;
    box-shadow: 4px 0px 0px 0px {RETRO_COLORS['shadow_ink']} !important;
}}

[data-testid="stSidebar"] * {{
    font-family: 'JetBrains Mono', monospace !important;
}}

/* ── 3. HEADLINES (SPACE GROTESK UPPERCASE) ── */
h1, h2, h3, h4, h5, h6, [data-testid="stHeader"] {{
    font-family: 'Space Grotesk', sans-serif !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    color: {RETRO_COLORS['on_surface_bright']} !important;
    font-weight: 700 !important;
}}

h1 {{
    font-size: 2.1rem !important;
    text-shadow: 0 0 10px rgba(0, 255, 102, 0.3) !important;
}}

/* ── 4. STRICT ZERO-RADIUS & CHUNKY PIXEL CARDS ── */
* {{
    border-radius: 0px !important;
}}

div[data-testid="metric-container"], .stMetric {{
    background-color: {RETRO_COLORS['surface_container_low']} !important;
    border: 3px solid {RETRO_COLORS['surface_container']} !important;
    border-radius: 0px !important;
    box-shadow: 4px 4px 0px 0px {RETRO_COLORS['shadow_ink']} !important;
    padding: 14px 18px !important;
    transition: transform 0.1s ease, border-color 0.1s ease !important;
}}

div[data-testid="metric-container"]:hover {{
    border-color: {RETRO_COLORS['secondary']} !important;
    box-shadow: 6px 6px 0px 0px {RETRO_COLORS['shadow_ink']} !important;
}}

div[data-testid="metric-container"] [data-testid="stMetricLabel"] {{
    font-family: 'Space Grotesk', sans-serif !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
    color: #94a3b8 !important;
    font-size: 0.75rem !important;
    font-weight: 700 !important;
}}

div[data-testid="metric-container"] [data-testid="stMetricValue"] {{
    font-family: 'JetBrains Mono', monospace !important;
    font-weight: 700 !important;
    font-variant-numeric: tabular-nums !important;
    color: {RETRO_COLORS['primary']} !important;
    font-size: 1.6rem !important;
    text-shadow: 0 0 8px rgba(0, 255, 102, 0.4) !important;
}}

/* ── 5. MECHANICAL HARDWARE ARCADE BUTTONS ── */
button[kind="primary"], .stButton > button {{
    font-family: 'Space Grotesk', sans-serif !important;
    text-transform: uppercase !important;
    font-weight: 700 !important;
    letter-spacing: 0.08em !important;
    border-radius: 0px !important;
    border: 3px solid #ffffff !important;
    background-color: {RETRO_COLORS['primary']} !important;
    color: {RETRO_COLORS['shadow_ink']} !important;
    box-shadow: 4px 4px 0px 0px {RETRO_COLORS['shadow_ink']} !important;
    padding: 10px 22px !important;
    transition: transform 0.05s ease, box-shadow 0.05s ease !important;
}}

button[kind="primary"]:hover, .stButton > button:hover {{
    background-color: {RETRO_COLORS['primary_glow']} !important;
    border-color: #ffffff !important;
    color: {RETRO_COLORS['shadow_ink']} !important;
}}

button[kind="primary"]:active, .stButton > button:active {{
    transform: translate(4px, 4px) !important;
    box-shadow: 0px 0px 0px 0px {RETRO_COLORS['shadow_ink']} !important;
}}

/* ── 6. TERMINAL TABS (SHARP 0px RADIUS) ── */
button[data-baseweb="tab"] {{
    border-radius: 0px !important;
    font-family: 'Space Grotesk', sans-serif !important;
    text-transform: uppercase !important;
    font-weight: 700 !important;
    letter-spacing: 0.06em !important;
    border: 2px solid transparent !important;
    background: transparent !important;
    color: #94a3b8 !important;
}}

button[data-baseweb="tab"][aria-selected="true"] {{
    background-color: {RETRO_COLORS['surface_container_low']} !important;
    border: 2px solid {RETRO_COLORS['secondary']} !important;
    color: {RETRO_COLORS['secondary']} !important;
    box-shadow: 3px 3px 0px 0px {RETRO_COLORS['shadow_ink']} !important;
    text-shadow: 0 0 6px rgba(0, 238, 252, 0.4) !important;
}}

/* ── 7. INPUTS & SELECTBOXES ── */
input, textarea, select, [data-baseweb="select"] {{
    border-radius: 0px !important;
    background-color: {RETRO_COLORS['surface_container_lowest']} !important;
    border: 2px solid {RETRO_COLORS['surface_container_high']} !important;
    color: {RETRO_COLORS['on_surface_bright']} !important;
    font-family: 'JetBrains Mono', monospace !important;
}}

input:focus, textarea:focus {{
    border-color: {RETRO_COLORS['primary']} !important;
    box-shadow: 4px 4px 0px 0px {RETRO_COLORS['shadow_ink']} !important;
}}

/* ── 8. DATAFRAMES & TABLES ── */
[data-testid="stDataFrame"], table {{
    border: 3px solid {RETRO_COLORS['surface_container']} !important;
    box-shadow: 4px 4px 0px 0px {RETRO_COLORS['shadow_ink']} !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-variant-numeric: tabular-nums !important;
}}

/* ── 9. BLINKING TERMINAL CURSOR ── */
@keyframes blinkCursor {{
    0%, 49% {{ opacity: 1; }}
    50%, 100% {{ opacity: 0; }}
}}

.terminal-cursor {{
    display: inline-block;
    width: 9px;
    height: 16px;
    background-color: {RETRO_COLORS['primary']};
    vertical-align: middle;
    margin-left: 6px;
    box-shadow: 0 0 6px {RETRO_COLORS['primary']};
    animation: blinkCursor 1s infinite;
}}

/* ── 10. EXPANDERS & STATUS BOXES ── */
[data-testid="stExpander"] {{
    background-color: {RETRO_COLORS['surface_container_lowest']} !important;
    border: 2px solid {RETRO_COLORS['surface_container_high']} !important;
    border-radius: 0px !important;
    box-shadow: 3px 3px 0px 0px {RETRO_COLORS['shadow_ink']} !important;
}}
</style>
"""


# ─── INJECTION METHOD ─────────────────────────────────────────────────────────

def inject_retro_terminal_theme() -> None:
    """Injects the full Retro Terminal Quant CSS into the Streamlit session."""
    st.markdown(RETRO_TERMINAL_CSS, unsafe_allow_html=True)


# ─── REUSABLE ARCADE QUANT VISUAL HELPERS ──────────────────────────────────────

def render_arcade_badge(text: str, tier: str = "S-RANK") -> str:
    """
    Renders chunky arcade rank badges: [ 1UP ], [ S-RANK ], [ LEVEL 99 ], [ BOSS-HP ].
    """
    tier_upper = tier.upper()
    palette = {
        "1UP": {"border": RETRO_COLORS["primary"], "text": RETRO_COLORS["primary"], "bg": "rgba(0, 255, 102, 0.12)"},
        "S-RANK": {"border": RETRO_COLORS["tertiary"], "text": RETRO_COLORS["tertiary"], "bg": "rgba(255, 215, 0, 0.12)"},
        "BOSS-HP": {"border": RETRO_COLORS["error"], "text": RETRO_COLORS["error"], "bg": "rgba(255, 42, 95, 0.12)"},
        "QUANTUM": {"border": RETRO_COLORS["quantum"], "text": RETRO_COLORS["quantum"], "bg": "rgba(189, 0, 255, 0.12)"},
        "CYBER": {"border": RETRO_COLORS["secondary"], "text": RETRO_COLORS["secondary"], "bg": "rgba(0, 238, 252, 0.12)"},
        "HIGH-SCORE": {"border": RETRO_COLORS["tertiary"], "text": RETRO_COLORS["tertiary"], "bg": "rgba(255, 215, 0, 0.15)"}
    }
    style = palette.get(tier_upper, palette["CYBER"])
    return f"""<span style="font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 0.75rem; border: 2px solid {style['border']}; color: {style['text']}; background: {style['bg']}; padding: 2px 7px; box-shadow: 2px 2px 0px 0px {RETRO_COLORS['shadow_ink']}; text-transform: uppercase; letter-spacing: 0.08em; display: inline-block;">[ {text} ]</span>"""


def render_segmented_meter(value: float, max_value: float = 100.0, total_segments: int = 10, mode: str = "bullish") -> str:
    """
    Renders 8-bit discrete segmented arcade blocks (each segment 8px wide, 14px high, 2px gap).
    Replaces smooth continuous progress bars.
    """
    pct = max(0.0, min(1.0, value / max_value if max_value > 0 else 0.0))
    filled = int(round(pct * total_segments))

    color_map = {
        "bullish": RETRO_COLORS["primary"],
        "bearish": RETRO_COLORS["error"],
        "mana": RETRO_COLORS["secondary"],
        "gold": RETRO_COLORS["tertiary"],
        "quantum": RETRO_COLORS["quantum"]
    }
    fill_color = color_map.get(mode, RETRO_COLORS["primary"])

    blocks = []
    for i in range(total_segments):
        if i < filled:
            blocks.append(f'<div style="width: 8px; height: 14px; background: {fill_color}; margin-right: 2px; box-shadow: 0 0 4px {fill_color}; display: inline-block;"></div>')
        else:
            blocks.append(f'<div style="width: 8px; height: 14px; background: {RETRO_COLORS["surface_container"]}; border: 1px solid {RETRO_COLORS["surface_container_lowest"]}; margin-right: 2px; display: inline-block;"></div>')

    return f"""<div style="display: inline-flex; align-items: center; vertical-align: middle;">{''.join(blocks)} <span style="font-family: 'JetBrains Mono'; font-weight: 700; font-size: 0.85rem; color: {fill_color}; margin-left: 8px; font-variant-numeric: tabular-nums;">{value:.1f}</span></div>"""


def render_arcade_header(title: str, subtitle: str, status_tag: str = "TERMINAL ONLINE") -> str:
    """
    Renders the retro arcade CRT marquee header with scanline and phosphor styling.
    """
    return f"""
    <div style="background-color: {RETRO_COLORS['surface_container_lowest']}; border: 3px solid {RETRO_COLORS['primary']}; box-shadow: 6px 6px 0px 0px {RETRO_COLORS['shadow_ink']}; padding: 20px 24px; margin-bottom: 24px; position: relative;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
            <div>
                <div style="display: flex; align-items: center;">
                    <span style="font-size: 1.8rem; margin-right: 10px;">🕹️</span>
                    <h1 style="color: {RETRO_COLORS['on_surface_bright']}; margin: 0; font-size: 1.9rem; font-weight: 800; letter-spacing: 0.08em; display: inline;">
                        {title}
                    </h1>
                    <span class="terminal-cursor"></span>
                </div>
                <p style="color: #94a3b8; margin: 8px 0 0 0; font-size: 0.9rem; font-family: 'JetBrains Mono', monospace;">
                    > {subtitle}
                </p>
            </div>
            <div style="text-align: right; background: {RETRO_COLORS['surface_container']}; padding: 8px 14px; border: 2px solid {RETRO_COLORS['secondary']}; box-shadow: 3px 3px 0px 0px {RETRO_COLORS['shadow_ink']};">
                <div style="font-size: 0.7rem; color: {RETRO_COLORS['secondary']}; text-transform: uppercase; letter-spacing: 0.12em; font-weight: 700;">SYSTEM TELEMETRY</div>
                <div style="font-size: 1.05rem; color: {RETRO_COLORS['primary']}; font-weight: 800; text-shadow: 0 0 6px {RETRO_COLORS['primary']};">{status_tag}</div>
            </div>
        </div>
    </div>
    """
