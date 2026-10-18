"""Monthly straight-line depreciation.

Policy used (change here if the accountant's policy differs): an asset is depreciated from the
month after it is put in use, by (cost − value at end of life) ÷ useful life each month, until fully
depreciated or disposed. The run creates a journal that goes through normal approval.
"""
from datetime import date, timedelta
from django.db.models import Sum

from django.db import transaction
from django.utils.translation import gettext as _

from . import posting
from .models import ZERO, DepreciationLine, DepreciationRun, FinanceError, FixedAsset, JournalEntry, money


def month_end(year, month):
    return date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)


@transaction.atomic
def calculate(run, user):
    run = DepreciationRun.objects.select_for_update().get(pk=run.pk)
    if run.entry_id and run.entry.status in (JournalEntry.PENDING, JournalEntry.POSTED):
        raise FinanceError(_("This depreciation is awaiting approval or already posted."))
    start, end = date(run.year, run.month, 1), month_end(run.year, run.month)
    old_entry = run.entry
    run.lines.all().delete()
    run.end = end
    run.entry = None
    run.save()
    if old_entry:
        old_entry.lines.all().delete()
        old_entry.delete()
    lines, total = [], ZERO
    for asset in FixedAsset.objects.filter(acquired_on__lt=start).select_related("category"):
        if asset.disposed_on and asset.disposed_on < start:
            continue
        depreciable = asset.cost - asset.salvage_value
        done = asset.depreciation_lines.filter(run__entry__status=JournalEntry.POSTED).exclude(run=run) \
            .aggregate(s=Sum("amount"))["s"] or ZERO
        amount = min(money(depreciable / asset.life), depreciable - done)
        if amount <= 0:
            continue
        DepreciationLine.objects.create(run=run, asset=asset, amount=amount)
        total += amount
        cat = asset.category
        lines += [{"account": cat.expense_account, "debit": amount, "fund": asset.fund, "project": asset.project,
                   "department": asset.department, "memo": asset.asset_no},
                  {"account": cat.accumulated_account, "credit": amount, "fund": asset.fund, "memo": asset.asset_no}]
    if lines:
        run.entry = posting._create(end, _("Depreciation %(m)s") % {"m": run}, "depreciation",
                                    posting._clean(lines), user=user)
    run.total = total
    run.save()
    return run
