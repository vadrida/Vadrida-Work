from django.contrib import admin
from django.utils.html import format_html
import json
from .models import UserProfile, SiteVisitReport, ReportSketch, ClientFolder, VerificationReport, DraftingReport, MonthlyPerformance, LeaveRecord, CreditLedger, WorkSession

# 1. Improved Inline for Sketches
class ReportSketchInline(admin.TabularInline):
    model = ReportSketch
    extra = 0
    # Add 'source_key' to readonly so admins don't accidentally break the link to the form field
    readonly_fields = ('source_key', 'image_preview', 'created_at')
    fields = ('source_key', 'image', 'image_preview', 'created_at')

    def image_preview(self, obj):
        if obj.image:
            # Added max-height so tall sketches don't take up the whole screen
            return format_html(
                '<a href="{url}" target="_blank"><img src="{url}" style="max-width: 200px; max-height: 200px;" /></a>', 
                url=obj.image.url
            )
        return "No Image"
    image_preview.short_description = "Sketch Preview"

# 2. Main Report Admin
@admin.register(SiteVisitReport)
class SiteVisitReportAdmin(admin.ModelAdmin):
    list_display = ('office_file_no', 'applicant_name', 'user', 'created_at','generated_pdf_name','completion_score')
    search_fields = ('office_file_no', 'applicant_name', 'user__user_name')
    list_filter = ('created_at', 'user')
    
    # Connect the Inline here
    inlines = [ReportSketchInline]

    # Display JSON nicely
    readonly_fields = ('formatted_data', 'created_at')

    def formatted_data(self, obj):
        try:
            # Convert JSON to a pretty string
            data = json.dumps(obj.form_data, indent=4)
            # Wrap in <pre> to keep formatting
            return format_html('<pre style="background: #f5f5f5; padding: 10px; border-radius: 5px;">{}</pre>', data)
        except Exception:
            return str(obj.form_data)
    
    formatted_data.short_description = "Form JSON Data"

    fieldsets = (
        ("Meta Info", {
            "fields": ("user", "office_file_no", "applicant_name", "target_folder", "created_at","generated_pdf_name","completion_score")
        }),
        ("Captured Data", {
            "fields": ("formatted_data",)
        }),
    )

# 3. User Profile Admin (Standard)
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user_name", "email", "role", "created_at")
    search_fields = ("user_name", "email")

@admin.register(ClientFolder)
class ClientFolderAdmin(admin.ModelAdmin):
    # What columns to show in the list
    list_display = (
        'unique_file_no', 
        'applicant_name', 
        'bank_code', 
        'district_code', 
        'product', 
        'created_at'
    )
    
    # Enable clicking on these to edit
    list_display_links = ('unique_file_no', 'applicant_name')
    
    # Add a Search Bar (Search by Name, File No, Bank Ref)
    search_fields = ('unique_file_no', 'applicant_name', 'bank_ref_no', 'full_folder_path')
    
    # Add Filters on the right side
    list_filter = ('year', 'bank_code', 'district_code', 'product', 'created_at')
    
    # Order by newest first
    ordering = ('-created_at',)
    
    # Make the list per page smaller for speed
    list_per_page = 50

@admin.register(VerificationReport)
class VerificationReportAdmin(admin.ModelAdmin):
    list_display = ('office_file_no', 'verified_by', 'inspection_date', 'created_at')
    search_fields = ('office_file_no', 'verified_by__user_name')
    readonly_fields = ('formatted_database', 'created_at', 'updated_at')
    
    def formatted_database(self, obj):
        try:
            data = json.dumps(obj.verification_database, indent=4)
            return format_html('<pre style="background: #eef2ff; padding: 10px; border: 1px solid #c7d2fe;">{}</pre>', data)
        except Exception:
            return str(obj.verification_database)
    
    formatted_database.short_description = "Verified Data JSON"

    fieldsets = (
        ("Verification Info", {
            "fields": ("office_file_no", "verified_by", "inspection_date", "documents_received")
        }),
        ("Database Data", {
            "fields": ("formatted_database",)
        }),
    )
admin.site.register(DraftingReport)

# --- EMPLOYEE ANALYTICS ADMIN ---

@admin.register(MonthlyPerformance)
class MonthlyPerformanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'month', 'year', 'files_done', 'files_target', 'hours_worked', 'overtime_hours', 'pd_cases', 'npa_cases', 'project_cases', 'other_cases', 'updated_at')
    list_filter = ('year', 'month', 'user')
    search_fields = ('user__user_name', 'user__email')
    list_editable = ('files_done', 'files_target', 'hours_worked', 'overtime_hours', 'pd_cases', 'npa_cases', 'project_cases', 'other_cases')
    list_per_page = 25
    ordering = ('-year', '-month')


@admin.register(LeaveRecord)
class LeaveRecordAdmin(admin.ModelAdmin):
    list_display = ('user', 'leave_date', 'leave_type', 'reason', 'created_at')
    list_filter = ('leave_type', 'leave_date', 'user')
    search_fields = ('user__user_name', 'reason')
    list_editable = ('leave_type',)
    list_per_page = 50
    ordering = ('-leave_date',)
    date_hierarchy = 'leave_date'


@admin.register(CreditLedger)
class CreditLedgerAdmin(admin.ModelAdmin):
    list_display = ('user', 'credits', 'source', 'reference', 'earned_date', 'notes', 'created_at')
    list_filter = ('source', 'earned_date', 'user')
    search_fields = ('user__user_name', 'reference', 'notes')
    list_editable = ('credits', 'source', 'notes')
    list_per_page = 50
    ordering = ('-earned_date', '-created_at')
    date_hierarchy = 'earned_date'


@admin.register(WorkSession)
class WorkSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'login_time', 'logout_time', 'hours_worked', 'overtime_hours', 'is_active')
    list_filter = ('is_active', 'date', 'user')
    search_fields = ('user__user_name',)
    list_per_page = 50
    readonly_fields = ('login_time', 'logout_time', 'hours_worked')

from .models import SystemConfiguration, OvertimeRequest

@admin.register(SystemConfiguration)
class SystemConfigurationAdmin(admin.ModelAdmin):
    list_display = ('id', 'files_per_day', 'credits_per_file', 'hours_target', 'max_session_hours')
    
    def has_add_permission(self, request):
        # Prevent multiple rows
        return not SystemConfiguration.objects.exists()

@admin.register(OvertimeRequest)
class OvertimeRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'request_date', 'status', 'requested_at', 'approved_at')
    list_filter = ('status', 'request_date')
    actions = ['approve_requests', 'deny_requests']

    def approve_requests(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='approved', approved_at=timezone.now())
    approve_requests.short_description = "Approve selected requests"

    def deny_requests(self, request, queryset):
        queryset.update(status='denied')
    deny_requests.short_description = "Deny selected requests"
    date_hierarchy = 'request_date'
