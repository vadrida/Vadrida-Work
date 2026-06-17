# core/urls.py
from django.urls import path
from . import views

app_name = 'core' # Keep this commented out if you chose Option A earlier

urlpatterns = [
    # The Page
    path('dashboard/', views.admin_dashboard, name='admin_dashboard'),
    
    # The APIs
    path('api/dashboard-data/', views.dashboard_stats_api, name='api_dashboard_data'),
    path('api/user-details/<str:user_id>/', views.user_details_api, name='api_user_details'),
    path('report-detail/<int:report_id>/', views.report_detail_view, name='report_detail'),
    path('api/stats/', views.dashboard_stats_api, name='api_stats'),
    path('api/pdfs/', views.list_pdfs_api, name='api_pdfs'),
    path('view-pdf/<str:filename>/', views.view_pdf, name='view_pdf'),
    path('report-analysis/', views.report_analysis_view, name='report_analysis'),
    path('api/analysis-data/', views.analysis_data_api, name='analysis_data_api'),
    path('summary-report/', views.admin_summary_page, name='admin_summary_page'),
    path('api/system-holidays/', views.system_holidays_api, name='system_holidays_api'),
    path('api/system-config/', views.system_config_api, name='system_config_api'),
    path('api/credit-users/', views.credit_users_api, name='credit_users_api'),
    path('api/attendance/', views.attendance_api, name='attendance_api'),
    path('api/leaves/', views.leaves_api, name='leaves_api'),
]