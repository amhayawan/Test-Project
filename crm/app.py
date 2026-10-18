import csv
import io
import os
import re
import secrets
from datetime import date
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
from .models import Aid, Beneficiary, Donation, Donor, Member, User, Volunteer, db

APP_NAME = "جمعية حسن عباس زكي"
PHONE_RE = re.compile(r"^\+?[0-9][0-9 \-]{5,19}$")
PER_PAGE = 25


def default_data_dir():
    """Per-user data folder: %APPDATA%\\HAZ-CRM on Windows, ~/.haz-crm elsewhere."""
    base = os.environ.get("APPDATA")
    path = Path(base) / "HAZ-CRM" if base else Path.home() / ".haz-crm"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_secret_key(data_dir):
    key_file = Path(data_dir) / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    return key_file.read_text().strip()


def create_app(config=None):
    app = Flask(__name__)
    data_dir = Path((config or {}).get("DATA_DIR") or os.environ.get("HAZ_CRM_DATA") or default_data_dir()).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    app.config.update(
        DATA_DIR=str(data_dir),
        DB_PATH=str(data_dir / "crm.db"),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{data_dir / 'crm.db'}",
        SECRET_KEY=load_secret_key(data_dir),
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if config:
        app.config.update({k: v for k, v in config.items() if k != "DATA_DIR"})

    db.init_app(app)
    with app.app_context():
        db.create_all()

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
            if not username or not name or len(password) < 6:
                error = "أكمل البيانات (كلمة المرور 6 أحرف على الأقل)"
            elif password != request.form.get("password2"):
                error = "كلمتا المرور غير متطابقتين"
            else:
                user = User(username=username, name=name, role="admin")
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                login_user(user)
                flash("تم إنشاء حساب المدير بنجاح", "success")
                return redirect(url_for("dashboard"))
        return render_template("setup.html", error=error)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            user = User.query.filter_by(username=request.form.get("username", "").strip()).first()
            if user and user.active and user.check_password(request.form.get("password", "")):
                login_user(user)
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
            error = "اسم المستخدم أو كلمة المرور غير صحيحة"
        return render_template("login.html", error=error)

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
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
                if save(errors):
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
                for k, v in new_values.items():
                    setattr(obj, k, v)
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
            if not username or not name or len(password) < 6 or role not in ("admin", "staff"):
                error = "أكمل البيانات (كلمة المرور 6 أحرف على الأقل)"
            elif User.query.filter_by(username=username).first():
                error = "اسم المستخدم مستخدم بالفعل"
            else:
                user = User(username=username, name=name, role=role)
                user.set_password(password)
                db.session.add(user)
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
            db.session.commit()
        return redirect(url_for("users"))

    @app.route("/users/<int:user_id>/reset", methods=["POST"])
    @login_required
    @admin_required
    def user_reset(user_id):
        user = db.get_or_404(User, user_id)
        password = request.form.get("password", "")
        if len(password) < 6:
            flash("كلمة المرور 6 أحرف على الأقل", "error")
        else:
            user.set_password(password)
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
            elif len(request.form.get("new", "")) < 6:
                error = "كلمة المرور الجديدة 6 أحرف على الأقل"
            elif request.form.get("new") != request.form.get("new2"):
                error = "كلمتا المرور غير متطابقتين"
            else:
                current_user.set_password(request.form["new"])
                db.session.commit()
                flash("تم تغيير كلمة المرور", "success")
                return redirect(url_for("dashboard"))
        return render_template("password.html", error=error)

    @app.route("/backup")
    @login_required
    @admin_required
    def backup():
        """Download a consistent copy of the SQLite database."""
        import sqlite3
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir) / "backup.db"
            src = sqlite3.connect(app.config["DB_PATH"])
            dst = sqlite3.connect(tmp)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            data = tmp.read_bytes()
        return send_file(io.BytesIO(data), as_attachment=True,
                         download_name=f"haz-crm-backup-{date.today()}.db",
                         mimetype="application/octet-stream")

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("message.html", title="غير مسموح",
                               message="هذه الصفحة متاحة لمدير النظام فقط"), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("message.html", title="غير موجود",
                               message="الصفحة أو السجل المطلوب غير موجود"), 404


def raw_value(obj, field):
    value = getattr(obj, field["name"])
    if value is None:
        return ""
    if field["type"] == "date":
        return value.isoformat()
    return str(value)


def save(errors):
    try:
        db.session.commit()
        return True
    except IntegrityError:
        db.session.rollback()
        errors["_"] = "هذا السجل مسجل من قبل (رقم قومي أو رقم عضوية مكرر)"
        return False
