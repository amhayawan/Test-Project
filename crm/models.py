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
    role = db.Column(db.String(16), nullable=False, default="staff")  # see ROLES
    active = db.Column(db.Boolean, nullable=False, default=True)
    failed_logins = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime)
    last_login = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_case_manager(self):
        return self.role in ("admin", "case_manager")

    @property
    def is_researcher(self):
        return self.role == "researcher"

    def can(self, perm):
        return perm in ROLE_PERMS.get(self.role, ())

    @property
    def role_label(self):
        return ROLES.get(self.role, self.role)

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
    # Optional earmarking: this donation pays for a specific case / need / sponsorship.
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiary.id"))
    need_id = db.Column(db.Integer, db.ForeignKey("case_need.id"))
    sponsorship_id = db.Column(db.Integer, db.ForeignKey("sponsorship.id"))
    donor = db.relationship("Donor", back_populates="donations")
    recorded_by = db.relationship("User")
    beneficiary = db.relationship("Beneficiary", foreign_keys=[beneficiary_id])
    need = db.relationship("CaseNeed", foreign_keys=[need_id])
    sponsorship = db.relationship("Sponsorship", foreign_keys=[sponsorship_id])

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
    # ---- case management / social research
    researcher_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    zakat_eligible = db.Column(db.String(3))  # yes | no | None (not assessed yet)
    housing_type = db.Column(db.String(20))
    housing_condition = db.Column(db.String(20))
    health_summary = db.Column(db.Text)
    debts = db.Column(db.Numeric(12, 2))
    visit_date = db.Column(db.Date)
    research_findings = db.Column(db.Text)
    recommendation = db.Column(db.Text)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    reviewed_at = db.Column(db.DateTime)
    review_note = db.Column(db.Text)

    researcher = db.relationship("User", foreign_keys=[researcher_id])
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id])
    aids = db.relationship("Aid", back_populates="beneficiary", lazy="dynamic")
    family = db.relationship("FamilyMember", back_populates="beneficiary", order_by="FamilyMember.id",
                             cascade="all, delete-orphan")
    needs = db.relationship("CaseNeed", back_populates="beneficiary", order_by="CaseNeed.id",
                            cascade="all, delete-orphan")
    documents = db.relationship("CaseDocument", back_populates="beneficiary", order_by="CaseDocument.id",
                                cascade="all, delete-orphan")
    sponsorships = db.relationship("Sponsorship", back_populates="beneficiary", order_by="Sponsorship.id")

    @property
    def total_aid(self):
        return self.aids.with_entities(func.coalesce(func.sum(Aid.value), 0)).scalar()

    @property
    def earmarked_donations(self):
        return Donation.query.filter_by(beneficiary_id=self.id).order_by(Donation.donation_date.desc()).all()

    @property
    def research_complete(self):
        return bool(self.visit_date and (self.research_findings or "").strip()
                    and (self.recommendation or "").strip() and self.zakat_eligible)

    @property
    def stage(self):
        if self.status == "under_study":
            return "unassigned" if not self.researcher_id else "researching"
        return self.status

    def __str__(self):
        return self.name


class FamilyMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiary.id"), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    relation = db.Column(db.String(20), nullable=False)
    birth_year = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    education_work = db.Column(db.String(160))
    health = db.Column(db.String(200))
    monthly_income = db.Column(db.Numeric(12, 2))
    beneficiary = db.relationship("Beneficiary", back_populates="family")

    @property
    def age(self):
        return date.today().year - self.birth_year if self.birth_year else None


