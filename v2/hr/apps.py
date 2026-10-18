from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class HrConfig(AppConfig):
    name = "hr"
    verbose_name = _("Human resources")

    def ready(self):
        from core.audit import track
        from . import models as m
        for model in (m.Grade, m.Position, m.Employee, m.Contract, m.Assignment, m.PayComponent,
                      m.EmployeePayItem, m.Incentive, m.PayrollRun, m.Appraisal, m.TaxBracket, m.InsuranceRule,
                      m.LeaveType, m.LeaveEntitlement, m.PublicHoliday, m.LeaveAdjustment, m.LeaveRequest):
            track(model)
