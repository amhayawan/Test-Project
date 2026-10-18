"""Finance: automatic postings from other modules, maker-checker journals, statements that balance."""
from datetime import date
from decimal import Decimal

import pytest
from django.db.models import Sum
from django.test import Client

from approvals import services
from cases.models import Aid, Beneficiary
from core.models import Fund, Project
from crm.models import Campaign, Donation, Donor
from finance import assets, posting, reports
from finance.models import (Account, AccountMapping, AssetCategory, DepreciationRun, FinanceError, FiscalYear,
                            FixedAsset, JournalEntry, JournalLine, Payment, PostingIssue)
from hr import payroll
from hr.models import Assignment, PayrollRun
from test_hr import hire, org, sample_rules  # noqa: F401

pytestmark = pytest.mark.django_db
D = Decimal


def acc(code):
    return Account.objects.get(code=code)


def balance(code, **kw):
    return reports.balance_of([acc(code)], kw.get("as_of"))


@pytest.fixture
def fin(org, make_user):
    org.update(fm=make_user("fm", "finance_manager"), accountant=make_user("acct", "accountant"),
               fundraiser=make_user("fr", "fundraising"), cm=make_user("cm", "case_manager"))
    org["donor"] = Donor.objects.create(name="متبرع", phone="01000000000")
    return org


def approved_case():
    return Beneficiary.objects.create(name="حالة", status=Beneficiary.APPROVED, zakat_eligible="yes")


def test_donation_is_booked_and_follows_corrections(fin):
    d = Donation.objects.create(donor=fin["donor"], amount=D(1000), method="bank", purpose="zakat",
                                fund=Fund.objects.get(code="ZAK"), donation_date=date(2026, 3, 1))
    entry = posting.live_entry(d, "donation.received")
    assert entry.status == JournalEntry.POSTED and entry.totals() == (D(1000), D(1000))
    assert balance("1102") == D(1000) and balance("4102") == D(-1000)
    assert set(entry.lines.values_list("fund__code", flat=True)) == {"ZAK"}

    d.amount = D(1200)                         # correction: old entry reversed, new one posted
    d.save()
    assert balance("1102") == D(1200)
    assert JournalEntry.objects.filter(source="reversal").count() == 1
    d.delete()
    assert balance("1102") == 0 and balance("4102") == 0

    Donation.objects.create(donor=fin["donor"], amount=D(500), method="in_kind", donation_date=date(2026, 3, 1))
    assert balance("4107") == 0                # goods: booked by the goods receipt, not here


def test_campaign_project_reaches_income_line(fin):
    project = Project.objects.create(code="RMD", name_ar="رمضان", department=fin["prog"])
    camp = Campaign.objects.create(code="R26", name="رمضان 2026", start_date=date(2026, 3, 1), project=project)
    d = Donation.objects.create(donor=fin["donor"], amount=D(300), method="cash", campaign=camp,
                                donation_date=date(2026, 3, 2))
    line = posting.live_entry(d, "donation.received").lines.get(credit__gt=0)
    assert line.project == project and line.fund.code == "GEN"


def test_problems_are_queued_not_blocking_and_can_be_retried(fin):
    AccountMapping.objects.filter(key="cash.cash").delete()
    d = Donation.objects.create(donor=fin["donor"], amount=D(100), method="cash", donation_date=date(2026, 3, 1))
    assert Donation.objects.filter(pk=d.pk).exists()           # fundraising was not blocked
    issue = PostingIssue.objects.get(resolved_at__isnull=True)
    assert "cash.cash" in issue.message
    AccountMapping.objects.create(key="cash.cash", account=acc("1101"))
    assert posting.retry(issue) is True
    assert balance("1101") == D(100)

    FiscalYear.objects.filter(year=2026).update(locked_through=date(2026, 3, 31))
    Donation.objects.create(donor=fin["donor"], amount=D(50), method="cash", donation_date=date(2026, 3, 15))
    assert "locked" in PostingIssue.objects.get(resolved_at__isnull=True).message


def test_aid_delivery_books_expense_except_goods(fin):
    case = approved_case()
    cash_aid = Aid.objects.create(beneficiary=case, aid_type="medical", value=D(700), paid_by="cash",
                                  status=Aid.APPROVED)     # approval itself is tested with the cases module
    cash_aid.mark_delivered(date(2026, 3, 5))
    assert balance("5103") == D(700) and balance("1101") == D(-700)
    goods = Aid.objects.create(beneficiary=case, aid_type="food", value=D(400), paid_by="stock",
                               status=Aid.APPROVED)
    goods.mark_delivered(date(2026, 3, 5))
    assert balance("5102") == 0


