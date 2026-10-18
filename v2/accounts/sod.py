"""Segregation of duties: role combinations one person should not hold.

The approval engine already stops anyone approving their own request. These rules flag the
wider risk of one person controlling two steps that are meant to check each other.
Edit the list to match the association's internal-control policy.
"""
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from .roles import role_label

CONFLICTS = [
    ("researcher", "case_manager", _("Researches cases and also accepts them")),
    ("fundraising", "case_manager", _("Records donations and also decides who receives them")),
    ("admin", "case_manager", _("Controls user permissions and also approves cases and aid")),
    ("admin", "fundraising", _("Controls user permissions and also records donations")),
    ("admin", "executive", _("Controls user permissions and also gives final approvals")),
]


def conflicts():
    """Active users holding a conflicting pair of roles, or permissions given outside any role."""
    found = []
    User = get_user_model()
    for user in User.objects.filter(is_active=True).prefetch_related("groups"):
        held = {g.name for g in user.groups.all()}
        for a, b, why in CONFLICTS:
            if a in held and b in held:
                found.append({"user": user, "roles": f"{role_label(a)} + {role_label(b)}", "why": why})
        if user.user_permissions.exists():
            found.append({"user": user, "roles": _("Individual permissions"),
                          "why": _("Has permissions given directly instead of through a role")})
        if user.is_superuser and held - {"admin"}:
            found.append({"user": user, "roles": _("Superuser"),
                          "why": _("Superusers bypass every permission check; keep them for emergencies only")})
    return found
