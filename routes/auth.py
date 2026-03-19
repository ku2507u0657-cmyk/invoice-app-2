"""
routes/auth.py — Authentication routes: login, logout.
"""

from flask import (
    Blueprint, render_template, redirect,
    url_for, request, flash, current_app,
)
from flask_login import login_user, logout_user, login_required, current_user
from models import Admin

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ── Login ─────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Render and process the admin login form."""

    # Already authenticated → go straight to dashboard
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        # ── Validate ──────────────────────────────────────
        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template("auth/login.html",
                                   app_name=current_app.config.get("APP_NAME"))

        admin = Admin.query.filter_by(username=username).first()

        if admin is None or not admin.check_password(password):
            # Intentionally vague — don't reveal which field was wrong
            flash("Invalid username or password.", "danger")
            return render_template("auth/login.html",
                                   app_name=current_app.config.get("APP_NAME"))

        # ── Success ───────────────────────────────────────
        login_user(admin, remember=remember)
        flash(f"Welcome back, {admin.username}!", "success")

        # Safe redirect: honour ?next= but only for internal paths
        next_page = request.args.get("next")
        if next_page and next_page.startswith("/"):
            return redirect(next_page)
        return redirect(url_for("main.dashboard"))

    return render_template(
        "auth/login.html",
        app_name=current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


# ── Logout ────────────────────────────────────────────────────

@auth_bp.route("/logout")
@login_required
def logout():
    """Log out the current admin and redirect to login."""
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
