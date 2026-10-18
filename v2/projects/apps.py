from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ProjectsConfig(AppConfig):
    name = "projects"
    verbose_name = _("Project management")

    def ready(self):
        from approvals.registry import register
        from core.audit import track
        from . import models as m
        register("projects.budget", _("Project budget"))
        for model in (m.ProjectProfile, m.BudgetLine, m.Milestone, m.Task):
            track(model)
