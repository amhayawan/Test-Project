from django.utils import translation


class UserLanguageMiddleware:
    """Apply the language the user chose (stored on their account), before LocaleMiddleware runs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = request.session.get("lang") if hasattr(request, "session") else None
        if lang:
            request.META["HTTP_ACCEPT_LANGUAGE"] = lang
            translation.activate(lang)
        return self.get_response(request)
