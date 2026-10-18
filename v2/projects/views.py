from django.contrib.auth.decorators import login_required, permission_required
from django.http import Http404
from django.shortcuts import render

from dashboards import filters as flt

from .services import summary, visible_projects

PERM = "projects.view_projectprofile"


@login_required
@permission_required(PERM, raise_exception=True)
def project_list(request):
    projects = visible_projects(request.user).select_related("department", "manager")
    return render(request, "projects/list.html", {"rows": [summary(p) for p in projects]})


@login_required
@permission_required(PERM, raise_exception=True)
def project_detail(request, pk):
    project = visible_projects(request.user).select_related("department", "manager", "fund").filter(pk=pk).first()
    if project is None:
        raise Http404
    f = flt.parse(request.GET) if request.GET.get("period") else None
    data = summary(project, f.start if f else None, f.end if f else None, detail=True)
    return render(request, "projects/detail.html", {"d": data, "f": f, "presets": flt.PRESETS})
