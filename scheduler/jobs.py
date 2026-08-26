"""
APScheduler Daily Refresh Jobs
Runs automatically at 6:30 PM IST to update data after market close.
Also provides a manual trigger function.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import DAILY_UPDATE_HOUR, DAILY_UPDATE_MINUTE, TIMEZONE

logger = logging.getLogger(__name__)


def run_daily_update():
    """Full daily update pipeline."""
    from db.database import get_global_engine, get_session
    from core.data_fetcher import daily_update
    from core.indicators import compute_all_indicators
    from core.scoring import compute_and_save_scores
    from core.signals import generate_all_signals
    from core.sector_analysis import compute_and_save_sector_analysis
    from core.strategies import save_all_strategies

    logger.info(f"⏰ Daily update started at {datetime.now()}")
    engine = get_global_engine()
    session = get_session(engine)

    try:
        daily_update(session)
        compute_all_indicators(session)
        compute_and_save_scores(session)
        generate_all_signals(session)
        compute_and_save_sector_analysis(session)
        save_all_strategies(session)
        logger.info("✅ Daily update complete")
    except Exception as e:
        logger.error(f"Daily update failed: {e}")
    finally:
        session.close()


def start_scheduler():
    """Start the background scheduler."""
    ist = pytz.timezone(TIMEZONE)
    scheduler = BackgroundScheduler(timezone=ist)

    scheduler.add_job(
        run_daily_update,
        trigger=CronTrigger(
            hour=DAILY_UPDATE_HOUR,
            minute=DAILY_UPDATE_MINUTE,
            timezone=ist
        ),
        id="daily_update",
        name="Daily Market Data Update",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()
    logger.info(f"📅 Scheduler started: daily update at {DAILY_UPDATE_HOUR}:{DAILY_UPDATE_MINUTE:02d} IST")
    return scheduler


if __name__ == "__main__":
    import time
    scheduler = start_scheduler()
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
