"""Field definitions that drive the generic list / form / export views."""

from .models import Aid, Beneficiary, CaseNeed, Donation, Donor, Member, Sponsorship, Volunteer

CHOICES = {
    "donor_type": {"individual": "فرد", "company": "شركة / مؤسسة"},
    "method": {
        "cash": "نقدي",
        "bank": "تحويل بنكي",
        "instapay": "إنستاباي",
        "wallet": "محفظة إلكترونية",
        "check": "شيك",
        "in_kind": "عيني",
    },
    "purpose": {
        "general": "تبرع عام",
        "zakat": "زكاة مال",
        "zakat_fitr": "زكاة فطر",
        "sadaqa": "صدقة",
        "orphans": "كفالة أيتام",
        "medical": "علاج",
        "education": "تعليم",
        "food": "إطعام / شنط رمضان",
        "udhiya": "أضاحي",
    },
    "category": {
        "poor_family": "أسرة محتاجة",
        "orphan": "يتيم",
        "widow": "أرملة / مطلقة",
        "elderly": "مسن",
        "disabled": "ذوي همم",
        "sick": "مريض",
        "student": "طالب",
    },
    "beneficiary_status": {
        "under_study": "تحت الدراسة",
        "recommended": "بانتظار الاعتماد",
        "approved": "مقبول",
        "rejected": "مرفوض",
        "suspended": "موقوف",
    },
    "aid_type": {
        "cash": "مساعدة نقدية",
        "food": "مواد غذائية",
        "medical": "علاج",
        "education": "تعليم",
        "clothes": "ملابس",
        "housing": "سكن / ترميم",
        "other": "أخرى",
    },
    "volunteer_status": {"active": "نشط", "inactive": "غير نشط"},
    "yes_no": {"yes": "نعم", "no": "لا"},
    "housing_type": {"owned": "تمليك", "rent_old": "إيجار قديم", "rent_new": "إيجار جديد",
                     "relatives": "مع الأقارب", "free": "بدون مقابل / إيواء"},
    "housing_condition": {"good": "جيدة", "fair": "متوسطة", "poor": "سيئة", "unsafe": "غير آمنة / آيلة للسقوط"},
    "relation": {"head": "رب الأسرة", "wife": "زوجة", "husband": "زوج", "son": "ابن", "daughter": "ابنة",
                 "father": "أب", "mother": "أم", "other": "أخرى"},
    "gender": {"m": "ذكر", "f": "أنثى"},
    "need_type": {"monthly": "إعانة شهرية", "food": "غذاء", "medical": "علاج / عملية", "education": "تعليم",
                  "housing": "سكن / ترميم", "debt": "سداد ديون", "marriage": "تجهيز زواج",
                  "project": "مشروع صغير", "other": "أخرى"},
    "frequency": {"once": "مرة واحدة", "monthly": "شهري"},
    "priority": {"urgent": "عاجل", "high": "مرتفع", "normal": "عادي"},
    "need_status": {"open": "مفتوح", "closed": "مغلق"},
    "funding_state": {"open": "غير ممول", "partial": "ممول جزئياً", "funded": "ممول بالكامل", "closed": "مغلق"},
    "sponsorship_status": {"active": "سارية", "paused": "متوقفة مؤقتاً", "ended": "منتهية"},
    "member_status": {"active": "عامل", "inactive": "غير عامل", "honorary": "شرفي"},
}


def F(name, label, type="text", required=False, choices=None, list=False, search=False):
    return dict(name=name, label=label, type=type, required=required,
                choices=choices, list=list, search=search)


# "perm" names the permission needed to open a section (see ROLE_PERMS in models.py).


