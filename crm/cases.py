"""Case management: researcher assignment, social research, needs, documents and approval."""

import secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from .entities import CHOICES
from .models import (Aid, AuditLog, Beneficiary, CaseDocument, CaseNeed, Donation, FamilyMember, Sponsorship,
                     User, db)

ALLOWED_UPLOADS = {
    ".pdf": ("application/pdf", (b"%PDF",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".png": ("image/png", (b"\x89PNG",)),
}


def _money(raw, required=False):
    raw = (raw or "").replace(",", "").strip()
    if not raw:
        if required:
            raise ValueError("المبلغ مطلوب")
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError("مبلغ غير صحيح")
    if value < 0 or (required and value == 0):
        raise ValueError("المبلغ يجب أن يكون أكبر من صفر")
    return value


def _choice(raw, key, required=False):
    raw = (raw or "").strip()
    if not raw:
        if required:
            raise ValueError("اختيار مطلوب")
        return None
    if raw not in CHOICES[key]:
        raise ValueError("اختيار غير صحيح")
    return raw


def register_case_routes(app):
    from .app import audit, can_edit_case, can_view_case, case_scope, perm_required

    def get_case(case_id, edit=False):
        case = db.get_or_404(Beneficiary, case_id)
        if not can_view_case(case):
            abort(403)
        if edit and not can_edit_case(case):
            flash("لا يمكن تعديل هذه الحالة الآن (ليست مسندة إليك أو أُرسلت للاعتماد)", "error")
            abort(redirect(url_for("case_view", case_id=case.id)))
        return case

    def researchers():
        return (User.query.filter(User.active.is_(True), User.role.in_(("researcher", "case_manager")))
                .order_by(User.name).all())

    # ------------------------------------------------------------ dashboard

    @app.route("/cases/")
    @login_required
    @perm_required("cases")
    def cases_dashboard():
        base = case_scope(Beneficiary.query)
        counts = {
            "unassigned": base.filter(Beneficiary.status == "under_study", Beneficiary.researcher_id.is_(None)).count(),
            "researching": base.filter(Beneficiary.status == "under_study", Beneficiary.researcher_id.isnot(None)).count(),
            "recommended": base.filter(Beneficiary.status == "recommended").count(),
            "approved": base.filter(Beneficiary.status == "approved").count(),
            "closed": base.filter(Beneficiary.status.in_(("rejected", "suspended"))).count(),
        }
        stage = request.args.get("stage", "")
        stage_filters = {
            "unassigned": [Beneficiary.status == "under_study", Beneficiary.researcher_id.is_(None)],
            "researching": [Beneficiary.status == "under_study", Beneficiary.researcher_id.isnot(None)],
            "recommended": [Beneficiary.status == "recommended"],
            "approved": [Beneficiary.status == "approved"],
            "closed": [Beneficiary.status.in_(("rejected", "suspended"))],
        }
        if stage not in stage_filters:
            stage = "recommended" if current_user.can("cases.approve") and counts["recommended"] else "researching"
        rows = base.filter(*stage_filters[stage]).order_by(Beneficiary.created_at.desc()).limit(200).all()

        open_needs = (CaseNeed.query.join(Beneficiary).filter(CaseNeed.status == "open")
                      .filter(Beneficiary.status == "approved"))
        open_needs = case_scope(open_needs)
        needs = sorted(open_needs.all(), key=lambda n: ({"urgent": 0, "high": 1}.get(n.priority, 2), n.id))
        unfunded = [n for n in needs if n.funding_state != "funded"]
        totals = dict(
            needed=sum((n.amount_needed for n in unfunded), Decimal(0)),
            funded=sum((n.funded for n in unfunded), Decimal(0)),
        )
        late = []
        if current_user.can("cases.funding"):
            late = [s for s in Sponsorship.query.filter_by(status="active").all()
                    if s.months_due() > 0 and not s.paid_this_month]
        return render_template("cases_dashboard.html", counts=counts, stage=stage, rows=rows,
                               needs=unfunded[:12], needs_count=len(unfunded), totals=totals, late=late[:12],
                               late_count=len(late), researchers=researchers())

    # ------------------------------------------------------------ workspace

    @app.route("/cases/<int:case_id>")
    @login_required
    @perm_required("cases")
    def case_view(case_id):
        case = get_case(case_id)
        history = (AuditLog.query.filter_by(entity="beneficiaries", record_id=case.id)
                   .order_by(AuditLog.id.desc()).limit(30).all())
        from .app import AUDIT_ACTIONS
        aids = case.aids.order_by(Aid.aid_date.desc()).all()
        return render_template("case.html", case=case, can_edit=can_edit_case(case), researchers=researchers(),
                               history=history, actions=AUDIT_ACTIONS, aids=aids,
                               show_funding=current_user.can("cases.funding"),
                               donations=case.earmarked_donations if current_user.can("cases.funding") else [])

    @app.route("/cases/<int:case_id>/assign", methods=["POST"])
    @login_required
    @perm_required("cases.assign")
    def case_assign(case_id):
        case = get_case(case_id)
        user_id = request.form.get("researcher_id", type=int)
        user = db.session.get(User, user_id) if user_id else None
        if not user or user.role not in ("researcher", "case_manager") or not user.active:
            flash("اختر باحثاً من القائمة", "error")
        elif case.researcher_id != user.id:
            old = case.researcher.name if case.researcher else "—"
            case.researcher_id = user.id
            audit("assign", "beneficiaries", case.id, f"{case.name}: {old} ← {user.name}")
            db.session.commit()
            flash(f"تم إسناد الحالة إلى {user.name}", "success")
        return redirect(request.form.get("next") or url_for("case_view", case_id=case.id))

    @app.route("/cases/<int:case_id>/research", methods=["GET", "POST"])
    @login_required
    @perm_required("cases")
    def case_research(case_id):
        case = get_case(case_id, edit=True)
        errors = {}
        if request.method == "POST":
            f = request.form
            new = {}
            try:
                new["zakat_eligible"] = _choice(f.get("zakat_eligible"), "yes_no")
            except ValueError as e:
                errors["zakat_eligible"] = str(e)
            try:
                new["housing_type"] = _choice(f.get("housing_type"), "housing_type")
            except ValueError as e:
                errors["housing_type"] = str(e)
            try:
                new["housing_condition"] = _choice(f.get("housing_condition"), "housing_condition")
            except ValueError as e:
                errors["housing_condition"] = str(e)
            try:
                new["debts"] = _money(f.get("debts"))
            except ValueError as e:
                errors["debts"] = str(e)
            try:
                raw = (f.get("visit_date") or "").strip()
                new["visit_date"] = date.fromisoformat(raw) if raw else None
                if new["visit_date"] and new["visit_date"] > date.today():
                    raise ValueError("تاريخ الزيارة في المستقبل")
            except ValueError as e:
                errors["visit_date"] = str(e) if "تاريخ" in str(e) else "تاريخ غير صحيح"
            for name in ("health_summary", "research_findings", "recommendation"):
                new[name] = (f.get(name) or "").strip() or None
            if not errors:
                labels = {"zakat_eligible": "مستحق للزكاة", "housing_type": "نوع السكن",
                          "housing_condition": "حالة السكن", "debts": "الديون", "visit_date": "تاريخ الزيارة",
                          "health_summary": "الحالة الصحية", "research_findings": "نتائج البحث",
                          "recommendation": "التوصية"}
                changed = [labels[k] for k, v in new.items() if getattr(case, k) != v]
                for k, v in new.items():
                    setattr(case, k, v)
                if changed:
                    audit("research", "beneficiaries", case.id, f"{case.name}: " + "، ".join(changed))
                db.session.commit()
                flash("تم حفظ البحث الاجتماعي", "success")
                return redirect(url_for("case_view", case_id=case.id))
        return render_template("case_research.html", case=case, errors=errors,
                               v=request.form if request.method == "POST" else None)

    @app.route("/cases/<int:case_id>/submit", methods=["POST"])
    @login_required
    @perm_required("cases")
    def case_submit(case_id):
        case = get_case(case_id, edit=True)
        if case.status != "under_study":
            flash("الحالة ليست تحت الدراسة", "error")
        elif not case.research_complete:
            flash("أكمل البحث أولاً: تاريخ الزيارة، نتائج البحث، التوصية، واستحقاق الزكاة", "error")
        else:
            case.status = "recommended"
            if not case.researcher_id:
                case.researcher_id = current_user.id
            audit("recommend", "beneficiaries", case.id, f"{case.name}: {(case.recommendation or '')[:200]}")
            db.session.commit()
            flash("تم إرسال الحالة لمدير إدارة الحالات للاعتماد", "success")
        return redirect(url_for("case_view", case_id=case.id))

    @app.route("/cases/<int:case_id>/review", methods=["POST"])
    @login_required
    @perm_required("cases.approve")
    def case_review(case_id):
        case = get_case(case_id)
        decision = request.form.get("decision")
        note = (request.form.get("review_note") or "").strip()
        allowed = {
            "approve": ("recommended", "approved"),
            "reject": ("recommended", "rejected"),
            "return": ("recommended", "under_study"),
            "suspend": ("approved", "suspended"),
            "reactivate": ("suspended", "approved"),
        }
        if decision not in allowed:
            abort(400)
        source, target = allowed[decision]
        if case.status != source:
            flash("لا يمكن تنفيذ هذا الإجراء على الحالة في وضعها الحالي", "error")
        elif decision in ("reject", "return", "suspend") and not note:
            flash("اكتب سبب القرار في الملاحظة", "error")
        else:
            case.status = target
            case.reviewed_by_id = current_user.id
            case.reviewed_at = datetime.now()
            case.review_note = note or None
            audit({"reactivate": "approve"}.get(decision, decision), "beneficiaries", case.id,
                  f"{case.name}" + (f": {note[:250]}" if note else ""))
            db.session.commit()
            flash({"approve": "تم اعتماد الحالة", "reject": "تم رفض الحالة", "return": "أعيدت الحالة للباحث",
                   "suspend": "تم إيقاف الحالة", "reactivate": "أعيد تفعيل الحالة"}[decision], "success")
        return redirect(url_for("case_view", case_id=case.id))

    # ------------------------------------------------------------ family

    @app.route("/cases/<int:case_id>/family", methods=["POST"])
    @login_required
    @perm_required("cases")
    def case_family_add(case_id):
        case = get_case(case_id, edit=True)
        f = request.form
        try:
            name = (f.get("name") or "").strip()
            if not name:
                raise ValueError("اسم الفرد مطلوب")
            relation = _choice(f.get("relation"), "relation", required=True)
            gender = _choice(f.get("gender"), "gender")
            birth_year = (f.get("birth_year") or "").strip()
            birth_year = int(birth_year) if birth_year else None
            if birth_year and not 1900 <= birth_year <= date.today().year:
                raise ValueError("سنة الميلاد غير صحيحة")
            income = _money(f.get("monthly_income"))
        except ValueError as e:
            flash(str(e) if any("؀" <= c <= "ۿ" for c in str(e)) else "بيانات غير صحيحة", "error")
            return redirect(url_for("case_view", case_id=case.id) + "#family")
        member = FamilyMember(beneficiary_id=case.id, name=name, relation=relation, gender=gender,
                              birth_year=birth_year, monthly_income=income,
                              education_work=(f.get("education_work") or "").strip() or None,
                              health=(f.get("health") or "").strip() or None)
        db.session.add(member)
        db.session.flush()
        case.family_size = FamilyMember.query.filter_by(beneficiary_id=case.id).count()
        audit("family_add", "beneficiaries", case.id, f"{case.name}: {name} ({CHOICES['relation'][relation]})")
        db.session.commit()
        flash("تمت إضافة فرد الأسرة", "success")
        return redirect(url_for("case_view", case_id=case.id) + "#family")

    @app.route("/cases/<int:case_id>/family/<int:member_id>/delete", methods=["POST"])
    @login_required
    @perm_required("cases")
    def case_family_delete(case_id, member_id):
        case = get_case(case_id, edit=True)
        member = db.get_or_404(FamilyMember, member_id)
        if member.beneficiary_id != case.id:
            abort(404)
        audit("family_delete", "beneficiaries", case.id, f"{case.name}: {member.name}")
        db.session.delete(member)
        db.session.flush()
        case.family_size = max(FamilyMember.query.filter_by(beneficiary_id=case.id).count(), 1)
        db.session.commit()
        flash("تم حذف فرد الأسرة", "success")
        return redirect(url_for("case_view", case_id=case.id) + "#family")

    # ------------------------------------------------------------ needs

    @app.route("/cases/<int:case_id>/needs", methods=["POST"])
    @login_required
    @perm_required("cases")
    def case_need_add(case_id):
        case = get_case(case_id, edit=True)
        f = request.form
        try:
            need_type = _choice(f.get("need_type"), "need_type", required=True)
            description = (f.get("description") or "").strip()
            if not description:
                raise ValueError("وصف الاحتياج مطلوب")
            amount = _money(f.get("amount_needed"), required=True)
            frequency = _choice(f.get("frequency") or "once", "frequency", required=True)
            priority = _choice(f.get("priority") or "normal", "priority", required=True)
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("case_view", case_id=case.id) + "#needs")
        need = CaseNeed(beneficiary_id=case.id, need_type=need_type, description=description,
                        amount_needed=amount, frequency=frequency, priority=priority,
                        notes=(f.get("notes") or "").strip() or None, created_by_id=current_user.id)
        db.session.add(need)
        audit("need_add", "beneficiaries", case.id,
              f"{case.name}: {description} — {amount:,.2f} ({CHOICES['priority'][priority]})")
        db.session.commit()
        flash("تمت إضافة الاحتياج", "success")
        return redirect(url_for("case_view", case_id=case.id) + "#needs")

    @app.route("/cases/<int:case_id>/needs/<int:need_id>/status", methods=["POST"])
    @login_required
    @perm_required("cases.approve")
    def case_need_status(case_id, need_id):
        case = get_case(case_id)
        need = db.get_or_404(CaseNeed, need_id)
        if need.beneficiary_id != case.id:
            abort(404)
        need.status = "closed" if need.status == "open" else "open"
        audit("need_status", "beneficiaries", case.id,
              f"{case.name}: {need.description} ← {CHOICES['need_status'][need.status]}")
        db.session.commit()
        return redirect(url_for("case_view", case_id=case.id) + "#needs")

    # ------------------------------------------------------------ documents

    def upload_dir(case_id):
        path = Path(current_app.config["UPLOAD_DIR"]) / str(case_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @app.route("/cases/<int:case_id>/documents", methods=["POST"])
    @login_required
    @perm_required("cases")
    def case_doc_upload(case_id):
        case = get_case(case_id, edit=True)
        file = request.files.get("file")
        title = (request.form.get("title") or "").strip()
        if not file or not file.filename:
            flash("اختر ملفاً", "error")
            return redirect(url_for("case_view", case_id=case.id) + "#docs")
        ext = Path(file.filename).suffix.lower()
        head = file.stream.read(8)
        file.stream.seek(0)
        if ext not in ALLOWED_UPLOADS or not head.startswith(ALLOWED_UPLOADS[ext][1]):
            flash("الملفات المسموحة: PDF أو صورة JPG/PNG", "error")
            return redirect(url_for("case_view", case_id=case.id) + "#docs")
        stored = f"{secrets.token_hex(16)}{ext}"
        target = upload_dir(case.id) / stored
        file.save(target)
        size = target.stat().st_size
        if size > current_app.config["MAX_CONTENT_LENGTH"] - 2 * 1024 * 1024:
            target.unlink()
            flash("حجم الملف كبير جداً", "error")
            return redirect(url_for("case_view", case_id=case.id) + "#docs")
        doc = CaseDocument(beneficiary_id=case.id, title=title or Path(file.filename).stem[:160],
                           stored_name=stored, original_name=file.filename[:255],
                           content_type=ALLOWED_UPLOADS[ext][0], size=size, uploaded_by_id=current_user.id)
        db.session.add(doc)
        audit("doc_upload", "beneficiaries", case.id, f"{case.name}: {doc.title}")
        db.session.commit()
        flash("تم رفع المستند", "success")
        return redirect(url_for("case_view", case_id=case.id) + "#docs")

    @app.route("/cases/<int:case_id>/documents/<int:doc_id>")
    @login_required
    @perm_required("cases")
    def case_doc_download(case_id, doc_id):
        case = get_case(case_id)
        doc = db.get_or_404(CaseDocument, doc_id)
        if doc.beneficiary_id != case.id:
            abort(404)
        path = upload_dir(case.id) / doc.stored_name
        if not path.exists():
            abort(404)
        audit("doc_download", "beneficiaries", case.id, f"{case.name}: {doc.title}")
        db.session.commit()
        name = doc.original_name or doc.stored_name
        return send_file(path, mimetype=doc.content_type, as_attachment=True, download_name=name)

    @app.route("/cases/<int:case_id>/documents/<int:doc_id>/delete", methods=["POST"])
    @login_required
    @perm_required("cases.approve")
    def case_doc_delete(case_id, doc_id):
        case = get_case(case_id)
        doc = db.get_or_404(CaseDocument, doc_id)
        if doc.beneficiary_id != case.id:
            abort(404)
        path = upload_dir(case.id) / doc.stored_name
        audit("doc_delete", "beneficiaries", case.id, f"{case.name}: {doc.title}")
        db.session.delete(doc)
        db.session.commit()
        if path.exists():
            path.unlink()
        flash("تم حذف المستند", "success")
        return redirect(url_for("case_view", case_id=case.id) + "#docs")
