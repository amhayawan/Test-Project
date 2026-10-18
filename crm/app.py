import csv
import io
import os
import re
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path

from flask import (Flask, Response, abort, flash, redirect, render_template,
                   request, send_file, session, url_for)
from flask_login import (LoginManager, current_user, login_required,
                         login_user, logout_user)
from sqlalchemy import extract, func, or_
from sqlalchemy.exc import IntegrityError

from .entities import CHOICES, ENTITIES
from . import storage
from .models import (ADDED_COLUMNS, Aid, AuditLog, Beneficiary, Donation, Donor,
                     Member, User, Volunteer, db)

APP_NAME = "جمعية حسن عباس زكي"
PHONE_RE = re.compile(r"^\+?[0-9][0-9 \-]{5,19}$")
PER_PAGE = 25
MIN_PASSWORD = 8
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)


def default_data_dir():
    """Per-user data folder: %APPDATA%\\HAZ-CRM on Windows, ~/.haz-crm elsewhere."""
    base = os.environ.get("APPDATA")
    path = Path(base) / "HAZ-CRM" if base else Path.home() / ".haz-crm"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_secret_key(data_dir):
    if os.environ.get("HAZ_CRM_SECRET_KEY"):
        return os.environ["HAZ_CRM_SECRET_KEY"]
    key_file = Path(data_dir) / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    return key_file.read_text().strip()


def create_app(config=None):
    app = Flask(__name__)
    data_dir = Path((config or {}).get("DATA_DIR") or os.environ.get("HAZ_CRM_DATA") or default_data_dir()).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_url = storage.resolve_database_url(data_dir, (config or {}).get("DATABASE_URL"))
    behind_proxy = os.environ.get("HAZ_CRM_BEHIND_PROXY") == "1"
    app.config.update(
        DATA_DIR=str(data_dir),
        DATABASE_URL=db_url,
        SQLALCHEMY_DATABASE_URI=db_url,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SECRET_KEY=load_secret_key(data_dir),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=behind_proxy,  # cookies only over HTTPS when served behind Caddy/nginx
        PERMANENT_SESSION_LIFETIME=timedelta(
            minutes=int(os.environ.get("HAZ_CRM_SESSION_MINUTES", "30"))),
    )
    if config:
        app.config.update({k: v for k, v in config.items() if k not in ("DATA_DIR", "DATABASE_URL")})

    db.init_app(app)
    with app.app_context():
        db.create_all()
        storage.upgrade_schema(db.engine, ADDED_COLUMNS)

    login_manager = LoginManager(app)
    login_manager.login_view = "login"
    login_manager.login_message = "من فضلك سجّل الدخول أولاً"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    register_template_helpers(app)
    register_routes(app)
    return app


# ---------------------------------------------------------------- helpers

def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def audit(action, entity=None, record_id=None, summary=None, user=None):
    """Add an audit row to the current session (committed with the caller's change)."""
    user = user or (current_user if current_user.is_authenticated else None)
    db.session.add(AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else None,
        action=action, entity=entity, record_id=record_id,
        summary=(summary or "")[:500] or None,
        ip=request.remote_addr if request else None,
    ))


def get_entity(name):
    entity = ENTITIES.get(name)
    if not entity:
        abort(404)
    return entity


def money(value):
    if value is None or value == "":
        return ""
    return f"{Decimal(value):,.2f}"


def display_value(obj, field):
    value = getattr(obj, field["name"])
    ftype = field["type"]
    if value is None or value == "":
        return ""
    if ftype == "select":
        return CHOICES[field["choices"]].get(value, value)
    if ftype.startswith("fk:"):
        related = getattr(obj, field["name"][:-3], None)
        return str(related) if related else ""
    if ftype == "money":
        return money(value)
    if ftype == "date":
        return value.strftime("%Y-%m-%d")
    return str(value)


def register_template_helpers(app):
    @app.context_processor
    def inject():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return dict(app_name=APP_NAME, entities=ENTITIES, choices=CHOICES,
                    csrf_token=session["_csrf"], display_value=display_value,
                    today=date.today().isoformat())

    app.jinja_env.filters["money"] = money

    @app.before_request
    def csrf_protect():
        if request.method == "POST" and not app.config.get("TESTING_NO_CSRF"):
            token = request.form.get("_csrf")
            if not token or token != session.get("_csrf"):
                abort(400, "انتهت صلاحية الصفحة، أعد المحاولة")

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; frame-ancestors 'none'; form-action 'self'")
        if request.endpoint not in ("static",):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.before_request
    def first_run_setup():
        if request.endpoint in ("setup", "static"):
            return None
        if db.session.query(User.id).first() is None:
            return redirect(url_for("setup"))
        return None


