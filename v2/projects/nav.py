"""Menu entries for this module: (label, url, permission needed)."""
from django.utils.translation import gettext_lazy as _

GROUP = _("Project management")
ITEMS = [
    (_("Projects overview"), "/projects/", "projects.view_projectprofile"),
    (_("Project budgets"), "/backoffice/projects/projectprofile/", "projects.view_projectprofile"),
    (_("Milestones"), "/backoffice/projects/milestone/", "projects.view_milestone"),
    (_("Tasks"), "/backoffice/projects/task/", "projects.view_task"),
]