def test_payroll_accrual_by_cost_centre_and_payment(fin):
    sample_rules()
    project_fund = Fund.objects.create(code="PRJ", name_ar="منحة", kind=Fund.RESTRICTED)
    fin["project"].fund = project_fund
    fin["project"].save()
    emp = hire(fin)
    Assignment.objects.create(employee=emp, department=fin["prog"], project=fin["project"], percent=D(60),
                              start_date=date(2026, 1, 1))
    run = payroll.calculate(PayrollRun.objects.create(year=2026, month=3), fin["payroll"])
    req = services.submit(run, fin["payroll"])
    services.decide(req, fin["hr_manager"], "approve")
    services.decide(req, fin["executive"], "approve")
    entry = posting.live_entry(run, "payroll.approved")
    assert entry.date == date(2026, 3, 31) and entry.totals()[0] == entry.totals()[1]
    slip = run.payslips.get()
    assert balance("5201") + balance("5202") == slip.employer_cost
    assert balance("2110") == -slip.net and balance("2111") == -slip.income_tax
    on_project = JournalLine.objects.filter(entry=entry, project=fin["project"]).aggregate(s=Sum("debit"))["s"]
    assert on_project == D("7125.00")   # 60% of 10,000 + 1,875 employer insurance and entry.lines.filter(project=fin["project"]).first().fund == project_fund
    run.refresh_from_db()
    run.mark_paid(date(2026, 4, 2))
    assert balance("2110") == 0 and balance("1102") == -slip.net


def test_manual_journal_maker_checker_and_reversal(fin):
    e = JournalEntry.objects.create(date=date(2026, 3, 10), description="Rent March", created_by=fin["accountant"])
    JournalLine.objects.create(entry=e, account=acc("5301"), debit=D(5000), department=fin["admin"])
    JournalLine.objects.create(entry=e, account=acc("1102"), credit=D(4000))
    with pytest.raises(Exception):
        services.submit(e, fin["accountant"])            # does not balance
    JournalLine.objects.filter(entry=e, credit__gt=0).update(credit=D(5000))
    req = services.submit(e, fin["accountant"])
    assert not services.can_act(req, fin["accountant"])
    services.decide(req, fin["fm"], "approve")
    e.refresh_from_db()
    assert e.status == JournalEntry.POSTED and balance("5301") == D(5000)
    with pytest.raises(FinanceError):
        e.lines.first().delete()                          # posted entries are final
    rev = posting.reverse(e, fin["accountant"], post=False)
    services.decide(services.submit(rev, fin["accountant"]), fin["fm"], "approve")
    assert balance("5301") == 0


def test_payment_voucher(fin):
    p = Payment.objects.create(payee="مالك العقار", amount=D(8000), method="bank", debit_account=acc("5301"),
                               description="إيجار", prepared_by=fin["accountant"], date=date(2026, 3, 1))
    req = services.submit(p, fin["accountant"])
    services.decide(req, fin["fm"], "approve")
    p.refresh_from_db()
    with pytest.raises(FinanceError):
        Payment.objects.create(payee="x", amount=D(1), debit_account=acc("5301"), description="x").mark_paid()
    p.mark_paid()
    assert balance("5301") == D(8000) and balance("1102") == D(-8000)


def test_statements_balance(fin):
    Donation.objects.create(donor=fin["donor"], amount=D(10000), method="bank", donation_date=date(2026, 2, 1))
    Donation.objects.create(donor=fin["donor"], amount=D(3000), method="cash", purpose="zakat",
                            fund=Fund.objects.get(code="ZAK"), donation_date=date(2026, 2, 1))
    case = approved_case()
    a = Aid.objects.create(beneficiary=case, aid_type="cash", value=D(2000), fund=Fund.objects.get(code="ZAK"),
                           status=Aid.APPROVED)
    a.mark_delivered(date(2026, 2, 3))
    rows, t = reports.trial_balance(date(2026, 1, 1), date(2026, 12, 31))
    assert t["d"] == t["c"] == D(15000) and t["cd"] == t["cc"]
    inc = reports.income_statement(date(2026, 1, 1), date(2026, 12, 31))
    assert inc["surplus"]["zakat"] == D(1000) and inc["surplus"]["unrestricted"] == D(10000)
    bs = reports.balance_sheet(date(2026, 12, 31))
    assert bs["check"] == 0 and bs["assets_total"]["total"] == D(11000)
    funds = {r["fund"].code: r["closing"] for r in reports.fund_balances(date(2026, 1, 1), date(2026, 12, 31)) if r["fund"]}
    assert funds["ZAK"] == D(1000) and funds["GEN"] == D(10000)

    c = Client()
    c.force_login(fin["fm"])
    for url in ("/finance/", "/finance/trial-balance/?period=this_year", "/finance/income-statement/",
                "/finance/balance-sheet/", "/finance/funds/", f"/finance/ledger/?account={acc('1102').pk}", "/"):
        assert c.get(url).status_code == 200, url
    c.force_login(fin["hr_officer"])
    assert c.get("/finance/trial-balance/").status_code == 403


def test_depreciation_goes_through_approval(fin):
    cat = AssetCategory.objects.get(code="IT")
    asset = FixedAsset.objects.create(name="لابتوب", category=cat, acquired_on=date(2026, 1, 10), cost=D(36000),
                                      department=fin["admin"])
    run = assets.calculate(DepreciationRun.objects.create(year=2026, month=2, end=date(2026, 2, 28)), fin["accountant"])
    assert run.total == D(1000) and run.entry.status == JournalEntry.DRAFT
    assert asset.book_value(date(2026, 2, 28)) == D(36000)          # not posted yet
    services.decide(services.submit(run.entry, fin["accountant"]), fin["fm"], "approve")
    assert asset.book_value(date(2026, 2, 28)) == D(35000)
    assert balance("5401") == D(1000) and balance("1294") == D(-1000)
    with pytest.raises(FinanceError):
        assets.calculate(run, fin["accountant"])
