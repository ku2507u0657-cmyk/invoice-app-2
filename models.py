"""
models.py — SQLAlchemy models for InvoiceFlow
"""

from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


# ─────────────────────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────────────────────

GST_RATE = Decimal("0.18")   # 18 %


# ─────────────────────────────────────────────────────────────
#  Mixin: shared timestamp columns
# ─────────────────────────────────────────────────────────────

class TimestampMixin:
    created_at = db.Column(
        db.DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# ─────────────────────────────────────────────────────────────
#  Admin
# ─────────────────────────────────────────────────────────────

class Admin(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "admins"

    id            = db.Column(db.Integer,     primary_key=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, plaintext):
        self.password_hash = generate_password_hash(plaintext)

    def check_password(self, plaintext):
        return check_password_hash(self.password_hash, plaintext)

    def __repr__(self):
        return f"<Admin id={self.id} username={self.username!r}>"


# ─────────────────────────────────────────────────────────────
#  User  (future multi-tenant support)
# ─────────────────────────────────────────────────────────────

class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id        = db.Column(db.Integer,   primary_key=True)
    email     = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name      = db.Column(db.String(120), nullable=False)
    company   = db.Column(db.String(200), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<User id={self.id} email={self.email!r}>"


# ─────────────────────────────────────────────────────────────
#  Client
# ─────────────────────────────────────────────────────────────

class Client(db.Model):
    __tablename__ = "clients"

    id          = db.Column(db.Integer,      primary_key=True)
    name        = db.Column(db.String(200),  nullable=False, index=True)
    phone       = db.Column(db.String(50),   nullable=True)
    email       = db.Column(db.String(255),  nullable=True, index=True)
    monthly_fee = db.Column(db.Numeric(10, 2), nullable=True, default=0.00)
    gst_number  = db.Column(db.String(30),   nullable=True)
    created_at  = db.Column(
        db.DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # back-reference populated by Invoice.client relationship
    invoices = db.relationship("Invoice", back_populates="client",
                               lazy="dynamic", cascade="all, delete-orphan")

    @property
    def monthly_fee_display(self):
        if self.monthly_fee is None:
            return "—"
        return f"${float(self.monthly_fee):,.2f}"

    @property
    def initials(self):
        parts = self.name.strip().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return self.name[:2].upper()

    def __repr__(self):
        return f"<Client id={self.id} name={self.name!r}>"

    def to_dict(self):
        return {
            "id":          self.id,
            "name":        self.name,
            "phone":       self.phone,
            "email":       self.email,
            "monthly_fee": float(self.monthly_fee) if self.monthly_fee else 0.0,
            "gst_number":  self.gst_number,
            "created_at":  self.created_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────
#  Invoice
# ─────────────────────────────────────────────────────────────

class InvoiceStatus:
    UNPAID  = "unpaid"
    PAID    = "paid"
    OVERDUE = "overdue"
    ALL     = [UNPAID, PAID, OVERDUE]


class Invoice(db.Model):
    """
    A billable invoice sent to a Client.

    Fields
    ------
    id             – primary key
    invoice_number – human-readable unique reference  (e.g. INV-0042)
    client_id      – FK → clients.id
    amount         – base amount before GST  (Numeric 10,2)
    gst            – GST portion at 18 %     (Numeric 10,2)
    total          – amount + gst            (Numeric 10,2)
    due_date       – payment due date
    status         – 'unpaid' | 'paid' | 'overdue'
    created_at     – UTC insert timestamp
    paid_at        – UTC timestamp when marked paid (nullable)
    """

    __tablename__ = "invoices"

    id             = db.Column(db.Integer,      primary_key=True)
    invoice_number = db.Column(db.String(20),   unique=True, nullable=False, index=True)
    client_id      = db.Column(db.Integer,      db.ForeignKey("clients.id"), nullable=False, index=True)
    amount         = db.Column(db.Numeric(10, 2), nullable=False)
    gst            = db.Column(db.Numeric(10, 2), nullable=False)
    total          = db.Column(db.Numeric(10, 2), nullable=False)
    due_date       = db.Column(db.Date,          nullable=False)
    status         = db.Column(db.String(10),    nullable=False, default=InvoiceStatus.UNPAID, index=True)
    created_at     = db.Column(db.DateTime,      nullable=False,
                                default=lambda: datetime.now(timezone.utc))
    paid_at        = db.Column(db.DateTime,      nullable=True)

    # ── Relationship ──────────────────────────────────────────
    client = db.relationship("Client", back_populates="invoices")

    # ── Class methods ─────────────────────────────────────────

    @classmethod
    def next_invoice_number(cls):
        """
        Return the next sequential invoice number as 'INV-NNNN'.
        Thread-safe enough for single-process dev/small-scale production.
        """
        last = (
            cls.query
            .order_by(cls.id.desc())
            .with_entities(cls.invoice_number)
            .first()
        )
        if last is None:
            return "INV-0001"
        try:
            seq = int(last[0].split("-")[1]) + 1
        except (IndexError, ValueError):
            seq = cls.query.count() + 1
        return f"INV-{seq:04d}"

    @classmethod
    def calculate_gst(cls, amount):
        """
        Given a base amount (int, float, or Decimal), return
        (gst_amount, total) as Decimal values rounded to 2 d.p.
        """
        base = Decimal(str(amount))
        gst  = (base * GST_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total = base + gst
        return gst, total

    # ── Instance helpers ──────────────────────────────────────

    @property
    def is_overdue(self):
        return (
            self.status == InvoiceStatus.UNPAID
            and self.due_date < date.today()
        )

    @property
    def effective_status(self):
        """Return 'overdue' automatically for past-due unpaid invoices."""
        if self.is_overdue:
            return InvoiceStatus.OVERDUE
        return self.status

    @property
    def status_label(self):
        labels = {
            InvoiceStatus.PAID:    ("Paid",    "status-paid"),
            InvoiceStatus.UNPAID:  ("Unpaid",  "status-unpaid"),
            InvoiceStatus.OVERDUE: ("Overdue", "status-overdue"),
        }
        return labels.get(self.effective_status, ("Unknown", ""))

    @property
    def amount_display(self):
        return f"${float(self.amount):,.2f}"

    @property
    def gst_display(self):
        return f"${float(self.gst):,.2f}"

    @property
    def total_display(self):
        return f"${float(self.total):,.2f}"

    def mark_paid(self):
        """Mark this invoice as paid and record the timestamp."""
        self.status  = InvoiceStatus.PAID
        self.paid_at = datetime.now(timezone.utc)

    def __repr__(self):
        return f"<Invoice {self.invoice_number} status={self.status!r}>"

    def to_dict(self):
        return {
            "id":             self.id,
            "invoice_number": self.invoice_number,
            "client_id":      self.client_id,
            "client_name":    self.client.name if self.client else None,
            "amount":         float(self.amount),
            "gst":            float(self.gst),
            "total":          float(self.total),
            "due_date":       self.due_date.isoformat(),
            "status":         self.effective_status,
            "created_at":     self.created_at.isoformat(),
        }
