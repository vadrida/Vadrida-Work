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
    year = models.CharField(max_length=4)        
    bank_code = models.CharField(max_length=10)  
    district_code = models.CharField(max_length=10) 
    sequence_no = models.IntegerField()   

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
    
# --- NEW MODEL FOR OFFICE VERIFICATION DATA ---
class VerificationReport(models.Model):
    # Link it to the original file number
    office_file_no = models.CharField(max_length=50, unique=True, db_index=True)
    
    # Who verified it
    verified_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True)
    
    # The Top Section Data
    applicant_name = models.CharField(max_length=255, blank=True, null=True)
    product = models.CharField(max_length=100, blank=True, null=True)
    inspection_date = models.CharField(max_length=50, blank=True, null=True)
    person_met_at_site = models.CharField(max_length=255, blank=True, null=True)
    documents_received = models.JSONField(default=list, blank=True, null=True)
    
    # The massive, isolated dictionary containing all document forms (Title Deed, etc.)
    verification_database = models.JSONField(default=dict, blank=True, null=True)
    
    # General Notes/Deviations
    survey_notes = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Verification for {self.office_file_no}"

# --- NEW MODEL FOR REAL-TIME REPORT DRAFTING & AUDIT LOGS ---
class DraftingReport(models.Model):
    # Primary Key is the File Number
    office_file_no = models.CharField(max_length=50, primary_key=True, db_index=True)
    bank_code = models.CharField(max_length=10, blank=True, null=True)
    bank_name = models.CharField(max_length=255, blank=True, null=True)
    
    # Collaborators
    site_visitor = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='drafting_site_visits')
    office_verifier = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='drafting_verifications')
    report_drafter = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='drafting_current_work')

    # Status
    status = models.CharField(max_length=20, default='drafting') # drafting, completed, archived
    
    # Core Data
    report_data = models.JSONField(default=dict) # The latest state of all fields
    
    # Audit Log (Movement Tracking)
    # Structure: [{"user": "id", "name": "name", "field": "field_id", "old": "...", "new": "...", "timestamp": "..."}]
    audit_log = models.JSONField(default=list)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Drafting Report: {self.office_file_no} ({self.bank_name})"


# --- EMPLOYEE ANALYTICS SYSTEM ---

class MonthlyPerformance(models.Model):
    """One row per user per month. Primary data source for the dashboard."""
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='monthly_performance')
    year = models.IntegerField()
    month = models.IntegerField()  # 1-12

    # File Metrics
    files_done = models.IntegerField(default=0)
    files_target = models.IntegerField(default=125)  # 25 days × 5 files/day

    # Hours Metrics
    hours_worked = models.FloatField(default=0)
    hours_target = models.FloatField(default=200)  # ~25 days × 8 hours
    overtime_hours = models.FloatField(default=0)

    # Case Type Counters
    pd_cases = models.IntegerField(default=0)
    npa_cases = models.IntegerField(default=0)
    project_cases = models.IntegerField(default=0)
    other_cases = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'year', 'month')
        ordering = ['-year', '-month']
        verbose_name = 'Monthly Performance'
        verbose_name_plural = 'Monthly Performance Records'

    def __str__(self):
        return f"{self.user.user_name} — {self.month}/{self.year}"


class LeaveRecord(models.Model):
    """One row per leave day. Admin-managed, no approval workflow."""
    LEAVE_TYPES = [
        ('earned', 'Earned Leave'),
        ('sick', 'Sick Leave'),
        ('casual', 'Casual Leave'),
    ]

    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='leave_records')
    leave_date = models.DateField()
    leave_type = models.CharField(max_length=10, choices=LEAVE_TYPES)
    reason = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-leave_date']
        verbose_name = 'Leave Record'
        verbose_name_plural = 'Leave Records'

    def __str__(self):
        return f"{self.user.user_name} — {self.leave_type} on {self.leave_date}"


class CreditLedger(models.Model):
    """Credit-only ledger. Credits added on file completion/signing. Admin can deduct manually."""
    SOURCE_TYPES = [
        ('file_completion', 'File Completion'),
        ('report_signed', 'Report Signed'),
        ('bonus', 'Bonus'),
        ('admin_adjustment', 'Admin Adjustment'),
    ]

    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='credit_entries')
    credits = models.IntegerField()  # Positive = credit earned, negative = admin deduction
    source = models.CharField(max_length=20, choices=SOURCE_TYPES)
    reference = models.CharField(max_length=100, blank=True, null=True)  # e.g. office file number
    earned_date = models.DateField()
    notes = models.TextField(blank=True, null=True)  # Admin notes for adjustments

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-earned_date', '-created_at']
        verbose_name = 'Credit Entry'
        verbose_name_plural = 'Credit Ledger'

    def __str__(self):
        sign = "+" if self.credits >= 0 else ""
        return f"{self.user.user_name} — {sign}{self.credits} ({self.source})"


class WorkSession(models.Model):
    """Tracks daily work sessions. One active session per user per day."""
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='work_sessions')
    date = models.DateField()
    login_time = models.DateTimeField()  # When the user first logged in today
    logout_time = models.DateTimeField(null=True, blank=True)
    hours_worked = models.FloatField(default=0)
    overtime_hours = models.FloatField(default=0)
    is_active = models.BooleanField(default=True)  # Currently logged in

    class Meta:
        unique_together = ('user', 'date')
        ordering = ['-date']
        verbose_name = 'Work Session'
        verbose_name_plural = 'Work Sessions'

    def __str__(self):
        status = "🟢 Active" if self.is_active else "🔴 Ended"
        return f"{self.user.user_name} - {self.date} ({status})"


class SystemConfiguration(models.Model):
    """Stores global multipliers and configurations editable by the Admin."""
    files_per_day = models.IntegerField(default=5)
    credits_per_file = models.IntegerField(default=6)
    hours_target = models.FloatField(default=176.0)
    max_session_hours = models.FloatField(default=10.0, help_text="Auto-logout after X hours of work in a single day.")

    class Meta:
        verbose_name = 'System Configuration'
        verbose_name_plural = 'System Configurations'

    def __str__(self):
        return "Global System Settings"

    def save(self, *args, **kwargs):
        # Ensure only one record exists
        if not self.pk and SystemConfiguration.objects.exists():
            return
        super().save(*args, **kwargs)

class OvertimeRequest(models.Model):
    """Tracks overtime access requests from employees to bypass the 10-hour logout."""
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('denied', 'Denied')
    )
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='overtime_requests')
    request_date = models.DateField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Overtime Request'
        verbose_name_plural = 'Overtime Requests'
        ordering = ['-requested_at']

    def __str__(self):
        return f"{self.user.user_name} - {self.request_date} ({self.status})"