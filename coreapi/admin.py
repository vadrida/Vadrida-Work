from django.contrib import admin
from django.utils.html import format_html
import json
from .models import UserProfile, SiteVisitReport, ReportSketch

# 1. Create an Inline for the sketches
class ReportSketchInline(admin.TabularInline):
    model = ReportSketch
    extra = 0  # Don't show extra empty rows
    readonly_fields = ('image_preview',)  # Show the image, don't just let them edit the path

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="width: 150px; height: auto;" />', obj.image.url)
        return "No Image"
    image_preview.short_description = "Preview"

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user_name", "email", "role", "created_at", "password")

@admin.register(SiteVisitReport)
class SiteVisitReportAdmin(admin.ModelAdmin):
    list_display = ('office_file_no', 'applicant_name', 'created_at') # Removed 'sketch_preview' from here
    search_fields = ('office_file_no', 'applicant_name')
    
    # Add the inline here to see sketches at the bottom of the report page
    inlines = [ReportSketchInline]

    # Added 'created_at' to readonly so it doesn't crash on edit
    readonly_fields = ('formatted_data', 'created_at')

    def formatted_data(self, obj):
        # Pretty print the JSON data
        return format_html('<pre>{}</pre>', json.dumps(obj.form_data, indent=4))
    formatted_data.short_description = "Full Form Data"

    fieldsets = (
        ("Meta Info", {
            "fields": ("user", "office_file_no", "applicant_name", "created_at")
        }),
        # Removed the "Sketch" section because they are now in the Inline below
        ("Form Data", {
            "fields": ("formatted_data",)
        }),
    )