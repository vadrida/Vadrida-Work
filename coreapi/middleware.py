from django.shortcuts import redirect
class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        allowed_paths = [
            "/coreapi/login",
            "/coreapi/login/",
            "/coreapi/login/api",
            "/coreapi/login/api/",
            "/",
            "/services/",
            "/contact/",
            "/about/",
            "/work/",
            "/manifest.json",
            "/serviceworker.js",        # <--- NEW: Required for PWA
            "/offline",                 # <--- NEW: Required for PWA offline mode
            "/.well-known/assetlinks.json",
        ]

        # Allow static + media
        if request.path.startswith("/static/") or request.path.startswith("/media/"):
            return self.get_response(request)
        if request.path.startswith("/admin/"):
            return self.get_response(request)


        # Skip login API
        if request.path.startswith("/coreapi/login/api/"):
            return self.get_response(request)

        # If user is NOT logged in and path not allowed → redirect
        if request.session.get("user_id") is None and request.path not in allowed_paths:
            return redirect("/coreapi/login/")

        return self.get_response(request)
