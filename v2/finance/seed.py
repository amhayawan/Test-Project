"""STARTER chart of accounts for an Egyptian charity, posting rules, and approval limits.

This is a template to start testing with, not the association's approved chart: the accountant
reviews and edits it (codes, names, structure) before real use. Nothing here overwrites edits:
records are only created if missing.
"""
from decimal import Decimal

from core.seeding import policy

# (code, Arabic, English, type, parent code or None, entries allowed, contra)
CHART = [
    ("1", "الأصول", "Assets", "asset", None, False, False),
    ("11", "الأصول المتداولة", "Current assets", "asset", "1", False, False),
    ("1101", "الخزينة (نقدية)", "Cash on hand", "asset", "11", True, False),
    ("1102", "البنك – الحساب الجاري", "Bank – current account", "asset", "11", True, False),
    ("1103", "المحافظ الإلكترونية وإنستاباي", "Mobile wallets and InstaPay", "asset", "11", True, False),
    ("1104", "شيكات تحت التحصيل", "Cheques under collection", "asset", "11", True, False),
    ("1110", "سلف وقروض العاملين", "Staff advances and loans", "asset", "11", True, False),
    ("1120", "مخزون مواد الإغاثة والمساعدات", "Inventory – relief goods", "asset", "11", True, False),
    ("1121", "مخزون المهمات والأدوات المكتبية", "Inventory – supplies", "asset", "11", True, False),
    ("1130", "مصروفات مدفوعة مقدماً", "Prepaid expenses", "asset", "11", True, False),
    ("12", "الأصول الثابتة", "Fixed assets", "asset", "1", False, False),
    ("1201", "المباني", "Buildings", "asset", "12", True, False),
    ("1202", "السيارات", "Vehicles", "asset", "12", True, False),
    ("1203", "الأثاث والتجهيزات", "Furniture and equipment", "asset", "12", True, False),
    ("1204", "أجهزة الحاسب الآلي", "Computers", "asset", "12", True, False),
    ("1291", "مجمع إهلاك المباني", "Accumulated depreciation – buildings", "asset", "12", True, True),
    ("1292", "مجمع إهلاك السيارات", "Accumulated depreciation – vehicles", "asset", "12", True, True),
    ("1293", "مجمع إهلاك الأثاث والتجهيزات", "Accumulated depreciation – furniture", "asset", "12", True, True),
    ("1294", "مجمع إهلاك الحاسب الآلي", "Accumulated depreciation – computers", "asset", "12", True, True),
    ("2", "الالتزامات", "Liabilities", "liability", None, False, False),
    ("2101", "الموردون", "Suppliers payable", "liability", "2", True, False),
    ("2102", "بضاعة مستلمة لم ترد فاتورتها", "Goods received not yet invoiced", "liability", "2", True, False),
    ("2110", "صافي رواتب مستحقة", "Net salaries payable", "liability", "2", True, False),
    ("2111", "ضريبة كسب العمل المستحقة", "Salary income tax payable", "liability", "2", True, False),
    ("2112", "التأمينات الاجتماعية المستحقة", "Social insurance payable", "liability", "2", True, False),
    ("2120", "مصروفات مستحقة", "Accrued expenses", "liability", "2", True, False),
    ("3", "صافي الأصول (الأرصدة الصندوقية)", "Net assets (fund balances)", "net_assets", None, False, False),
    ("3101", "رصيد الصندوق العام (غير مقيد)", "Unrestricted fund balance", "net_assets", "3", True, False),
    ("3102", "أرصدة الأموال المقيدة", "Restricted funds balance", "net_assets", "3", True, False),
    ("3103", "رصيد صندوق الزكاة", "Zakat fund balance", "net_assets", "3", True, False),
    ("4", "الإيرادات", "Income", "income", None, False, False),
    ("41", "التبرعات", "Donations", "income", "4", False, False),
    ("4101", "تبرعات عامة", "General donations", "income", "41", True, False),
    ("4102", "زكاة المال", "Zakat al-mal", "income", "41", True, False),
    ("4103", "زكاة الفطر", "Zakat al-fitr", "income", "41", True, False),
    ("4104", "صدقات", "Sadaqa", "income", "41", True, False),
    ("4105", "تبرعات كفالة الأيتام", "Orphan sponsorship donations", "income", "41", True, False),
    ("4106", "تبرعات مخصصة (علاج، تعليم، إطعام، أضاحي)", "Earmarked donations (medical, education, food, udhiya)",
     "income", "41", True, False),
    ("4107", "تبرعات عينية", "In-kind donations", "income", "41", True, False),
    ("42", "إيرادات أخرى", "Other income", "income", "4", False, False),
    ("4201", "المنح", "Grants", "income", "42", True, False),
    ("4202", "اشتراكات الأعضاء", "Membership fees", "income", "42", True, False),
    ("4209", "إيرادات متنوعة", "Miscellaneous income", "income", "42", True, False),
    ("5", "المصروفات", "Expenses", "expense", None, False, False),
    ("51", "مصروفات البرامج والمساعدات", "Programme and aid expenses", "expense", "5", False, False),
    ("5101", "مساعدات نقدية", "Cash aid", "expense", "51", True, False),
    ("5102", "مساعدات غذائية", "Food aid", "expense", "51", True, False),
    ("5103", "مساعدات علاجية", "Medical aid", "expense", "51", True, False),
    ("5104", "مساعدات تعليمية", "Education aid", "expense", "51", True, False),
    ("5105", "مساعدات سكن وترميم", "Housing and repairs aid", "expense", "51", True, False),
    ("5106", "مساعدات ملابس", "Clothes aid", "expense", "51", True, False),
    ("5107", "مساعدات أخرى", "Other aid", "expense", "51", True, False),
    ("5108", "مستلزمات البرامج والمشروعات", "Programme and project supplies", "expense", "51", True, False),
    ("52", "الأجور وما في حكمها", "Staff costs", "expense", "5", False, False),
    ("5201", "الرواتب والأجور", "Salaries and wages", "expense", "52", True, False),
    ("5202", "حصة الجمعية في التأمينات الاجتماعية", "Employer social insurance", "expense", "52", True, False),
    ("53", "المصروفات الإدارية والعمومية", "Administrative expenses", "expense", "5", False, False),
    ("5301", "الإيجارات", "Rent", "expense", "53", True, False),
    ("5302", "المرافق (كهرباء ومياه)", "Utilities", "expense", "53", True, False),
    ("5303", "أدوات مكتبية ومطبوعات", "Office supplies and printing", "expense", "53", True, False),
    ("5304", "اتصالات وإنترنت", "Telephone and internet", "expense", "53", True, False),
    ("5305", "انتقالات", "Transport", "expense", "53", True, False),
    ("5306", "صيانة", "Maintenance", "expense", "53", True, False),
    ("5307", "مصروفات بنكية", "Bank charges", "expense", "53", True, False),
    ("5308", "أتعاب مهنية ومراجعة", "Professional and audit fees", "expense", "53", True, False),
    ("54", "الإهلاك", "Depreciation", "expense", "5", False, False),
    ("5401", "مصروف الإهلاك", "Depreciation expense", "expense", "54", True, False),
    ("55", "مصروفات جمع التبرعات", "Fundraising costs", "expense", "5", False, False),
    ("5501", "مصروفات حملات جمع التبرعات", "Fundraising campaign costs", "expense", "55", True, False),
]