def parse_form(entity, form, obj=None):
    """Validate submitted form data. Returns (values, errors)."""
    values, errors = {}, {}
    for field in entity["fields"]:
        name, ftype, label = field["name"], field["type"], field["label"]
        if ftype == "readonly":
            continue
        raw = (form.get(name) or "").strip()
        if not raw:
            if field["required"]:
                errors[name] = f"{label} مطلوب"
            values[name] = None
            continue
        try:
            if ftype == "phone":
                if not PHONE_RE.match(raw):
                    raise ValueError("رقم هاتف غير صحيح")
                value = raw
            elif ftype == "email":
                if "@" not in raw or "." not in raw.split("@")[-1]:
                    raise ValueError("بريد إلكتروني غير صحيح")
                value = raw
            elif ftype == "nid":
                if not (raw.isdigit() and len(raw) == 14):
                    raise ValueError("الرقم القومي يجب أن يكون 14 رقماً")
                value = raw
            elif ftype == "int":
                value = int(raw)
                if value < 0:
                    raise ValueError("يجب أن يكون رقماً موجباً")
            elif ftype == "year":
                value = int(raw)
                if not 1900 <= value <= 2100:
                    raise ValueError("سنة غير صحيحة")
            elif ftype == "money":
                value = Decimal(raw.replace(",", ""))
                if value < 0 or (field["required"] and value == 0):
                    raise ValueError("المبلغ يجب أن يكون أكبر من صفر")
            elif ftype == "date":
                value = date.fromisoformat(raw)
            elif ftype == "select":
                if raw not in CHOICES[field["choices"]]:
                    raise ValueError("اختيار غير صحيح")
                value = raw
            elif ftype.startswith("fk:"):
                target = ENTITIES[ftype[3:]]["model"]
                if not db.session.get(target, int(raw)):
                    raise ValueError("السجل المختار غير موجود")
                value = int(raw)
            else:
                value = raw
            values[name] = value
        except (ValueError, InvalidOperation) as exc:
            msg = str(exc)
            errors[name] = msg if any("؀" <= c <= "ۿ" for c in msg) else f"{label}: قيمة غير صحيحة"
    return values, errors


def fk_options(entity):
    options = {}
    for field in entity["fields"]:
        if field["type"].startswith("fk:"):
            target = ENTITIES[field["type"][3:]]
            options[field["name"]] = target["model"].query.order_by(target["order"]).all()
    return options


def search_query(entity, q):
    model = entity["model"]
    query = model.query
    if q:
        cols = [getattr(model, f["name"]) for f in entity["fields"] if f["search"]]
        query = query.filter(or_(*[c.ilike(f"%{q}%") for c in cols]))
    return query.order_by(entity["order"])


# ---------------------------------------------------------------- routes

