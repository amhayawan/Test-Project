from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.utils import translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.audit import log_event

from .forms import LockoutAuthenticationForm


class LoginView(auth_views.LoginView):
    form_class = LockoutAuthenticationForm
    template_name = "registration/login.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.get_user()
        self.request.session["lang"] = user.language
        log_event("login", obj=user, request=self.request)
        return response


class LogoutView(auth_views.LogoutView):
    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            log_event("logout", obj=request.user, request=request)
        return super().post(request, *args, **kwargs)


@require_POST
def set_language(request):
    lang = request.POST.get("language")
    if lang not in dict(settings.LANGUAGES):
        return HttpResponseBadRequest()
    request.session["lang"] = lang
    translation.activate(lang)
    if request.user.is_authenticated and request.user.language != lang:
        request.user.language = lang
        request.user.save(update_fields=["language"])
    nxt = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = "/"
    return redirect(nxt)


ACTION_CODES = ("view", "add", "change", "delete")


@login_required
def access_matrix(request):
    """Who can do what: every role against every module, as management can review it."""
    from django.apps import apps
    from django.contrib.auth.models import Group
    from django.core.exceptions import PermissionDenied
    from django.shortcuts import render

    from .roles import ROLES, role_label
    from .sod import CONFLICTS, conflicts

    if not request.user.has_perm("accounts.view_user"):
        raise PermissionDenied
    groups = {g.name: {f"{p.content_type.app_label}.{p.codename}" for p in g.permissions.select_related("content_type")}
              for g in Group.objects.filter(name__in=ROLES).prefetch_related("permissions")}
    roles = [(code, role_label(code)) for code in ROLES if code in groups]
    sections = []
    for app_label in ("cases", "crm", "approvals", "core", "accounts"):
        app = apps.get_app_config(app_label)
        rows = []
        for model in app.get_models():
            meta = model._meta
            cells = []
            for code, _label in roles:
                held = [a for a in ACTION_CODES if f"{app_label}.{a}_{meta.model_name}" in groups[code]]
                cells.append(held)
            rows.append({"label": meta.verbose_name_plural, "cells": cells})
            for codename, label in meta.permissions:
                rows.append({"label": label, "special": True,
                             "cells": [[f"{app_label}.{codename}" in groups[code]] for code, _l in roles]})
        sections.append({"label": app.verbose_name, "rows": rows})
    return render(request, "accounts/access.html", {
        "roles": roles, "sections": sections, "conflicts": conflicts(),
        "rules": [(role_label(a), role_label(b), why) for a, b, why in CONFLICTS],
    })


def setup(request):
    """First start only: create the administrator, or load fictional demo data to try the system."""
    from django import forms
    from django.contrib import messages
    from django.contrib.auth import get_user_model, login
    from django.contrib.auth.models import Group
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    from django.core.management import call_command
    from django.http import Http404
    from django.shortcuts import render
    from django.utils.translation import gettext as _

    User = get_user_model()
    if User.objects.exists():
        raise Http404

    class AdminForm(forms.Form):
        name = forms.CharField(label=_("Your name"), max_length=150)
        username = forms.CharField(label=_("Username"), max_length=150)
        password = forms.CharField(label=_("Password"), widget=forms.PasswordInput)

        def clean_password(self):
            pw = self.cleaned_data["password"]
            validate_password(pw)
            return pw

    form = AdminForm(request.POST if request.POST.get("action") == "admin" else None)
    if request.method == "POST" and request.POST.get("action") == "demo":
        from core.management.commands import load_demo
        call_command(load_demo.Command())
        from .middleware import FirstRunMiddleware
        FirstRunMiddleware.checked = True
        messages.success(request, _("Demo data loaded. Sign in with any demo login below (password: Demo@2026)."))
        return redirect("login")
    if form.is_valid():
        try:
            user = User.objects.create_user(form.cleaned_data["username"], "", form.cleaned_data["password"],
                                            name_ar=form.cleaned_data["name"], is_staff=True, is_superuser=True)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            user.groups.add(Group.objects.get(name="admin"))
            from .middleware import FirstRunMiddleware
            FirstRunMiddleware.checked = True
            login(request, user)
            log_event("setup_admin_created", obj=user, request=request)
            return redirect("dashboard")
    return render(request, "registration/setup.html", {"form": form})
