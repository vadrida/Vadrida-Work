from django.shortcuts import redirect
from django.core.cache import cache
from django.utils.deprecation import MiddlewareMixin
import traceback
import os
import json
from datetime import datetime
from django.conf import settings

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
            "/admin/",
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

class RedisActiveUserMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # Look for your custom session variable
        user_name = request.session.get('user_name')
        if user_name:
            # Set a flag in Redis for this user that auto-deletes after 5 minutes (300 seconds)
            cache.set(f"online_user_{user_name}", True, 300)
            
        # Update session logout time based on last activity
        user_id = request.session.get('user_id')
        if user_id:
            try:
                from django.utils import timezone
                from coreapi.models import WorkSession
                now = timezone.now()
                today = now.date()
                session_obj = WorkSession.objects.filter(user_id=user_id, date=today, is_active=True).first()
                if session_obj:
                    session_obj.logout_time = now
                    delta = now - session_obj.login_time
                    session_obj.hours_worked = round(delta.total_seconds() / 3600, 2)
                    session_obj.save(update_fields=['logout_time', 'hours_worked'])
            except Exception:
                pass
            
class SmartExceptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        """Catches crashes and translates them into plain English solutions"""
        
        error_type = type(exception).__name__
        error_msg = str(exception)
        tb = traceback.format_exc()

        # --- THE DEVELOPER TRANSLATOR DICTIONARY ---
        solutions = {
            'TemplateDoesNotExist': 'Check if the HTML file exists in your templates folder and is spelled correctly in your views.py render() function.',
            'ModuleNotFoundError': 'You forgot to `pip install` a package, or you are missing a comma in INSTALLED_APPS.',
            'OperationalError': 'Database issue! Did you forget to run `python manage.py migrate`? Or is your PostgreSQL service turned off?',
            'SyntaxError': 'You have a typo, missing colon, or wrong indentation in your Python code. Check the exact line number.',
            'DoesNotExist': 'You are using .get() to find a database record that does not exist. Use .filter().first() instead to avoid crashing.',
            'MultiValueDictKeyError': 'You are trying to get data from a form (request.POST) that is missing. Use request.POST.get("key") instead of request.POST["key"].',
            'NameError': 'You are trying to use a variable or function that you forgot to import at the top of the file.'
        }

        # Find the plain English solution, or provide a default one
        plain_english_solution = solutions.get(error_type, 'Read the bottom line of the traceback below to see the exact variable or line causing the crash.')

        # Format the data
        error_data = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'type': error_type,
            'message': error_msg,
            'solution': plain_english_solution,
            'path': request.path,
            'traceback': tb
        }

        # Save it to our logs folder
        log_path = os.path.join(settings.BASE_DIR, 'logs', 'latest_error.json')
        try:
            with open(log_path, 'w') as f:
                json.dump(error_data, f)
        except Exception:
            pass

        # Return None so Django continues to show the normal error page to the user
        return None