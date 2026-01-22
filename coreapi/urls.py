from django.urls import path
from . import views

app_name = "coreapi"

urlpatterns = [
    # Authentication APIs
    path("login/api/", views.login_api, name="login_api"),
    path("logout/api/", views.logout_api, name="logout_api"),

    # Folder/File APIs
    path("api/folders/", views.search_folders_api, name="get_folders_api"),
    path("api/folder-contents/", views.get_folder_contents_api, name="folder_contents_api"),
    path('api/file-info/', views.get_file_info, name='get_file_info'),
    path('api/analyze/', views.analyze_file, name='analyze_file'),
    path("api/search/", views.search_files, name="search_files"),
    path("api/refresh/", views.refresh_files, name="refresh_files"),
    path('api/thumbnail/', views.get_thumbnail, name='get_thumbnail'),
    path('render-page/', views.render_pdf_page, name='render_pdf_page'),

    # File serving
    path('serve-file/', views.serve_file, name='serve_file'),

    # Pages
    path("login/", views.login_page, name="login_page"),
    # path("manager/", views.admin_dashboard, name="admin_dashboard"),
    path("office/", views.office_dashboard, name="office_dashboard"),
    path("dashboard/", views.dashboard, name="dashboard"),
    
    # Feedback Form URLs
    path("feedback/", views.feedback, name="feedback"),
    path("admin_/",views.admin_dash,name="admin_dash"),
    path('api/save-feedback/', views.save_feedback, name='save_feedback'),
    path('pdf-editor/<str:report_id>/', views.pdf_editor_page, name='pdf_editor_page'),
    path('api/get-report-data/<str:report_id>/', views.get_report_data, name='get_report_data'),
    path('api/finalize-pdf/', views.finalize_pdf, name='finalize_pdf'),
    path('api/auto-save/', views.auto_save_api, name='auto_save'),
]