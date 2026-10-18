from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import translation

from core.audit import log_event

from .models import Beneficiary, CaseNeed, FamilyMember, HouseholdItem


@login_required
def research_form(request, pk=None):
    """The association's field research form, filled from the case (or blank to print for a visit). Always Arabic."""
    case = None
    if pk is not None:
        case = get_object_or_404(Beneficiary.objects.visible_to(request.user), pk=pk)
        log_event("research_form_print", case)
    elif not request.user.has_perm("cases.add_beneficiary"):
        raise Http404
    items = list(case.household.all()) if case else [HouseholdItem(item=c, kind=k) for c, k, _l in HouseholdItem.ITEMS]
    family = list(case.family.all()) if case else []
    with translation.override("ar"):
        return render(request, "cases/research_form.html", {
            "c": case, "family": family + [FamilyMember()] * max(0, 8 - len(family)),
            "medical": (list(case.medical.all()) if case else []) + [None] * 3,
            "appliances": [i for i in items if i.kind == HouseholdItem.APPLIANCE],
            "furniture": [i for i in items if i.kind == HouseholdItem.FURNITURE]})


@login_required
@permission_required("cases.view_case_summary", raise_exception=True)
def available(request):
    """Approved cases by code only, with what is still needed: for fundraising and donors. No personal details."""
    q = (request.GET.get("q") or "").strip()
    cases = (Beneficiary.objects.filter(status=Beneficiary.APPROVED)
             .prefetch_related(Prefetch("needs", queryset=CaseNeed.objects.filter(is_open=True)))
             .order_by("case_no"))
    if q:
        cases = cases.filter(case_no__icontains=q)
    category = request.GET.get("category")
    if category:
        cases = cases.filter(category=category)
    rows = []
    for c in cases:
        needs = [{"need": n, "state": n.funding_state, "label": n.funding_label,
                  "remaining": max(n.amount_needed - n.funded, 0)} for n in c.needs.all()]
        if needs:
            rows.append({"case": c, "needs": needs})
    return render(request, "cases/available.html", {"rows": rows, "q": q, "category": category,
                                                    "categories": Beneficiary.CATEGORIES})
