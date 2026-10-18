from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Sum
from django.shortcuts import render

from .models import ZERO, Item, StockMove, Warehouse


def balances(warehouse=None):
    """Rows of item, store, quantity, average cost and value (only lines with stock or value)."""
    qs = StockMove.objects.values("item_id", "warehouse_id").annotate(q=Sum("qty"), v=Sum("value"))
    if warehouse:
        qs = qs.filter(warehouse_id=warehouse)
    items = {i.pk: i for i in Item.objects.select_related("category")}
    stores = {w.pk: w for w in Warehouse.objects.all()}
    rows = []
    for r in qs:
        q, v = r["q"] or ZERO, r["v"] or ZERO
        if not q and not v:
            continue
        item = items[r["item_id"]]
        rows.append({"item": item, "warehouse": stores[r["warehouse_id"]], "qty": q, "value": v,
                     "avg": (v / q) if q else ZERO, "low": q <= item.reorder_level})
    return sorted(rows, key=lambda r: (r["warehouse"].code, r["item"].code))


@login_required
@permission_required("supply.view_stockmove", raise_exception=True)
def stock(request):
    warehouse = request.GET.get("warehouse") or None
    rows = balances(int(warehouse) if warehouse and warehouse.isdigit() else None)
    return render(request, "supply/stock.html", {
        "rows": rows, "warehouses": Warehouse.objects.filter(is_active=True), "selected": warehouse,
        "total": sum((r["value"] for r in rows), ZERO)})
