"""
routes/clients.py — Client management: list, add, edit, delete.
All routes require an authenticated admin session.
"""

from flask import (
    Blueprint, render_template, redirect, url_for,
    request, flash, current_app,
)
from flask_login import login_required
from extensions import db
from models import Client

clients_bp = Blueprint("clients", __name__, url_prefix="/clients")


# ── Helpers ───────────────────────────────────────────────────

def _form_to_client(client):
    """
    Read POST form fields, validate, and populate client in-place.
    Returns (is_valid: bool, error_message: str).
    """
    name        = request.form.get("name", "").strip()
    phone       = request.form.get("phone", "").strip()
    email       = request.form.get("email", "").strip()
    monthly_fee = request.form.get("monthly_fee", "").strip()
    gst_number  = request.form.get("gst_number", "").strip()

    if not name:
        return False, "Client name is required."

    fee_value = None
    if monthly_fee:
        try:
            fee_value = float(monthly_fee)
            if fee_value < 0:
                return False, "Monthly fee cannot be negative."
        except ValueError:
            return False, "Monthly fee must be a valid number."

    client.name        = name
    client.phone       = phone or None
    client.email       = email or None
    client.monthly_fee = fee_value
    client.gst_number  = gst_number or None

    return True, ""


# ── List ──────────────────────────────────────────────────────

@clients_bp.route("/")
@login_required
def list_clients():
    """Paginated, searchable client list."""
    search = request.args.get("q", "").strip()
    page   = request.args.get("page", 1, type=int)

    query = Client.query.order_by(Client.name.asc())

    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(
                Client.name.ilike(like),
                Client.email.ilike(like),
                Client.phone.ilike(like),
                Client.gst_number.ilike(like),
            )
        )

    pagination = query.paginate(page=page, per_page=15, error_out=False)

    return render_template(
        "clients/list.html",
        clients    = pagination.items,
        pagination = pagination,
        search     = search,
        app_name   = current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


# ── Add ───────────────────────────────────────────────────────

@clients_bp.route("/add", methods=["GET", "POST"])
@login_required
def add_client():
    """Render and process the new-client form."""
    if request.method == "POST":
        client = Client()
        ok, err = _form_to_client(client)

        if not ok:
            flash(err, "danger")
            return render_template(
                "clients/form.html",
                mode     = "add",
                client   = client,
                app_name = current_app.config.get("APP_NAME"),
            )

        db.session.add(client)
        db.session.commit()
        flash(f"Client '{client.name}' added successfully.", "success")
        return redirect(url_for("clients.list_clients"))

    return render_template(
        "clients/form.html",
        mode     = "add",
        client   = Client(),
        app_name = current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


# ── Edit ──────────────────────────────────────────────────────

@clients_bp.route("/<int:client_id>/edit", methods=["GET", "POST"])
@login_required
def edit_client(client_id):
    """Render and process the edit-client form."""
    client = db.get_or_404(Client, client_id)

    if request.method == "POST":
        ok, err = _form_to_client(client)

        if not ok:
            flash(err, "danger")
            return render_template(
                "clients/form.html",
                mode     = "edit",
                client   = client,
                app_name = current_app.config.get("APP_NAME"),
            )

        db.session.commit()
        flash(f"Client '{client.name}' updated.", "success")
        return redirect(url_for("clients.list_clients"))

    return render_template(
        "clients/form.html",
        mode     = "edit",
        client   = client,
        app_name = current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


# ── Delete ────────────────────────────────────────────────────

@clients_bp.route("/<int:client_id>/delete", methods=["POST"])
@login_required
def delete_client(client_id):
    """
    Delete a client record. POST-only to prevent accidental deletions
    from stray GET requests or link prefetching.
    """
    client = db.get_or_404(Client, client_id)
    name   = client.name

    db.session.delete(client)
    db.session.commit()
    flash(f"Client '{name}' has been deleted.", "warning")
    return redirect(url_for("clients.list_clients"))