ENTITIES = {
    "needs": dict(
        model=CaseNeed, title="احتياجات الحالات", singular="احتياج", icon="◎", perm="needs",
        order=CaseNeed.id.desc(), group="cases",
        fields=[
            F("beneficiary_id", "الحالة", "fk:beneficiaries", True, list=True),
            F("need_type", "نوع الاحتياج", "select", True, "need_type", list=True),
            F("description", "الوصف", required=True, list=True, search=True),
            F("amount_needed", "المبلغ المطلوب (ج.م)", "money", True, list=True),
            F("frequency", "التكرار", "select", True, "frequency"),
            F("priority", "الأولوية", "select", True, "priority", list=True),
            F("funded_display", "المموَّل", "readonly", list=True),
            F("status", "الحالة", "select", True, "need_status", list=True),
            F("notes", "ملاحظات", "textarea"),
        ],
    ),
    "sponsorships": dict(
        model=Sponsorship, title="الكفالات", singular="كفالة", icon="⚭", perm="sponsorships",
        order=Sponsorship.id.desc(), group="cases",
        fields=[
            F("donor_id", "الكافل (المتبرع)", "fk:donors", True, list=True),
            F("beneficiary_id", "الحالة المكفولة", "fk:beneficiaries", True, list=True),
            F("need_id", "الاحتياج (اختياري)", "fk:needs"),
            F("monthly_amount", "المبلغ الشهري (ج.م)", "money", True, list=True),
            F("start_date", "تاريخ البداية", "date", True, list=True),
            F("end_date", "تاريخ النهاية (اختياري)", "date"),
            F("status", "الحالة", "select", True, "sponsorship_status", list=True),
            F("paid_display", "المدفوع حتى الآن", "readonly", list=True),
            F("arrears_display", "المتأخرات", "readonly", list=True),
            F("notes", "ملاحظات", "textarea"),
        ],
    ),
    "donors": dict(
        model=Donor, title="المتبرعون", singular="متبرع", icon="♥", perm="donors",
        order=Donor.name,
        fields=[
            F("name", "الاسم", required=True, list=True, search=True),
            F("donor_type", "النوع", "select", True, "donor_type", list=True),
            F("phone", "الهاتف", "phone", list=True, search=True),
            F("email", "البريد الإلكتروني", "email", search=True),
            F("address", "العنوان"),
            F("notes", "ملاحظات", "textarea"),
        ],
    ),
    "donations": dict(
        model=Donation, title="التبرعات", singular="تبرع", icon="₤", perm="donations",
        order=Donation.donation_date.desc(),
        fields=[
            F("receipt_no", "رقم الإيصال", "readonly", list=True, search=True),
            F("donor_id", "المتبرع", "fk:donors", True, list=True),
            F("amount", "المبلغ (ج.م)", "money", True, list=True),
            F("method", "طريقة الدفع", "select", True, "method", list=True),
            F("purpose", "الغرض", "select", True, "purpose", list=True),
            F("donation_date", "التاريخ", "date", True, list=True),
            F("beneficiary_id", "مخصص لحالة (اختياري)", "fk:beneficiaries"),
            F("need_id", "مخصص لاحتياج (اختياري)", "fk:needs"),
            F("sponsorship_id", "دفعة كفالة (اختياري)", "fk:sponsorships"),
            F("notes", "ملاحظات", "textarea"),
        ],
    ),
    "beneficiaries": dict(
        model=Beneficiary, title="المستفيدون / الحالات", singular="حالة", icon="⌂", perm="beneficiaries",
        order=Beneficiary.name,
        fields=[
            F("name", "الاسم", required=True, list=True, search=True),
            F("national_id", "الرقم القومي", "nid", list=True, search=True),
            F("phone", "الهاتف", "phone", search=True),
            F("area", "المنطقة", list=True, search=True),
            F("address", "العنوان"),
            F("category", "الفئة", "select", True, "category", list=True),
            F("family_size", "عدد أفراد الأسرة", "int"),
            F("monthly_income", "الدخل الشهري (ج.م)", "money"),
            F("status", "حالة الملف", "select", True, "beneficiary_status", list=True),
            F("notes", "ملاحظات البحث الاجتماعي", "textarea"),
        ],
    ),
    "aids": dict(
        model=Aid, title="المساعدات المصروفة", singular="مساعدة", icon="✚", perm="aids",
        order=Aid.aid_date.desc(),
        fields=[
            F("beneficiary_id", "المستفيد", "fk:beneficiaries", True, list=True),
            F("aid_type", "نوع المساعدة", "select", True, "aid_type", list=True),
            F("value", "القيمة (ج.م)", "money", True, list=True),
            F("aid_date", "التاريخ", "date", True, list=True),
            F("description", "الوصف", search=True, list=True),
        ],
    ),
    "volunteers": dict(
        model=Volunteer, title="المتطوعون", singular="متطوع", icon="☺", perm="volunteers",
        order=Volunteer.name,
        fields=[
            F("name", "الاسم", required=True, list=True, search=True),
            F("phone", "الهاتف", "phone", list=True, search=True),
            F("email", "البريد الإلكتروني", "email"),
            F("skills", "المهارات", list=True, search=True),
            F("availability", "أوقات التفرغ"),
            F("join_date", "تاريخ الانضمام", "date"),
            F("status", "الحالة", "select", True, "volunteer_status", list=True),
            F("notes", "ملاحظات", "textarea"),
        ],
    ),
    "members": dict(
        model=Member, title="أعضاء الجمعية العمومية", singular="عضو", icon="★", perm="members",
        order=Member.membership_no,
        fields=[
            F("membership_no", "رقم العضوية", required=True, list=True, search=True),
            F("name", "الاسم", required=True, list=True, search=True),
            F("national_id", "الرقم القومي", "nid", search=True),
            F("phone", "الهاتف", "phone", list=True),
            F("join_date", "تاريخ الانضمام", "date"),
            F("paid_until_year", "الاشتراك مسدد حتى سنة", "year", list=True),
            F("status", "نوع العضوية", "select", True, "member_status", list=True),
            F("notes", "ملاحظات", "textarea"),
        ],
    ),
}
