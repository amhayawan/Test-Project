from datetime import date, datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="staff")  # admin | staff
    active = db.Column(db.Boolean, nullable=False, default=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_active(self):
        return self.active


class Donor(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    donor_type = db.Column(db.String(20), nullable=False, default="individual")
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)
    donations = db.relationship("Donation", back_populates="donor", lazy="dynamic")

    @property
    def total_donated(self):
        return self.donations.with_entities(func.coalesce(func.sum(Donation.amount), 0)).scalar()

    def __str__(self):
        return self.name


class Donation(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    receipt_no = db.Column(db.String(20), unique=True, nullable=False)
    donor_id = db.Column(db.Integer, db.ForeignKey("donor.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    method = db.Column(db.String(20), nullable=False, default="cash")
    purpose = db.Column(db.String(20), nullable=False, default="general")
    donation_date = db.Column(db.Date, nullable=False, default=date.today)
    notes = db.Column(db.Text)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    donor = db.relationship("Donor", back_populates="donations")
    recorded_by = db.relationship("User")

    @staticmethod
    def next_receipt_no(year=None):
        year = year or date.today().year
        prefix = f"R-{year}-"
        last = (
            db.session.query(func.max(Donation.receipt_no))
            .filter(Donation.receipt_no.like(prefix + "%"))
            .scalar()
        )
        seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
        return f"{prefix}{seq:05d}"

    def __str__(self):
        return self.receipt_no


class Beneficiary(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    national_id = db.Column(db.String(14), unique=True)
    phone = db.Column(db.String(30))
    address = db.Column(db.String(255))
    area = db.Column(db.String(80))
    category = db.Column(db.String(20), nullable=False, default="poor_family")
    family_size = db.Column(db.Integer, default=1)
    monthly_income = db.Column(db.Numeric(12, 2), default=0)
    status = db.Column(db.String(20), nullable=False, default="under_study")
    notes = db.Column(db.Text)
    aids = db.relationship("Aid", back_populates="beneficiary", lazy="dynamic")

    @property
    def total_aid(self):
        return self.aids.with_entities(func.coalesce(func.sum(Aid.value), 0)).scalar()

    def __str__(self):
        return self.name


class Aid(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiary.id"), nullable=False)
    aid_type = db.Column(db.String(20), nullable=False, default="cash")
    value = db.Column(db.Numeric(12, 2), nullable=False)
    aid_date = db.Column(db.Date, nullable=False, default=date.today)
    description = db.Column(db.String(255))
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    beneficiary = db.relationship("Beneficiary", back_populates="aids")
    recorded_by = db.relationship("User")

    def __str__(self):
        return f"#{self.id}"


class Volunteer(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    skills = db.Column(db.String(255))
    availability = db.Column(db.String(120))
    join_date = db.Column(db.Date, default=date.today)
    status = db.Column(db.String(20), nullable=False, default="active")
    notes = db.Column(db.Text)

    def __str__(self):
        return self.name


class Member(TimestampMixin, db.Model):
    """General-assembly members of the association (annual dues)."""

    id = db.Column(db.Integer, primary_key=True)
    membership_no = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False)
    national_id = db.Column(db.String(14), unique=True)
    phone = db.Column(db.String(30))
    join_date = db.Column(db.Date, default=date.today)
    paid_until_year = db.Column(db.Integer)
    status = db.Column(db.String(20), nullable=False, default="active")
    notes = db.Column(db.Text)

    @property
    def dues_current(self):
        return bool(self.paid_until_year and self.paid_until_year >= date.today().year)

    def __str__(self):
        return self.name
