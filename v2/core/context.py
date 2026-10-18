from django.utils.translation import gettext_lazy as _

def modules():
    """Menu groups collected from each installed app's nav.py, in INSTALLED_APPS order."""
    from importlib import import_module
    from django.apps import apps
    found = []
    for cfg in apps.get_app_configs():
        try:
            nav = import_module(f"{cfg.name}.nav")
        except ModuleNotFoundError:
            continue
        found.append((nav.GROUP, nav.ITEMS))
    return found


def navigation(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from approvals.services import inbox
    return {
        "nav_modules": [(label, url) for _group, items in modules() for label, url, perm in items
                        if user.has_perm(perm) and (user.is_staff or not url.startswith("/backoffice/"))],
        "nav_groups": [(group, links, any(request.path.startswith(u) for _l, u in links))
                       for group, items in modules()
                       if (links := [(label, url) for label, url, perm in items if user.has_perm(perm)
                                     and (user.is_staff or not url.startswith("/backoffice/"))])],
        "has_employee_record": hasattr(user, "employee"),
        "approvals_waiting": len(inbox(user)),
    }