MAPPINGS = [
    ("cash.cash", "1101", "Cash receipts and payments"),
    ("cash.bank", "1102", "Bank transfers, salary payments"),
    ("cash.instapay", "1103", "InstaPay donations"),
    ("cash.wallet", "1103", "Mobile wallet donations"),
    ("cash.check", "1104", "Cheques received / paid"),
    ("income.general", "4101", "General donations (and any purpose without its own rule)"),
    ("income.zakat", "4102", "Zakat al-mal"),
    ("income.zakat_fitr", "4103", "Zakat al-fitr"),
    ("income.sadaqa", "4104", "Sadaqa"),
    ("income.orphans", "4105", "Orphan sponsorship"),
    ("income.medical", "4106", "Earmarked: medical"),
    ("income.education", "4106", "Earmarked: education"),
    ("income.food", "4106", "Earmarked: food / Ramadan boxes"),
    ("income.udhiya", "4106", "Earmarked: udhiya"),
    ("income.in_kind", "4107", "In-kind donations received into the store"),
    ("aid.expense", "5107", "Aid of any type without its own rule"),
    ("aid.expense.cash", "5101", "Cash aid"),
    ("aid.expense.food", "5102", "Food aid"),
    ("aid.expense.medical", "5103", "Medical aid"),
    ("aid.expense.education", "5104", "Education aid"),
    ("aid.expense.housing", "5105", "Housing / repairs aid"),
    ("aid.expense.clothes", "5106", "Clothes aid"),
    ("payroll.salaries", "5201", "Gross salaries (by cost centre and project)"),
    ("payroll.employer_insurance", "5202", "Employer share of social insurance"),
    ("payroll.net_payable", "2110", "Net salaries until transferred"),
    ("payroll.tax_payable", "2111", "Salary income tax withheld"),
    ("payroll.insurance_payable", "2112", "Social insurance (employee + employer)"),
    ("payroll.deductions", "1110", "Loan / advance instalments deducted from salary"),
    ("payroll.penalties", "4209", "Penalty deductions"),
    ("supply.inventory", "1120", "Stock received into the store"),
    ("supply.received_not_invoiced", "2102", "Goods received, supplier invoice not yet recorded"),
    ("supply.payable", "2101", "Supplier invoices until paid"),
    ("supply.expense", "5108", "Non-stock purchases and goods issued to projects"),
]

