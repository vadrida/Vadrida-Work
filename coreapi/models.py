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
    last_seen = models.DateTimeField(null=True, blank=True)
    current_page = models.CharField(max_length=255, null=True, blank=True)
    

    def save(self, *args, **kwargs):
        if self.password and not self.password.startswith("pbkdf2_"):
            self.password = make_password(self.password)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user_name} ({self.role})"

class SiteVisitReport(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    office_file_no = models.CharField(max_length=50, unique=True, null=True, blank=True, db_index=True)
    applicant_name = models.CharField(max_length=255, blank=True, null=True)
    generated_pdf_name = models.CharField(max_length=255, blank=True, null=True)
    
    # Store the text data here (cleaned, without images)
    form_data = models.JSONField(default=dict)
    target_folder = models.CharField(max_length=500, blank=True, null=True, default="")
    completion_score = models.IntegerField(default=0)  # Stores 0 to 100
    # Optional: Keep this for the "Main" layout if you want it easily accessible, 
    # or you can move it to the child model too.
    main_sketch = models.ImageField(upload_to='main_sketches/', blank=True, null=True)
  

    def __str__(self):
        return f"Report {self.office_file_no}"

# --- NEW MODEL FOR HANDLING ALL NOTE SKETCHES ---
class ReportSketch(models.Model):
    # Link to the parent report
    report = models.ForeignKey(SiteVisitReport, related_name='sketches', on_delete=models.CASCADE)
    
    # Stores the "Path" from your JS (e.g., "Ownership_Analysis.Ownership_Analysis_notes")
    source_key = models.CharField(max_length=255, db_index=True)
    
    # The actual image file
    image = models.ImageField(upload_to='note_sketches/')
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Sketch for {self.source_key} (Report {self.report.id})"

class ClientFolder(models.Model):
    # The Unique 10-digit ID (Primary Key)
    unique_file_no = models.CharField(max_length=20, unique=True, primary_key=True)
    
    # Specifics for counting
    year = models.CharField(max_length=4)        # e.g. "26"
    bank_code = models.CharField(max_length=10)  # e.g. "01"
    district_code = models.CharField(max_length=10) # e.g. "07"
    sequence_no = models.IntegerField()          # e.g. 1, 2, 3...

    # Metadata
    applicant_name = models.CharField(max_length=255)
    product = models.CharField(max_length=100)
    bank_ref_no = models.CharField(max_length=100)
    
    site_staff_code = models.CharField(max_length=50)
    office_staff_code = models.CharField(max_length=50)
    
    full_folder_path = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.unique_file_no} - {self.applicant_name}"