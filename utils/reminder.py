"""
utils/reminder.py — Daily overdue-invoice reminder job.

This module is executed by APScheduler in a background thread.
It must therefore push its own Flask application context before
touching SQLAlchemy models or app.config.

Job flow
--------
1.  Push an app context so SQLAlchemy and Jinja are available.
2.  Query all unpaid invoices whose due_date < today.
3.  For each, attempt to send a reminder email (with PDF attached).
4.  Log a structured summary: sent / skipped / failed counts.
"""

import logging
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
#  Entry point called by APScheduler
# ─────────────────────────────────────────────────────────────────────────

def run_overdue_reminder_job(app):
    """
    APScheduler entry point.

    Parameters
    ----------
    app : Flask application instance
          (passed as a positional arg from scheduler.add_job)
    """
    with app.app_context():
        _execute(app)


# ─────────────────────────────────────────────────────────────────────────
#  Core logic (runs inside an app context)
# ─────────────────────────────────────────────────────────────────────────

def _execute(app):
    from extensions import db
    from models     import Invoice, InvoiceStatus
    from utils.email import send_reminder_email, EmailError

    cfg        = app.config
    today      = date.today()
    grace_days = cfg.get("REMINDER_GRACE_DAYS", 0)

    logger.info(
        "[Reminder job] Starting at %s. Grace days: %d.",
        datetime.now(timezone.utc).isoformat(), grace_days,
    )

    # ── Find all overdue unpaid invoices ───────────────────────────────────
    overdue = (
        Invoice.query
        .filter(
            Invoice.status   == InvoiceStatus.UNPAID,
            Invoice.due_date <  today,
        )
        .order_by(Invoice.due_date.asc())
        .all()
    )

    if not overdue:
        logger.info("[Reminder job] No overdue invoices found. Done.")
        return

    logger.info("[Reminder job] Found %d overdue invoice(s).", len(overdue))

    sent    = 0
    skipped = 0
    failed  = 0

    for invoice in overdue:
        days_overdue = (today - invoice.due_date).days

        # Respect grace period: skip invoices that aren't yet past it
        if days_overdue < grace_days:
            logger.debug(
                "[Reminder job] Skipping %s (%d day(s) overdue, grace=%d).",
                invoice.invoice_number, days_overdue, grace_days,
            )
            skipped += 1
            continue

        # Skip if client has no email and no fallback is configured
        recipient = (
            invoice.client.email
            or cfg.get("MAIL_FALLBACK_RECIPIENT")
        )
        if not recipient:
            logger.warning(
                "[Reminder job] Skipping %s: client '%s' has no email address.",
                invoice.invoice_number, invoice.client.name,
            )
            skipped += 1
            continue

        # ── Attempt to send ────────────────────────────────────────────────
        try:
            send_reminder_email(invoice, app, days_overdue=days_overdue)
            logger.info(
                "[Reminder job] Sent reminder for %s to %s (%d day(s) overdue).",
                invoice.invoice_number, recipient, days_overdue,
            )
            sent += 1

        except EmailError as exc:
            logger.error(
                "[Reminder job] Failed to send reminder for %s: %s",
                invoice.invoice_number, exc,
            )
            failed += 1

        except Exception as exc:
            logger.exception(
                "[Reminder job] Unexpected error for %s: %s",
                invoice.invoice_number, exc,
            )
            failed += 1

    # ── Summary log ───────────────────────────────────────────────────────
    logger.info(
        "[Reminder job] Complete. sent=%d  skipped=%d  failed=%d",
        sent, skipped, failed,
    )
