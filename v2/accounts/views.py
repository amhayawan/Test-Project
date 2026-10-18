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
