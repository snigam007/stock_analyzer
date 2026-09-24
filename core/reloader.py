"""
Centralized Core Module Hot-Reloader for Streamlit Long-Running Dev Sessions.
Ensures that all backend analytical engines and models are dynamically reloaded
from disk into Python's sys.modules cache on page re-runs without requiring
a complete server restart.
"""
import sys
import importlib
import logging

logger = logging.getLogger(__name__)

# Modules ordered by dependency topology (primitives first, higher-order engines last)
CORE_MODULE_NAMES = [
    "core.indicators",
    "core.candlestick_patterns",
    "core.target_velocity",
    "core.cpr_vsa_scanner",
    "core.sector_clusters",
    "core.market_breadth",
    "core.bellwether_lead_lag",
    "core.macro_regime",
    "core.accuracy_tracker",
    "core.multi_timeframe",
    "core.tranche_execution",
    "core.earnings_catalysts",
    "core.missed_signals",
    "core.signals",
    "core.smart_order_router",
    "core.portfolio_analyzer",
    "core.portfolio_optimizer",
    "core.monthly_sip_advisor",
    "core.sip_audit_backtester",
    "core.sip_tracker",
    "core.recommendation_tracker",
    "core.broker_gateway",
    "core.broker_sync",
    "core.mf_fetcher",
    "core.mf_signals",
    "core.trading_journal",
    "core.institutional_flows",
    "core.economic_calendar",
]


def reload_all_core_modules():
    """
    Dynamically reloads all core analytical modules if they are already present in sys.modules.
    Prevents stale in-memory cached definitions during long-running Streamlit sessions.
    """
    reloaded_count = 0
    for mod_name in CORE_MODULE_NAMES:
        if mod_name in sys.modules:
            try:
                mod = sys.modules[mod_name]
                if mod is not None:
                    importlib.reload(mod)
                    reloaded_count += 1
            except Exception as e:
                logger.debug(f"Failed to reload {mod_name}: {e}")
    return reloaded_count
