"""Server-side SVG bar charts (no JavaScript library, works offline, passes the strict CSP).

Geometry is computed here because templates can't do arithmetic. Each bar carries a <title>
so hovering shows its exact value; every chart also has a table view in the template.
"""
import math
from decimal import Decimal

W, H = 760, 260
PAD_L, PAD_R, PAD_T, PAD_B = 64, 12, 12, 34


def _nice_max(value):
    if value <= 0:
        return Decimal(1)
    exp = 10 ** math.floor(math.log10(float(value)))
    for m in (1, 2, 2.5, 5, 10):
        if m * exp >= float(value):
            return Decimal(str(m * exp))
    return Decimal(str(10 * exp))


def _short(v):
    v = float(v)
    for div, suffix in ((1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"{v / div:.1f}".rstrip("0").rstrip(".") + suffix
    return f"{v:.0f}"


def grouped_bars(rows, series):
    """rows: [{"label": str, "values": [Decimal per series]}] -> drawing instructions."""
    n_series = len(series)
    top = _nice_max(max([v for r in rows for v in r["values"]] + [Decimal(0)]))
    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    slot = plot_w / max(len(rows), 1)
    gap = 2                                        # surface gap between adjacent bars
    group_w = slot * 0.72
    bar_w = max((group_w - gap * (n_series - 1)) / n_series, 1.5)
    label_every = max(1, math.ceil(len(rows) / 12))
    bars, labels = [], []
    for i, row in enumerate(rows):
        x0 = PAD_L + i * slot + (slot - group_w) / 2
        for j, value in enumerate(row["values"]):
            h = float(value / top) * plot_h if top else 0
            bars.append({"x": round(x0 + j * (bar_w + gap), 1), "y": round(PAD_T + plot_h - h, 1),
                         "w": round(bar_w, 1), "h": round(max(h, 0), 1), "series": j + 1,
                         "title": f"{row['label']} — {series[j]}: {value:,.0f}"})
        if i % label_every == 0:
            labels.append({"x": round(PAD_L + i * slot + slot / 2, 1), "text": row["label"]})
    ticks = [{"y": round(PAD_T + plot_h - plot_h * k / 4, 1), "text": _short(top * k / 4)} for k in range(5)]
    return {"w": W, "h": H, "bars": bars, "labels": labels, "ticks": ticks, "series": list(enumerate(series, 1)),
            "x0": PAD_L, "x1": W - PAD_R, "base_y": PAD_T + plot_h, "label_y": H - 10, "rows": rows}
