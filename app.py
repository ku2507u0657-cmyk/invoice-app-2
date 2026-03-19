"""
app.py — InvoiceFlow Flask Application
"""

from flask import Flask
from config import get_config
from extensions import db, migrate, login_manager


def create_app(config_class=None):
    app = Flask(__name__)
    app.config.from_object(config_class or get_config())

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # ── Blueprints ─────────────────────────────────────────
    from routes.main     import main_bp
    from routes.auth     import auth_bp
    from routes.clients  import clients_bp
    from routes.invoices import invoices_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(invoices_bp)

    # ── User loader ────────────────────────────────────────
    from models import Admin

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Admin, int(user_id))

    # ── Init DB ────────────────────────────────────────────
    with app.app_context():
        db.create_all()
        _seed_admin(app)

    # ── Start scheduler ────────────────────────────────────
    # Imported here to avoid circular imports at module level.
    # The scheduler pushes its own app context per job run.
    from scheduler import init_scheduler
    init_scheduler(app)

    # ── Shell context ──────────────────────────────────────
    @app.shell_context_processor
    def make_shell_context():
        from models import Admin, Client, Invoice
        return {"db": db, "Admin": Admin, "Client": Client, "Invoice": Invoice}

    return app


def _seed_admin(app):
    import os
    from models import Admin

    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "changeme123")

    if not Admin.query.filter_by(username=username).first():
        admin = Admin(username=username)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        app.logger.info(f"Seeded default admin: '{username}'")


app = create_app()

if __name__ == "__main__":
    app.run(debug=app.config.get("DEBUG", False), port=5000)
