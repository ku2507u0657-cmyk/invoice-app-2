"""
scheduler.py — APScheduler configuration and job registration for InvoiceFlow.

Architecture
------------
We use BackgroundScheduler with a SQLAlchemyJobStore so job state survives
restarts.  The scheduler is initialised once inside create_app() and stored on
the Flask app instance so it can be shut down cleanly on teardown.

Gunicorn note
-------------
When running with multiple worker *processes* each worker starts its own
scheduler.  To prevent N copies of every job firing simultaneously, either:
  a) use a single-worker Gunicorn setup  (--workers 1)           [simplest]
  b) pin the scheduler to a dedicated process / thread            [production]
  c) use a Redis/Postgres job-store + a process lock             [scale-out]
For single-server deployments option (a) is perfectly adequate.
"""

import logging

from apscheduler.schedulers.background  import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy   import SQLAlchemyJobStore
from apscheduler.executors.pool         import ThreadPoolExecutor
from apscheduler.triggers.cron          import CronTrigger

logger = logging.getLogger(__name__)


def init_scheduler(app):
    """
    Create, configure and start the APScheduler BackgroundScheduler.

    Attaches the scheduler to ``app.scheduler`` so it is accessible
    throughout the application and can be stopped on shutdown.

    Parameters
    ----------
    app : Flask application instance (config must already be loaded)
    """
    if not app.config.get("SCHEDULER_ENABLED", False):
        logger.info("Scheduler is disabled (SCHEDULER_ENABLED=False). Skipping.")
        return

    cfg = app.config
    db_url   = cfg.get("SQLALCHEMY_DATABASE_URI", "sqlite:///invoice_app.db")
    timezone = cfg.get("SCHEDULER_TIMEZONE", "UTC")
    hour     = cfg.get("REMINDER_HOUR",   9)
    minute   = cfg.get("REMINDER_MINUTE", 0)

    # ── Job store: persist job definitions in the same DB ─────────────────
    jobstores = {
        "default": SQLAlchemyJobStore(url=db_url, tablename="apscheduler_jobs"),
    }

    # ── Executor: a thread pool (keeps the DB session per-thread) ─────────
    executors = {
        "default": ThreadPoolExecutor(max_workers=2),
    }

    job_defaults = {
        "coalesce":    True,   # merge missed fires into one run
        "max_instances": 1,    # never run the same job concurrently
        "misfire_grace_time": 3600,  # allow up to 1 h late fire
    }

    scheduler = BackgroundScheduler(
        jobstores    = jobstores,
        executors    = executors,
        job_defaults = job_defaults,
        timezone     = timezone,
    )

    # ── Register jobs ──────────────────────────────────────────────────────
    _register_daily_reminder(scheduler, app, hour, minute, timezone)

    scheduler.start()
    app.scheduler = scheduler

    logger.info(
        "Scheduler started. Daily reminder job: %02d:%02d %s",
        hour, minute, timezone,
    )

    # ── Graceful shutdown hook ─────────────────────────────────────────────
    import atexit
    atexit.register(_shutdown_scheduler, scheduler)

    return scheduler


def _register_daily_reminder(scheduler, app, hour, minute, timezone):
    """
    Add (or replace) the daily overdue-reminder job.

    Using ``replace_existing=True`` means re-starting the app won't
    accumulate duplicate job entries in the job store.
    """
    from utils.reminder import run_overdue_reminder_job

    scheduler.add_job(
        func             = run_overdue_reminder_job,
        trigger          = CronTrigger(hour=hour, minute=minute, timezone=timezone),
        id               = "daily_overdue_reminder",
        name             = "Daily Overdue Invoice Reminder",
        args             = [app],
        replace_existing = True,
    )
    logger.info(
        "Registered job 'daily_overdue_reminder' at %02d:%02d %s",
        hour, minute, timezone,
    )


def _shutdown_scheduler(scheduler):
    """Cleanly stop the scheduler on process exit."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down.")