class CaseNeed(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiary.id"), nullable=False)
    need_type = db.Column(db.String(20), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    amount_needed = db.Column(db.Numeric(12, 2), nullable=False)
    frequency = db.Column(db.String(10), nullable=False, default="once")  # once | monthly
    priority = db.Column(db.String(10), nullable=False, default="normal")
    status = db.Column(db.String(10), nullable=False, default="open")  # open | closed
    notes = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    beneficiary = db.relationship("Beneficiary", back_populates="needs")

    @property
    def funded(self):
        """Money earmarked to this need. Monthly needs count the current month only."""
        q = db.session.query(func.coalesce(func.sum(Donation.amount), 0)).filter(Donation.need_id == self.id)
        if self.frequency == "monthly":
            today = date.today()
            q = q.filter(func.extract("year", Donation.donation_date) == today.year,
                         func.extract("month", Donation.donation_date) == today.month)
        return q.scalar()

    @property
    def funded_total(self):
        return db.session.query(func.coalesce(func.sum(Donation.amount), 0)).filter(
            Donation.need_id == self.id).scalar()

    @property
    def funded_pct(self):
        need = float(self.amount_needed or 0)
        return min(100.0, float(self.funded) / need * 100) if need else 0.0

    @property
    def funding_state(self):
        if self.status == "closed":
            return "closed"
        funded = self.funded
        if funded >= (self.amount_needed or 0):
            return "funded"
        return "partial" if funded > 0 else "open"

    @property
    def funded_display(self):
        suffix = " هذا الشهر" if self.frequency == "monthly" else ""
        return f"{self.funded:,.2f} ({self.funded_pct:.0f}%){suffix}"

    def __str__(self):
        return f"{self.beneficiary.name} — {self.description}"


class Sponsorship(TimestampMixin, db.Model):
    """A donor's recurring commitment to a case (e.g. monthly orphan sponsorship)."""

    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey("donor.id"), nullable=False)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiary.id"), nullable=False)
    need_id = db.Column(db.Integer, db.ForeignKey("case_need.id"))
    monthly_amount = db.Column(db.Numeric(12, 2), nullable=False)
    start_date = db.Column(db.Date, nullable=False, default=date.today)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(10), nullable=False, default="active")  # active | paused | ended
    notes = db.Column(db.Text)
    donor = db.relationship("Donor")
    beneficiary = db.relationship("Beneficiary", back_populates="sponsorships")
    need = db.relationship("CaseNeed")

    @property
    def paid_total(self):
        return db.session.query(func.coalesce(func.sum(Donation.amount), 0)).filter(
            Donation.sponsorship_id == self.id).scalar()

    def months_due(self, today=None):
        today = today or date.today()
        end = min(today, self.end_date) if self.end_date else today
        if not self.start_date or end < self.start_date:
            return 0
        return (end.year - self.start_date.year) * 12 + end.month - self.start_date.month + 1

    @property
    def arrears(self):
        expected = (self.monthly_amount or 0) * self.months_due()
        return max(expected - self.paid_total, 0)

    @property
    def paid_this_month(self):
        today = date.today()
        return Donation.query.filter(
            Donation.sponsorship_id == self.id,
            func.extract("year", Donation.donation_date) == today.year,
            func.extract("month", Donation.donation_date) == today.month).first() is not None

    @property
    def paid_display(self):
        return f"{self.paid_total:,.2f}"

    @property
    def arrears_display(self):
        return f"{self.arrears:,.2f}"

    def __str__(self):
        return f"{self.donor.name} ← {self.beneficiary.name} ({self.monthly_amount:,.0f}/شهر)"


class CaseDocument(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiary.id"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    stored_name = db.Column(db.String(80), nullable=False, unique=True)
    original_name = db.Column(db.String(255))
    content_type = db.Column(db.String(80))
    size = db.Column(db.Integer)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    beneficiary = db.relationship("Beneficiary", back_populates="documents")
    uploaded_by = db.relationship("User")


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


class AuditLog(db.Model):
    """Who did what and when. Rows are only ever added, never edited."""

    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    username = db.Column(db.String(64))
    action = db.Column(db.String(30), nullable=False)
    entity = db.Column(db.String(30))
    record_id = db.Column(db.Integer)
    summary = db.Column(db.String(500))
    ip = db.Column(db.String(64))


ROLES = {
    "admin": "مدير النظام",
    "case_manager": "مدير إدارة الحالات",
    "researcher": "باحث اجتماعي",
    "staff": "موظف (حسابات وتبرعات)",
}

# What each role may open. Researchers see only their own cases and never donors or money.
ROLE_PERMS = {
    "admin": {"dashboard", "cases", "cases.all", "cases.assign", "cases.approve", "cases.funding",
              "beneficiaries", "needs", "sponsorships", "donors", "donations", "aids", "volunteers", "members"},
    "case_manager": {"dashboard", "cases", "cases.all", "cases.assign", "cases.approve", "cases.funding",
                     "beneficiaries", "needs", "sponsorships", "donors", "donations", "aids"},
    "researcher": {"cases", "beneficiaries"},
    "staff": {"dashboard", "cases", "cases.all", "cases.funding", "beneficiaries", "needs", "sponsorships",
              "donors", "donations", "aids", "volunteers", "members"},
}

# Columns added after the first release. Existing databases get them on startup.
ADDED_COLUMNS = {
    "user": {
        "failed_logins": "INTEGER NOT NULL DEFAULT 0",
        "locked_until": "TIMESTAMP",
        "last_login": "TIMESTAMP",
    },
    "beneficiary": {
        "researcher_id": "INTEGER",
        "zakat_eligible": "VARCHAR(3)",
        "housing_type": "VARCHAR(20)",
        "housing_condition": "VARCHAR(20)",
        "health_summary": "TEXT",
        "debts": "NUMERIC(12, 2)",
        "visit_date": "DATE",
        "research_findings": "TEXT",
        "recommendation": "TEXT",
        "reviewed_by_id": "INTEGER",
        "reviewed_at": "TIMESTAMP",
        "review_note": "TEXT",
    },
    "donation": {
        "beneficiary_id": "INTEGER",
        "need_id": "INTEGER",
        "sponsorship_id": "INTEGER",
    },
}
