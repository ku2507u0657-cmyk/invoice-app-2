"""
utils/email.py — Email delivery via smtplib for InvoiceFlow.

Public API
----------
    send_invoice_email(invoice, app)  -> None
        Send the original invoice on creation (with PDF attached).

    send_reminder_email(invoice, app, days_overdue) -> None
        Send an overdue payment reminder (with PDF attached).

Both functions raise EmailError on failure so callers can decide whether
to surface the error or log-and-continue.
"""

import logging
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart   import MIMEMultipart
from email.mime.text        import MIMEText

from utils.pdf import build_invoice_pdf

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """Raised when an email cannot be delivered."""


# ─────────────────────────────────────────────────────────────────────────
#  Public: send original invoice email
# ─────────────────────────────────────────────────────────────────────────

def send_invoice_email(invoice, app) -> None:
    """
    Build an invoice PDF and deliver a rich HTML email to the client.

    Parameters
    ----------
    invoice : Invoice ORM instance (client relationship must be loaded)
    app     : Flask application instance

    Raises
    ------
    EmailError on any delivery failure
    """
    cfg          = app.config
    company_name = cfg.get("COMPANY_NAME", cfg.get("APP_NAME", "InvoiceFlow"))

    _guard_enabled(cfg)
    recipient = _resolve_recipient(invoice, cfg)
    pdf_bytes = _build_pdf(invoice, company_name)

    subject = f"Invoice {invoice.invoice_number} from {company_name}"

    html_body = _render_template(app, "emails/invoice_email.html",
                                 invoice=invoice, company_name=company_name)
    plain_body = _plain_invoice_body(invoice, company_name)

    msg = _assemble_message(
        subject      = subject,
        from_name    = cfg.get("MAIL_FROM_NAME",    company_name),
        from_address = cfg.get("MAIL_FROM_ADDRESS", cfg.get("MAIL_USERNAME", "")),
        recipient    = recipient,
        plain_body   = plain_body,
        html_body    = html_body,
        pdf_bytes    = pdf_bytes,
        pdf_filename = f"{invoice.invoice_number}.pdf",
    )

    _smtp_send(msg, recipient, cfg)
    logger.info("Invoice email sent: %s -> %s", invoice.invoice_number, recipient)


# ─────────────────────────────────────────────────────────────────────────
#  Public: send overdue reminder email
# ─────────────────────────────────────────────────────────────────────────

def send_reminder_email(invoice, app, days_overdue: int = 0) -> None:
    """
    Send an overdue payment reminder with the invoice PDF re-attached.

    Parameters
    ----------
    invoice      : Invoice ORM instance
    app          : Flask application instance
    days_overdue : How many calendar days past the due date (for email copy)

    Raises
    ------
    EmailError on any delivery failure
    """
    cfg          = app.config
    company_name = cfg.get("COMPANY_NAME", cfg.get("APP_NAME", "InvoiceFlow"))

    _guard_enabled(cfg)
    recipient = _resolve_recipient(invoice, cfg)
    pdf_bytes = _build_pdf(invoice, company_name)

    subject = (
        f"Payment Reminder: {invoice.invoice_number} is "
        f"{days_overdue} day{'s' if days_overdue != 1 else ''} overdue"
    )

    html_body = _render_template(
        app, "emails/reminder_email.html",
        invoice      = invoice,
        company_name = company_name,
        days_overdue = days_overdue,
    )
    plain_body = _plain_reminder_body(invoice, company_name, days_overdue)

    msg = _assemble_message(
        subject      = subject,
        from_name    = cfg.get("MAIL_FROM_NAME",    company_name),
        from_address = cfg.get("MAIL_FROM_ADDRESS", cfg.get("MAIL_USERNAME", "")),
        recipient    = recipient,
        plain_body   = plain_body,
        html_body    = html_body,
        pdf_bytes    = pdf_bytes,
        pdf_filename = f"{invoice.invoice_number}.pdf",
    )

    _smtp_send(msg, recipient, cfg)
    logger.info(
        "Reminder email sent: %s -> %s (%d days overdue)",
        invoice.invoice_number, recipient, days_overdue,
    )


# ─────────────────────────────────────────────────────────────────────────
#  Shared private helpers
# ─────────────────────────────────────────────────────────────────────────

def _guard_enabled(cfg):
    """Raise EmailError immediately if mail sending is disabled."""
    if not cfg.get("MAIL_ENABLED", False):
        raise EmailError("Email sending is disabled (MAIL_ENABLED=False).")