# (code, Arabic, English, asset, accumulated, expense, default life in months) — the accountant sets the policy
ASSET_CATEGORIES = [
    ("BLD", "مبانٍ", "Buildings", "1201", "1291", "5401", 240),
    ("VEH", "سيارات", "Vehicles", "1202", "1292", "5401", 60),
    ("FUR", "أثاث وتجهيزات", "Furniture and equipment", "1203", "1293", "5401", 120),
    ("IT", "حاسب آلي", "Computers", "1204", "1294", "5401", 36),
]

# Approval limits are PLACEHOLDERS until the board sets them (Finance → Approval policies).
POLICIES = [
    ("finance.journal", Decimal(0), ["finance_manager"]),
    ("finance.journal", Decimal(100000), ["finance_manager", "executive"]),
    ("finance.payment", Decimal(0), ["finance_manager"]),
    ("finance.payment", Decimal(50000), ["finance_manager", "executive"]),
]


def run(stdout):
    from .models import Account, AccountMapping, AssetCategory, FiscalYear
    from django.utils import timezone
    by_code = {}
    for code, ar, en, kind, parent, postable, contra in CHART:
        acc, _ = Account.objects.get_or_create(code=code, defaults={
            "name_ar": ar, "name_en": en, "kind": kind, "parent": by_code.get(parent), "postable": postable,
            "contra": contra})
        by_code[code] = acc
    for key, code, desc in MAPPINGS:
        acc = by_code.get(code) or Account.objects.filter(code=code).first()
        if acc:
            AccountMapping.objects.get_or_create(key=key, defaults={"account": acc, "description": desc})
    for code, ar, en, a, acc_dep, exp, life in ASSET_CATEGORIES:
        if all(Account.objects.filter(code=c).exists() for c in (a, acc_dep, exp)):
            AssetCategory.objects.get_or_create(code=code, defaults={
                "name_ar": ar, "name_en": en, "asset_account": Account.objects.get(code=a),
                "accumulated_account": Account.objects.get(code=acc_dep), "expense_account": Account.objects.get(code=exp),
                "life_months": life})
    FiscalYear.objects.get_or_create(year=timezone.localdate().year)
    for doc_type, amount, roles in POLICIES:
        policy(doc_type, amount, roles)
