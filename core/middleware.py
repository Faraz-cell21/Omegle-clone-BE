class CsrfExemptApiMiddleware:
    """Skip CSRF for JWT API routes (browser clients use Bearer token, not cookies)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/") or request.path == "/admin/login/":
            request._dont_enforce_csrf_checks = True
        return self.get_response(request)


class StrictCorsMiddleware:
    """Allow only origins listed in settings.CORS_ALLOWED_ORIGINS."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.headers.get("Origin", "")

        if request.method == "OPTIONS":
            response = self._build_preflight_response(origin)
        else:
            response = self.get_response(request)
            self._apply_cors_headers(response, origin)
        return response

    def _allowed_origins(self):
        from django.conf import settings

        return set(getattr(settings, "CORS_ALLOWED_ORIGINS", []))

    def _is_allowed(self, origin: str) -> bool:
        return bool(origin) and origin in self._allowed_origins()

    def _build_preflight_response(self, origin: str):
        from django.http import HttpResponse

        if not self._is_allowed(origin):
            return HttpResponse(status=403)

        response = HttpResponse(status=200)
        self._apply_cors_headers(response, origin)
        return response

    def _apply_cors_headers(self, response, origin: str) -> None:
        if not self._is_allowed(origin):
            return

        response["Access-Control-Allow-Origin"] = origin
        response["Access-Control-Allow-Methods"] = (
            "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        )
        response["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, Accept, Origin, User-Agent, Cache-Control, "
            "X-Requested-With"
        )
        response["Access-Control-Max-Age"] = "86400"
        response["Vary"] = "Origin"


class AllowAllCorsMiddleware:
    """
    Temporary CORS middleware for development.
    Allows any origin and common methods/headers.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS":
            response = self._build_preflight_response()
        else:
            response = self.get_response(request)
        self._add_cors_headers(response)
        return response

    def _build_preflight_response(self):
        from django.http import HttpResponse

        return HttpResponse(status=200)

    def _add_cors_headers(self, response):
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, Accept, Origin, User-Agent, Cache-Control, "
            "X-Requested-With"
        )
        response["Access-Control-Max-Age"] = "86400"