def _resolve_recipient(invoice, cfg):
    """Return the best available recipient address or raise EmailError."""
    recipient = invoice.client.email or cfg.get("MAIL_FALLBACK_RECIPIENT")
    if not recipient:
        raise EmailError(
            f"No recipient for {invoice.invoice_number}: client has no email "
            "and MAIL_FALLBACK_RECIPIENT is not set."
        )
    return recipient


def _build_pdf(invoice, company_name):
    """Generate the PDF bytes or raise EmailError."""
    try:
        return build_invoice_pdf(invoice, company_name=company_name)
    except Exception as exc:
        raise EmailError(f"PDF generation failed: {exc}") from exc


def _render_template(app, template_path, **context):
    """Render a Jinja template to a string inside an app context."""
    with app.app_context():
        return app.jinja_env.get_template(template_path).render(**context)


def _assemble_message(subject, from_name, from_address, recipient,
                      plain_body, html_body, pdf_bytes, pdf_filename):
    """
    Build a MIMEMultipart/mixed message:
        mixed
          alternative
            text/plain
            text/html
          application/pdf  (attachment)
    """
    root = MIMEMultipart("mixed")
    root["Subject"] = subject
    root["From"]    = f"{from_name} <{from_address}>"
    root["To"]      = recipient

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body,  "html",  "utf-8"))
    root.attach(alt)

    pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
    pdf_part.add_header("Content-Disposition", "attachment", filename=pdf_filename)
    root.attach(pdf_part)

    return root


def _smtp_send(msg, recipient, cfg):
    """Open an SMTP connection and send *msg*."""
    username = cfg.get("MAIL_USERNAME")
    password = cfg.get("MAIL_PASSWORD")
    if not username or not password:
        raise EmailError("MAIL_USERNAME and MAIL_PASSWORD must both be set.")

    server  = cfg.get("MAIL_SERVER",  "smtp.gmail.com")
    port    = cfg.get("MAIL_PORT",    587)
    use_tls = cfg.get("MAIL_USE_TLS", True)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(server, port, timeout=15) as smtp:
            smtp.ehlo()
            if use_tls:
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(username, password)
            smtp.sendmail(
                from_addr = cfg.get("MAIL_FROM_ADDRESS", username),
                to_addrs  = [recipient],
                msg       = msg.as_string(),
            )
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailError(
            "SMTP authentication failed. Check MAIL_USERNAME and MAIL_PASSWORD."
        ) from exc
    except smtplib.SMTPException as exc:
        raise EmailError(f"SMTP error: {exc}") from exc
    except OSError as exc:
        raise EmailError(f"Cannot connect to {server}:{port} — {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────
#  Plain-text fallback bodies
# ─────────────────────────────────────────────────────────────────────────

def _plain_invoice_body(invoice, company_name):
    return (
        f"Dear {invoice.client.name},\n\n"
        f"Please find attached invoice {invoice.invoice_number} from {company_name}.\n\n"
        f"  Amount (excl. GST):  {invoice.amount_display}\n"
        f"  GST (18%):           {invoice.gst_display}\n"
        f"  Total Payable:       {invoice.total_display}\n"
        f"  Due Date:            {invoice.due_date.strftime('%d %B %Y')}\n\n"
        f"Please reference {invoice.invoice_number} when making payment.\n\n"
        f"Thank you,\n{company_name}"
    )


def _plain_reminder_body(invoice, company_name, days_overdue):
    day_str = f"{days_overdue} day{'s' if days_overdue != 1 else ''}"
    return (
        f"Dear {invoice.client.name},\n\n"
        f"This is a reminder that invoice {invoice.invoice_number} from "
        f"{company_name} is now {day_str} overdue.\n\n"
        f"  Invoice Number:  {invoice.invoice_number}\n"
        f"  Original Due:    {invoice.due_date.strftime('%d %B %Y')}\n"
        f"  Days Overdue:    {day_str}\n"
        f"  Total Payable:   {invoice.total_display}\n\n"
        f"Please arrange payment at your earliest convenience and quote "
        f"{invoice.invoice_number} as your reference.\n\n"
        f"The invoice PDF is re-attached for your convenience.\n\n"
        f"If you believe this has been sent in error, please reply to this email.\n\n"
        f"Regards,\n{company_name}"
    )
