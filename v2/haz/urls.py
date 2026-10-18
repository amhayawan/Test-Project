from django.contrib import admin
from django.urls import path
from django.utils.translation import gettext_lazy as _

from accounts import views as account_views
from approvals import views as approval_views
from core import views as core_views

admin.site.site_header = _("HAZ integrated management system")
admin.site.site_title = _("HAZ system")
admin.site.index_title = _("Back office")

urlpatterns = [
    path("", core_views.dashboard, name="dashboard"),
    path("login/", account_views.LoginView.as_view(), name="login"),
    path("logout/", account_views.LogoutView.as_view(), name="logout"),
    path("language/", account_views.set_language, name="set_language"),
    path("approvals/", approval_views.inbox_view, name="approvals_inbox"),
    path("approvals/<int:pk>/", approval_views.request_view, name="approval_request"),
    path("attachments/<int:pk>/", core_views.attachment_download, name="attachment_download"),
    path("backoffice/", admin.site.urls),
]
