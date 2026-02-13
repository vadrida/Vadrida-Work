from django.contrib import admin
from django.utils.html import format_html
import json
from .models import UserProfile, SiteVisitReport, ReportSketch

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