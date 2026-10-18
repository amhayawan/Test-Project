"""How supply-chain events are booked in finance (registered with finance.posting in apps.ready).

* goods receipt (stock items):  Dr stock — Cr goods received not invoiced (purchase) / in-kind donations
* supplier invoice:             Dr goods received not invoiced (stock, at order price; a lower invoice price
                                reduces stock) / expense (services) / fixed asset — Cr suppliers payable
* stock issue:                  Dr aid expense (case) or programme expense (project / department) — Cr stock
"""
from django.utils.translation import gettext as _

from finance.builders import default_fund
from finance.models import mapped

from .models import ZERO, Item, money


def _stock_account(item):
    return item.category.inventory_account or mapped("supply.inventory")


def _expense_account(item):
    return item.category.expense_account or mapped("supply.expense")


def receipt(r, **_extra):
    stock_lines = [l for l in r.lines.select_related("item__category") if l.item.kind == Item.STOCK]
    if not stock_lines:
        return None
    if r.purchase_order_id:
        req = r.purchase_order.request
        fund, project = req.fund or default_fund(), req.project
        credit = mapped("supply.received_not_invoiced")
        description = _("Goods received %(no)s — order %(po)s") % {"no": r.receipt_no, "po": r.purchase_order.order_no}
    else:
        d = r.donation
        fund = d.fund or default_fund(d.purpose in ("zakat", "zakat_fitr"))
        project = d.campaign.project if d.campaign_id and d.campaign.project_id else None
        credit = mapped("income.in_kind")
        description = _("In-kind donation received %(no)s — receipt %(rec)s") % {"no": r.receipt_no,
                                                                                "rec": d.receipt_no}
    lines, total = [], ZERO
    for l in stock_lines:
        value = money(l.qty * l.unit_cost)
        total += value
        lines.append({"account": _stock_account(l.item), "debit": value, "fund": fund, "project": project,
                      "memo": f"{r.receipt_no} {l.item.code}"})
    lines.append({"account": credit, "credit": total, "fund": fund, "project": project, "memo": r.receipt_no})
    return {"date": r.date, "source": "purchase" if r.purchase_order_id else "stock", "description": description,
            "lines": lines}


def invoice(inv, **_extra):
    po = inv.purchase_order
    req = po.request
    fund = req.fund or default_fund()
    ordered = po.ordered()
    lines, total = [], ZERO
    for l in inv.lines.select_related("item__category", "item__asset_category"):
        amount = money(l.qty * l.unit_price)
        total += amount
        memo = f"{inv.invoice_no} {l.item.code}"
        if l.item.kind == Item.STOCK:
            at_order = money(l.qty * ordered[l.item_id][1])
            lines.append({"account": mapped("supply.received_not_invoiced"), "debit": at_order, "fund": fund,
                          "project": req.project, "memo": memo})
            if at_order != amount:
                lines.append({"account": _stock_account(l.item), "credit": at_order - amount, "fund": fund,
                              "project": req.project, "memo": memo})
        elif l.item.kind == Item.ASSET:
            lines.append({"account": l.item.asset_category.asset_account, "debit": amount, "fund": fund,
                          "project": req.project, "department": req.department, "memo": memo})
        else:
            lines.append({"account": _expense_account(l.item), "debit": amount, "fund": fund,
                          "project": req.project, "department": req.department, "memo": memo})
    lines.append({"account": mapped("supply.payable"), "credit": total, "fund": fund, "memo": inv.invoice_no})
    return {"date": inv.date, "source": "purchase", "lines": lines,
            "description": _("Supplier invoice %(no)s — %(sup)s (%(ref)s)")
            % {"no": inv.invoice_no, "sup": po.supplier.name, "ref": inv.supplier_ref}}


def issue(s, **_extra):
    aid = s.aid if s.aid_id else None
    fund = (aid.fund if aid and aid.fund_id else s.fund) or default_fund()
    project = aid.project if aid else s.project
    department = None if aid else s.department
    lines, credits, total = [], {}, ZERO
    for l in s.lines.select_related("item__category"):
        if not l.value:
            continue
        total += l.value
        account = mapped(f"aid.expense.{aid.aid_type}", "aid.expense") if aid else _expense_account(l.item)
        lines.append({"account": account, "debit": l.value, "fund": fund, "project": project,
                      "department": department, "memo": f"{s.issue_no} {l.item.code}"})
        stock = _stock_account(l.item)
        credits[stock] = credits.get(stock, ZERO) + l.value
    if not total:
        return None
    for account, amount in credits.items():
        lines.append({"account": account, "credit": amount, "fund": fund, "memo": s.issue_no})
    if aid:
        description = _("Goods issued %(no)s — aid %(aid)s") % {"no": s.issue_no, "aid": aid.aid_no}
    else:
        description = _("Goods issued %(no)s — %(to)s") % {"no": s.issue_no, "to": project or department}
    return {"date": s.date, "source": "stock", "description": description, "lines": lines}
