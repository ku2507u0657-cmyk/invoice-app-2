"""
routes/invoices.py — Invoice management: list, create, mark-as-paid.
All routes protected by @login_required.
"""

from datetime import date, timedelta
from flask import (
    Blueprint, render_template, redirect, url_for,
    request, flash, current_app, jsonify,
)
from flask_login import login_required
from extensions import db
from models import Invoice, InvoiceStatus, Client

invoices_bp = Blueprint("invoices", __name__, url_prefix="/invoices")


# ── List ──────────────────────────────────────────────────────

@invoices_bp.route("/")
@login_required
def list_invoices():
    """Filterable, paginated invoice list."""
    status_filter = request.args.get("status", "").strip()
    search        = request.args.get("q", "").strip()
    page          = request.args.get("page", 1, type=int)

    query = (
        Invoice.query
        .join(Client)
        .order_by(Invoice.created_at.desc())
    )

    if status_filter and status_filter in InvoiceStatus.ALL:
        query = query.filter(Invoice.status == status_filter)

    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(
                Invoice.invoice_number.ilike(like),
                Client.name.ilike(like),
            )
        )

    pagination = query.paginate(page=page, per_page=15, error_out=False)

    # Summary counts for the filter tabs
    counts = {
        "all":    Invoice.query.count(),
        "unpaid": Invoice.query.filter_by(status=InvoiceStatus.UNPAID).count(),
        "paid":   Invoice.query.filter_by(status=InvoiceStatus.PAID).count(),
        "overdue": sum(
            1 for inv in Invoice.query.filter_by(status=InvoiceStatus.UNPAID).all()
            if inv.is_overdue
        ),
    }

    return render_template(
        "invoices/list.html",
        invoices      = pagination.items,
        pagination    = pagination,
        status_filter = status_filter,
        search        = search,
        counts        = counts,
        app_name      = current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


# ── Create ────────────────────────────────────────────────────

@invoices_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_invoice():
    """Render and process the new-invoice form."""
    clients = Client.query.order_by(Client.name.asc()).all()

    if request.method == "POST":
        client_id  = request.form.get("client_id", "").strip()
        amount_raw = request.form.get("amount", "").strip()
        due_date_s = request.form.get("due_date", "").strip()

        # ── Validate ──────────────────────────────────────
        errors = []

        if not client_id:
            errors.append("Please select a client.")
        else:
            client = db.session.get(Client, int(client_id))
            if client is None:
                errors.append("Selected client does not exist.")

        if not amount_raw:
            errors.append("Amount is required.")
        else:
            try:
                amount = float(amount_raw)
                if amount <= 0:
                    errors.append("Amount must be greater than zero.")
            except ValueError:
                errors.append("Amount must be a valid number.")

        if not due_date_s:
            errors.append("Due date is required.")
        else:
            try:
                due_date = date.fromisoformat(due_date_s)
            except ValueError:
                errors.append("Due date format is invalid.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "invoices/create.html",
                clients  = clients,
                form     = request.form,
                app_name = current_app.config.get("APP_NAME"),
            )

        # ── Calculate GST & create record ─────────────────
        gst_amount, total = Invoice.calculate_gst(amount)

        invoice = Invoice(
            invoice_number = Invoice.next_invoice_number(),
            client_id      = int(client_id),
            amount         = amount,
            gst            = gst_amount,
            total          = total,
            due_date       = due_date,
            status         = InvoiceStatus.UNPAID,
        )
        db.session.add(invoice)
        db.session.commit()

        flash(
            f"Invoice {invoice.invoice_number} created for {invoice.client.name}.",
            "success",
        )
        return redirect(url_for("invoices.list_invoices"))

    # Default due date: 30 days from today
    default_due = (date.today() + timedelta(days=30)).isoformat()

    return render_template(
        "invoices/create.html",
        clients      = clients,
        form         = {},
        default_due  = default_due,
        app_name     = current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


# ── Mark as paid ──────────────────────────────────────────────

@invoices_bp.route("/<int:invoice_id>/mark-paid", methods=["POST"])
@login_required
def mark_paid(invoice_id):
    """Mark an invoice as paid and redirect back to the list."""
    invoice = db.get_or_404(Invoice, invoice_id)

    if invoice.status == InvoiceStatus.PAID:
        flash(f"{invoice.invoice_number} is already marked as paid.", "warning")
    else:
        invoice.mark_paid()
        db.session.commit()
        flash(
            f"{invoice.invoice_number} marked as paid.",
            "success",
        )

    # Honour ?next= so the action works from both the list and dashboard
    next_page = request.args.get("next") or url_for("invoices.list_invoices")
    return redirect(next_page)


# ── GST preview (AJAX) ────────────────────────────────────────

@invoices_bp.route("/gst-preview")
@login_required
def gst_preview():
    """
    Returns JSON {gst, total} for a given amount.
    Called by the create-invoice form's live preview JS.
    """
    try:
        amount = float(request.args.get("amount", 0))
        if amount < 0:
            raise ValueError
    except ValueError:
        return jsonify({"error": "invalid amount"}), 400

    gst, total = Invoice.calculate_gst(amount)
    return jsonify({
        "gst":   f"{float(gst):,.2f}",
        "total": f"{float(total):,.2f}",
    })
