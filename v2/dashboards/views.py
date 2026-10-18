from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.models import Department, Fund, Project
from crm.models import Campaign

from . import filters as flt
from .charts import grouped_bars
from .widgets import build


@login_required
def dashboard(request):
    user = request.user
    f = flt.parse(request.GET)
    sections = build(user, f)
    if sections["overview"]:
        sections["overview"]["chart"] = grouped_bars(sections["overview"]["rows"], sections["overview"]["series"])
    if sections["fundraising"]:
        trend = sections["fundraising"]["trend"]
        sections["fundraising"]["chart"] = grouped_bars(trend["rows"], trend["series"])
    # Offer only the filters that affect something this role can see.
    options = {}
    if sections["fundraising"]:
        options["campaigns"] = Campaign.objects.order_by("-start_date")
    if sections["fundraising"] or sections["aid"]:
        options["funds"] = Fund.objects.filter(is_active=True)
    if sections["case_management"] or sections["overview"]:
        options["departments"] = Department.objects.filter(is_active=True)
        options["projects"] = Project.objects.exclude(status=Project.CLOSED)
    return render(request, "dashboards/dashboard.html", {
        "f": f, "s": sections, "presets": flt.PRESETS, "options": options,
    })
