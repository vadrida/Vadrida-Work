import os
import django
from django.contrib.auth.hashers import make_password

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vadrida.settings')
django.setup()

from coreapi.models import UserProfile
import uuid

def create_user(user_name, email, password, role):
    user, created = UserProfile.objects.update_or_create(
        email=email,
        defaults={
            "id": str(uuid.uuid4()),
            "user_name": user_name,
            "password": make_password(password),
            "role": role,
            "ph_no": "1234567890"
        }
    )
    if created:
        print(f"Created {role} user: {user_name} ({email})")
    else:
        print(f"Updated {role} user: {user_name} ({email})")

create_user("office_test", "office@vadrida.com", "password123", "office")
create_user("site_test", "site@vadrida.com", "password123", "site")
create_user("admin_test", "admin@vadrida.com", "password123", "admin")
