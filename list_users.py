import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vadrida.settings')
django.setup()

from coreapi.models import UserProfile
users = UserProfile.objects.all()
for u in users:
    print(f"User: {u.user_name}, Email: {u.email}, Role: {u.role}")
