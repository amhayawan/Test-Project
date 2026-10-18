from django.utils import translation


class UserLanguageMiddleware:
    """Apply the language the user chose (stored on their account), before LocaleMiddleware runs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Arabic unless the user chose English: the computer's own language does not decide.
        from django.conf import settings
        lang = (request.session.get("lang") if hasattr(request, "session") else None) or settings.LANGUAGE_CODE
        if lang:
            request.META["HTTP_ACCEPT_LANGUAGE"] = lang
            translation.activate(lang)
        return self.get_response(request)


class FirstRunMiddleware:
    """Until the first user exists, every page leads to the setup page."""

    checked = False

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not FirstRunMiddleware.checked:
            from django.contrib.auth import get_user_model
            if get_user_model().objects.exists():
                FirstRunMiddleware.checked = True
            elif not request.path.startswith(("/setup/", "/static/", "/language/")):
                from django.shortcuts import redirect
                return redirect("setup")
        return self.get_response(request)
