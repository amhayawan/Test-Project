import contextvars

_request = contextvars.ContextVar("haz_request", default=None)


def current_request():
    return _request.get()


def current_user():
    request = _request.get()
    user = getattr(request, "user", None)
    return user if user is not None and user.is_authenticated else None


class RequestContextMiddleware:
    """Makes the current request available to the audit trail."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _request.set(request)
        try:
            return self.get_response(request)
        finally:
            _request.reset(token)


class SecurityHeadersMiddleware:
    CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
           "frame-ancestors 'none'; form-action 'self'; base-uri 'self'")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.CSP)
        if not request.path.startswith("/static/"):
            response.setdefault("Cache-Control", "no-store")
        return response
