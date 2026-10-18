from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.audit import log_event


class LockoutAuthenticationForm(AuthenticationForm):
    """Normal login, plus: lock the account for a while after too many wrong passwords."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": _("Wrong username or password."),
        "locked": _("This account is temporarily locked after repeated wrong passwords. Try again in %(minutes)s minutes."),
    }

    def clean(self):
        username = self.cleaned_data.get("username")
        user = get_user_model().objects.filter(username=username).first() if username else None
        if user and user.is_locked:
            minutes = int((user.locked_until - timezone.now()).total_seconds() // 60) + 1
            raise forms.ValidationError(self.error_messages["locked"], code="locked", params={"minutes": minutes})
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            log_event("login_failed", summary=f"username: {(username or '')[:64]}", request=self.request)
            if user:
                user.failed_logins += 1
                if user.failed_logins >= settings.MAX_FAILED_LOGINS:
                    user.failed_logins = 0
                    user.locked_until = timezone.now() + timedelta(minutes=settings.LOCKOUT_MINUTES)
                    log_event("locked", obj=user, summary=user.username, request=self.request)
                user.save(update_fields=["failed_logins", "locked_until"])
            raise
        if self.user_cache.failed_logins or self.user_cache.locked_until:
            self.user_cache.failed_logins = 0
            self.user_cache.locked_until = None
            self.user_cache.save(update_fields=["failed_logins", "locked_until"])
        return cleaned