def register_routes(app):

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if db.session.query(User.id).first() is not None:
            return redirect(url_for("login"))
        error = None
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            name = request.form.get("name", "").strip()
            password = request.form.get("password", "")
            if not username or not name or len(password) < MIN_PASSWORD:
                error = f"أكمل البيانات (كلمة المرور {MIN_PASSWORD} أحرف على الأقل)"
            elif password != request.form.get("password2"):
                error = "كلمتا المرور غير متطابقتين"
            else:
                user = User(username=username, name=name, role="admin")
                user.set_password(password)
                db.session.add(user)
                db.session.flush()
                audit("setup", "users", user.id, "إنشاء حساب المدير الأول", user=user)
                db.session.commit()
                session.permanent = True
                login_user(user)
                flash("تم إنشاء حساب المدير بنجاح", "success")
                return redirect(url_for("dashboard"))
        return render_template("setup.html", error=error)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            user = User.query.filter_by(username=username).first()
            now = datetime.now()
            if user and user.locked_until and user.locked_until > now:
                minutes = int((user.locked_until - now).total_seconds() // 60) + 1
                error = f"الحساب مقفل مؤقتاً بسبب محاولات دخول خاطئة. حاول بعد {minutes} دقيقة"
            elif user and user.active and user.check_password(request.form.get("password", "")):
                user.failed_logins = 0
                user.locked_until = None
                user.last_login = now
                audit("login", user=user)
                db.session.commit()
                session.permanent = True
                login_user(user)
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
            else:
                error = "اسم المستخدم أو كلمة المرور غير صحيحة"
                audit("login_failed", summary=f"اسم المستخدم: {username[:64]}")
                if user:
                    user.failed_logins = (user.failed_logins or 0) + 1
                    if user.failed_logins >= MAX_FAILED_LOGINS:
                        user.failed_logins = 0
                        user.locked_until = now + LOCKOUT
                        audit("locked", "users", user.id, f"قفل الحساب {user.username} لمدة 15 دقيقة")
                db.session.commit()
        return render_template("login.html", error=error)

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        audit("logout")
        db.session.commit()
        logout_user()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        year = date.today().year
        month = date.today().month

        def total(model, col, date_col, **period):
            q = db.session.query(func.coalesce(func.sum(col), 0))
            if "year" in period:
                q = q.filter(extract("year", date_col) == period["year"])
            if "month" in period:
                q = q.filter(extract("month", date_col) == period["month"])
            return Decimal(str(q.scalar() or 0))

        stats = dict(
            donations_month=total(Donation, Donation.amount, Donation.donation_date, year=year, month=month),
            donations_year=total(Donation, Donation.amount, Donation.donation_date, year=year),
            aid_year=total(Aid, Aid.value, Aid.aid_date, year=year),
            donors=Donor.query.count(),
            beneficiaries=Beneficiary.query.filter_by(status="approved").count(),
            under_study=Beneficiary.query.filter_by(status="under_study").count(),
            volunteers=Volunteer.query.filter_by(status="active").count(),
            members=Member.query.count(),
            members_unpaid=Member.query.filter(
                Member.status == "active",
                or_(Member.paid_until_year.is_(None), Member.paid_until_year < year)).count(),
        )
        by_purpose = (db.session.query(Donation.purpose, func.sum(Donation.amount))
                      .filter(extract("year", Donation.donation_date) == year)
                      .group_by(Donation.purpose).order_by(func.sum(Donation.amount).desc()).all())
        rows = [(m,
                 total(Donation, Donation.amount, Donation.donation_date, year=year, month=m),
                 total(Aid, Aid.value, Aid.aid_date, year=year, month=m)) for m in range(1, 13)]
        peak = max([d for _, d, _ in rows] + [a for _, _, a in rows] + [Decimal(1)])
        monthly = [dict(month=m, donations=d, aid=a,
                        d_pct=float(d / peak * 100), a_pct=float(a / peak * 100)) for m, d, a in rows]
        recent = Donation.query.order_by(Donation.created_at.desc()).limit(8).all()
        return render_template("dashboard.html", stats=stats, by_purpose=by_purpose,
                               monthly=monthly, recent=recent, year=year)

    # ---- generic CRUD

    @app.route("/<entity_name>/")
    @login_required
    def entity_list(entity_name):
        entity = get_entity(entity_name)
        q = request.args.get("q", "").strip()
        page = max(request.args.get("page", 1, type=int), 1)
        pagination = search_query(entity, q).paginate(page=page, per_page=PER_PAGE, error_out=False)
        return render_template("list.html", entity=entity, entity_name=entity_name,
                               pagination=pagination, q=q)

    @app.route("/<entity_name>/export.csv")
    @login_required
    def entity_export(entity_name):
        entity = get_entity(entity_name)
        q = request.args.get("q", "").strip()
        buf = io.StringIO()
        buf.write("﻿")  # BOM so Excel shows Arabic correctly
        writer = csv.writer(buf)
        writer.writerow([f["label"] for f in entity["fields"]])
        for obj in search_query(entity, q).all():
            writer.writerow([display_value(obj, f) for f in entity["fields"]])
        return Response(buf.getvalue(), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename={entity_name}-{date.today()}.csv"})

    @app.route("/<entity_name>/new", methods=["GET", "POST"])
    @login_required
    def entity_new(entity_name):
        entity = get_entity(entity_name)
        errors, values = {}, dict(request.args.items())
        if request.method == "POST":
            values, errors = parse_form(entity, request.form)
            if not errors:
                obj = entity["model"](**values)
                if entity_name == "donations":
                    obj.receipt_no = Donation.next_receipt_no(obj.donation_date.year)
                if hasattr(obj, "recorded_by_id"):
                    obj.recorded_by_id = current_user.id
                db.session.add(obj)
                if save(errors, flush_only=True):
                    audit("create", entity_name, obj.id, describe(entity, obj))
                if not errors and save(errors):
                    flash(f"تم حفظ {entity['singular']} بنجاح", "success")
                    return redirect(url_for("entity_detail", entity_name=entity_name, obj_id=obj.id))
            values = request.form
        return render_template("form.html", entity=entity, entity_name=entity_name, obj=None,
                               values=values, errors=errors, fk=fk_options(entity))

    @app.route("/<entity_name>/<int:obj_id>")
    @login_required
    def entity_detail(entity_name, obj_id):
        entity = get_entity(entity_name)
        obj = db.get_or_404(entity["model"], obj_id)
        related = None
        if entity_name == "donors":
            related = ("donations", obj.donations.order_by(Donation.donation_date.desc()).all(), obj.total_donated)
        elif entity_name == "beneficiaries":
            related = ("aids", obj.aids.order_by(Aid.aid_date.desc()).all(), obj.total_aid)
        return render_template("detail.html", entity=entity, entity_name=entity_name, obj=obj, related=related)

    @app.route("/<entity_name>/<int:obj_id>/edit", methods=["GET", "POST"])
    @login_required
    def entity_edit(entity_name, obj_id):
        entity = get_entity(entity_name)
        obj = db.get_or_404(entity["model"], obj_id)
        errors = {}
        values = {f["name"]: raw_value(obj, f) for f in entity["fields"]}
        if request.method == "POST":
            new_values, errors = parse_form(entity, request.form, obj)
            if not errors:
                changes = []
                for k, v in new_values.items():
                    if getattr(obj, k) != v:
                        field = next(f for f in entity["fields"] if f["name"] == k)
                        old = display_value(obj, field)
                        setattr(obj, k, v)
                        changes.append(f"{field['label']}: {old or '—'} ← {display_value(obj, field) or '—'}")
                if changes:
                    audit("update", entity_name, obj.id, f"{obj} | " + " ؛ ".join(changes))
                if save(errors):
                    flash("تم حفظ التعديلات", "success")
                    return redirect(url_for("entity_detail", entity_name=entity_name, obj_id=obj.id))
            values = request.form
        return render_template("form.html", entity=entity, entity_name=entity_name, obj=obj,
                               values=values, errors=errors, fk=fk_options(entity))

    @app.route("/<entity_name>/<int:obj_id>/delete", methods=["POST"])
    @login_required
    @admin_required
    def entity_delete(entity_name, obj_id):
        entity = get_entity(entity_name)
        obj = db.get_or_404(entity["model"], obj_id)
        children = getattr(obj, "donations", None) or getattr(obj, "aids", None)
        if children is not None and children.count():
            flash("لا يمكن الحذف لوجود سجلات مرتبطة بهذا السجل", "error")
            return redirect(url_for("entity_detail", entity_name=entity_name, obj_id=obj_id))
        audit("delete", entity_name, obj.id, describe(entity, obj))
        db.session.delete(obj)
        db.session.commit()
        flash("تم الحذف", "success")
        return redirect(url_for("entity_list", entity_name=entity_name))

    @app.route("/donations/<int:obj_id>/receipt")
    @login_required
    def donation_receipt(obj_id):
        donation = db.get_or_404(Donation, obj_id)
        return render_template("receipt.html", d=donation)

    # ---- users & account

    @app.route("/users/", methods=["GET", "POST"])
    @login_required
    @admin_required
    def users():
        error = None
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            name = request.form.get("name", "").strip()
            password = request.form.get("password", "")
            role = request.form.get("role", "staff")
            if not username or not name or len(password) < MIN_PASSWORD or role not in ("admin", "staff"):
                error = f"أكمل البيانات (كلمة المرور {MIN_PASSWORD} أحرف على الأقل)"
            elif User.query.filter_by(username=username).first():
                error = "اسم المستخدم مستخدم بالفعل"
            else:
                user = User(username=username, name=name, role=role)
                user.set_password(password)
                db.session.add(user)
                db.session.flush()
                audit("user_add", "users", user.id, f"{username} ({role})")
                db.session.commit()
                flash("تمت إضافة المستخدم", "success")
                return redirect(url_for("users"))
        return render_template("users.html", users=User.query.order_by(User.username).all(), error=error)

    @app.route("/users/<int:user_id>/toggle", methods=["POST"])
    @login_required
    @admin_required
    def user_toggle(user_id):
        user = db.get_or_404(User, user_id)
        if user.id == current_user.id:
            flash("لا يمكنك إيقاف حسابك", "error")
        else:
            user.active = not user.active
            audit("user_toggle", "users", user.id, f"{user.username}: {'تفعيل' if user.active else 'إيقاف'}")
            db.session.commit()
        return redirect(url_for("users"))

    @app.route("/users/<int:user_id>/reset", methods=["POST"])
    @login_required
    @admin_required
    def user_reset(user_id):
        user = db.get_or_404(User, user_id)
        password = request.form.get("password", "")
        if len(password) < MIN_PASSWORD:
            flash(f"كلمة المرور {MIN_PASSWORD} أحرف على الأقل", "error")
        else:
            user.set_password(password)
            user.failed_logins = 0
            user.locked_until = None
            audit("password_reset", "users", user.id, user.username)
            db.session.commit()
            flash(f"تم تغيير كلمة مرور {user.username}", "success")
        return redirect(url_for("users"))

    @app.route("/account/password", methods=["GET", "POST"])
    @login_required
    def change_password():
        error = None
        if request.method == "POST":
            if not current_user.check_password(request.form.get("current", "")):
                error = "كلمة المرور الحالية غير صحيحة"
            elif len(request.form.get("new", "")) < MIN_PASSWORD:
                error = f"كلمة المرور الجديدة {MIN_PASSWORD} أحرف على الأقل"
            elif request.form.get("new") != request.form.get("new2"):
                error = "كلمتا المرور غير متطابقتين"
            else:
                current_user.set_password(request.form["new"])
                audit("password_change", "users", current_user.id)
                db.session.commit()
                flash("تم تغيير كلمة المرور", "success")
                return redirect(url_for("dashboard"))
        return render_template("password.html", error=error)

    @app.route("/backup")
    @login_required
    @admin_required
    def backup():
        """Download a complete copy of the data as a portable SQLite file."""
        data = storage.backup_bytes(app.config["DATABASE_URL"], db.metadata)
        audit("backup")
        db.session.commit()
        return send_file(io.BytesIO(data), as_attachment=True,
                         download_name=f"haz-crm-backup-{date.today()}.db",
                         mimetype="application/octet-stream")

    @app.route("/audit/")
    @login_required
    @admin_required
    def audit_log():
        q = request.args.get("q", "").strip()
        page = max(request.args.get("page", 1, type=int), 1)
        query = AuditLog.query
        if q:
            query = query.filter(or_(AuditLog.username.ilike(f"%{q}%"), AuditLog.summary.ilike(f"%{q}%"),
                                     AuditLog.action.ilike(f"%{q}%"), AuditLog.entity.ilike(f"%{q}%")))
        pagination = query.order_by(AuditLog.id.desc()).paginate(page=page, per_page=50, error_out=False)
        return render_template("audit.html", pagination=pagination, q=q, actions=AUDIT_ACTIONS)

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("message.html", title="غير مسموح",
                               message="هذه الصفحة متاحة لمدير النظام فقط"), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("message.html", title="غير موجود",
                               message="الصفحة أو السجل المطلوب غير موجود"), 404


AUDIT_ACTIONS = {
    "setup": "إعداد أول", "login": "دخول", "logout": "خروج", "login_failed": "محاولة دخول فاشلة",
    "locked": "قفل حساب", "create": "إضافة", "update": "تعديل", "delete": "حذف", "backup": "نسخة احتياطية",
    "user_add": "إضافة مستخدم", "user_toggle": "تفعيل/إيقاف مستخدم", "password_reset": "تغيير كلمة مرور مستخدم",
    "password_change": "تغيير كلمة المرور",
}


def describe(entity, obj):
    parts = [str(obj)]
    for f in entity["fields"]:
        if f["type"] in ("money", "select") or f["type"].startswith("fk:"):
            value = display_value(obj, f)
            if value:
                parts.append(f"{f['label']}: {value}")
    return " | ".join(parts)


def raw_value(obj, field):
    value = getattr(obj, field["name"])
    if value is None:
        return ""
    if field["type"] == "date":
        return value.isoformat()
    return str(value)


def save(errors, flush_only=False):
    try:
        db.session.flush() if flush_only else db.session.commit()
        return True
    except IntegrityError:
        db.session.rollback()
        errors["_"] = "هذا السجل مسجل من قبل (رقم قومي أو رقم عضوية مكرر)"
        return False
