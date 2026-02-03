# core/middleware.py
from django.utils import timezone
from coreapi.models import UserProfile
from django.core.cache import cache

class ActiveUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # 1. Skip static files to save database power
        if request.path.startswith('/static/') or request.path.startswith('/media/'):
            return response

        # 2. Check if user is logged in (Using your custom session key)
        user_id = request.session.get('user_id')
        
        if user_id:
            # 3. Optimization: Only update DB once every 60 seconds per user
            # We use cache to check if we just updated this user
            cache_key = f'last_seen_update_{user_id}'
            if not cache.get(cache_key):
                try:
                    # Update the UserProfile
                    UserProfile.objects.filter(id=user_id).update(
                        last_seen=timezone.now(),
                        current_page=request.path
                    )
                    # Set cache to prevent another DB write for 60 seconds
                    cache.set(cache_key, True, 60) 
                except Exception as e:
                    print(f"Middleware Error: {e}")

        return response