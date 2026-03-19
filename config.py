"""
config.py — Environment-based configuration for InvoiceFlow
"""

import os
from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    # ── Flask ──────────────────────────────────────────────
    SECRET_KEY   = os.environ.get("SECRET_KEY", "dev-fallback-secret-key-change-me")
    APP_NAME     = os.environ.get("APP_NAME", "InvoiceFlow")
    COMPANY_NAME = os.environ.get("COMPANY_NAME", "Your Company")

    # ── SQLAlchemy ─────────────────────────────────────────
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///invoice_app.db"
    )

    # ── SMTP / Email ───────────────────────────────────────
    # Toggle: set MAIL_ENABLED=False to skip all sending (useful in dev/test)
    MAIL_ENABLED      = os.environ.get("MAIL_ENABLED", "True").lower() == "true"

    MAIL_SERVER       = os.environ.get("MAIL_SERVER",   "smtp.gmail.com")
    MAIL_PORT         = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS      = os.environ.get("MAIL_USE_TLS",  "True").lower() == "true"

    # SMTP login credentials
    MAIL_USERNAME     = os.environ.get("MAIL_USERNAME")   # e.g. you@gmail.com
    MAIL_PASSWORD     = os.environ.get("MAIL_PASSWORD")   # App password (not account password)

    # The "From:" display name and address in sent emails
    MAIL_FROM_NAME    = os.environ.get("MAIL_FROM_NAME",    APP_NAME)
    MAIL_FROM_ADDRESS = os.environ.get("MAIL_FROM_ADDRESS", MAIL_USERNAME or "noreply@invoiceflow.app")

    # Fallback: if client has no email, send to this address instead (optional)
    MAIL_FALLBACK_RECIPIENT = os.environ.get("MAIL_FALLBACK_RECIPIENT")


class DevelopmentConfig(BaseConfig):
    DEBUG   = True
    TESTING = False
    # In development, default to disabled so stray emails aren't sent
    MAIL_ENABLED = os.environ.get("MAIL_ENABLED", "False").lower() == "true"


class TestingConfig(BaseConfig):
    DEBUG    = True
    TESTING  = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED        = False
    MAIL_ENABLED            = False   # always off in tests


class ProductionConfig(BaseConfig):
    DEBUG   = False
    TESTING = False
    # Production requires MAIL_ENABLED=True in .env to activate sending


config_map = {
    "development": DevelopmentConfig,
    "testing":     TestingConfig,
    "production":  ProductionConfig,
}


def get_config():
    env = os.environ.get("FLASK_ENV", "development").lower()
    return config_map.get(env, DevelopmentConfig)
