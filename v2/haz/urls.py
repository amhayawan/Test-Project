from django.contrib import admin
from django.urls import path
from django.utils.translation import gettext_lazy as _

from accounts import views as account_views
from approvals import views as approval_views
from core import views as core_views
from dashboards import views as dashboard_views
from hr import views as hr_views

admin.site.site_header = _("HAZ integrated management system")
admin.site.site_title = _("HAZ system")
admin.site.index_title = _("Back office")

urlpatterns = [
    path("", dashboard_views.dashboard, name="dashboard"),
    path("access/", account_views.access_matrix, name="access_matrix"),
    path("login/", account_views.LoginView.as_view(), name="login"),
    path("logout/", account_views.LogoutView.as_view(), name="logout"),
    path("language/", account_views.set_language, name="set_language"),
    path("approvals/", approval_views.inbox_view, name="approvals_inbox"),
    path("approvals/<int:pk>/", approval_views.request_view, name="approval_request"),
    path("attachments/<int:pk>/", core_views.attachment_download, name="attachment_download"),
    path("hr/structure/", hr_views.structure, name="hr_structure"),
    path("hr/payslips/<int:pk>/", hr_views.payslip, name="payslip"),
    path("hr/my-payslips/", hr_views.my_payslips, name="my_payslips"),
    path("hr/my-leave/", hr_views.my_leave, name="my_leave"),
    path("hr/my-leave/<int:pk>/cancel/", hr_views.cancel_leave, name="cancel_leave"),
    path("backoffice/", admin.site.urls),
]
