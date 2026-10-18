"""Dashboard filters: a period (preset or custom range) plus optional dimensions.

Every number on the dashboard is computed against the same filters, so they always agree.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

PRESETS = [
    ("this_month", _("This month")),
    ("last_month", _("Last month")),
    ("last_30", _("Last 30 days")),
    ("last_90", _("Last 90 days")),
    ("this_quarter", _("This quarter")),
    ("this_year", _("This year")),
    ("last_year", _("Last year")),
    ("custom", _("Custom range")),
]
DEFAULT_PRESET = "this_year"


def _month_start(d):
    return d.replace(day=1)


def _add_months(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def preset_range(preset, today):
    if preset == "this_month":
        return _month_start(today), today
    if preset == "last_month":
        end = _month_start(today) - timedelta(days=1)
        return _month_start(end), end
    if preset == "last_30":
        return today - timedelta(days=29), today
    if preset == "last_90":
        return today - timedelta(days=89), today
    if preset == "this_quarter":
        return date(today.year, (today.month - 1) // 3 * 3 + 1, 1), today
    if preset == "last_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    return date(today.year, 1, 1), today            # this_year


@dataclass
class Filters:
    preset: str
    start: date
    end: date
    campaign: int | None = None
    fund: int | None = None
    department: int | None = None
    project: int | None = None
    errors: list = field(default_factory=list)

    @property
    def days(self):
        return (self.end - self.start).days + 1

    @property
    def previous(self):
        """The period of the same length just before this one (for % change)."""
        prev_end = self.start - timedelta(days=1)
        return prev_end - timedelta(days=self.days - 1), prev_end

    @property
    def granularity(self):
        if self.days <= 31:
            return "day"
        if self.days <= 120:
            return "week"
        return "month"

    def buckets(self):
        """(label, start, end) chunks covering the period, for trend charts."""
        out = []
        if self.granularity == "day":
            d = self.start
            while d <= self.end:
                out.append((d.strftime("%d/%m"), d, d))
                d += timedelta(days=1)
        elif self.granularity == "week":
            d = self.start
            while d <= self.end:
                e = min(d + timedelta(days=6), self.end)
                out.append((d.strftime("%d/%m"), d, e))
                d = e + timedelta(days=1)
        else:
            d = _month_start(self.start)
            while d <= self.end:
                e = min(_add_months(d, 1) - timedelta(days=1), self.end)
                out.append((d.strftime("%m/%Y"), max(d, self.start), e))
                d = _add_months(d, 1)
        return out

    def querystring(self, **override):
        from urllib.parse import urlencode
        params = {"period": self.preset}
        if self.preset == "custom":
            params.update({"from": self.start.isoformat(), "to": self.end.isoformat()})
        for name in ("campaign", "fund", "department", "project"):
            if getattr(self, name):
                params[name] = getattr(self, name)
        params.update(override)
        return urlencode(params)


def _int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse(params, today=None):
    today = today or timezone.localdate()
    preset = params.get("period") or DEFAULT_PRESET
    errors = []
    if preset not in dict(PRESETS):
        preset = DEFAULT_PRESET
    if preset == "custom":
        try:
            start = date.fromisoformat(params.get("from", ""))
            end = date.fromisoformat(params.get("to", ""))
            if end < start:
                start, end = end, start
            if (end - start).days > 3660:
                raise ValueError
        except ValueError:
            errors.append(_("Choose a valid custom date range (from and to)."))
            preset = DEFAULT_PRESET
            start, end = preset_range(preset, today)
    else:
        start, end = preset_range(preset, today)
    return Filters(preset=preset, start=start, end=end, campaign=_int(params.get("campaign")),
                   fund=_int(params.get("fund")), department=_int(params.get("department")),
                   project=_int(params.get("project")), errors=errors)
