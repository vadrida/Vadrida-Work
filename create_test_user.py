import os
import django
from django.contrib.auth.hashers import make_password

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vadrida.settings')
django.setup()

from coreapi.models import UserProfile
import uuid

# Check if test user exists
user_name = "testuser"
email = "test@vadrida.com"
password = "password123"

user, created = UserProfile.objects.update_or_create(
    user_name=user_name,
    defaults={
        "id": str(uuid.uuid4()),
        "email": email,
        "password": make_password(password),
        "role": "OFFICE",
        "ph_no": "1234567890"
    }
)

if created:
    print(f"Created user: {user_name} with password: {password}")
else:
    # Update password for existing user
    user.password = make_password(password)
    user.save()
    print(f"Updated user: {user_name} with password: {password}")
