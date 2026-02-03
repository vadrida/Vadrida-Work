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
]