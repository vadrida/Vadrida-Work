from django.db import models
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User


class UserProfile(models.Model):
    id = models.CharField(max_length=200, primary_key=True)
    user_name = models.CharField(max_length=100, unique=True)
    email = models.EmailField(unique=True)
    ph_no = models.CharField(max_length=15)
    role = models.CharField(max_length=20)
    password = models.CharField(max_length=200, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.password and not self.password.startswith("pbkdf2_"):
            self.password = make_password(self.password)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user_name} ({self.role})"

class SiteVisitReport(models.Model):
    # Meta info
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Key Searchable Fields (Extracted from the JSON for easy indexing)
    office_file_no = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    applicant_name = models.CharField(max_length=255, blank=True, null=True)

    # The Main Data Dump
    # This stores the entire formState (Valuers, Ownership, Survey, etc.)
    form_data = models.JSONField(default=dict)

    # The Hand Sketch (Decoded from Base64)
    sketch = models.ImageField(upload_to='site_sketches/', blank=True, null=True)

    def __str__(self):
        return f"Report {self.office_file_no} - {self.applicant_name}"