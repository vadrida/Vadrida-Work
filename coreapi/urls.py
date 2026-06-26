from django.urls import path
from . import views

app_name = "coreapi"

urlpatterns = [
    # Authentication APIs
    path("login/api/", views.login_api, name="login_api"),
    path("logout/api/", views.logout_api, name="logout_api"),
    path("api/session-status/", views.session_status_api, name="session_status_api"),
    path("api/toggle-break/", views.toggle_break_api, name="toggle_break_api"),
    path("api/request-overtime/", views.request_overtime_api, name="request_overtime_api"),
    path("api/request-leaves/", views.request_leaves_api, name="request_leaves_api"),
    path("api/biometric-action/", views.biometric_action_api, name="biometric_action_api"),
    
    # admin
    path('dev-center/', views.developer_dashboard, name='dev_dashboard'),
    path('api/dev-logs/', views.fetch_live_logs_api, name='fetch_live_logs'),
    path('api/dev-execute/', views.execute_command_api, name='dev_execute'),
    path('api/dev-health/', views.server_health_api, name='dev_health'),
    path('api/dev-restart/', views.restart_server_api, name='dev_restart'),
    path('api/dev-error/', views.get_latest_error_api, name='dev_error'),
    path('api/dev-clear-sessions/', views.clear_stale_sessions_api, name='dev_clear_sessions'),

    # Folder/File APIs
    path("api/folders/", views.search_folders_api, name="get_folders_api"),
    path("api/folder-contents/", views.get_folder_contents_api, name="folder_contents_api"),
    path('api/file-info/', views.get_file_info, name='get_file_info'),
    path('api/analyze/', views.analyze_file, name='analyze_file'),
    path("api/search/", views.search_files, name="search_files"),
    path("api/refresh/", views.refresh_files, name="refresh_files"),
    path('api/thumbnail/', views.get_thumbnail, name='get_thumbnail'),
    path('render-page/', views.render_pdf_page, name='render_pdf_page'),
    path('create-folder/', views.create_folder_page, name='create_folder'),

    # File serving
    path('serve-file/', views.serve_file, name='serve_file'),
    path('api/save-verification/', views.save_verification_data, name='save_verification_data'),

    # Pages
    path("login/", views.login_page, name="login_page"),
    path("splash-demo/", views.splash_demo, name="splash_demo"),
    path("office/", views.office_dashboard, name="office_dashboard"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path('office-verification/', views.office_verification, name='office_verification'),
    path('office-dash/', views.office, name='office'),
    path('status-viewer/', views.status_viewer, name='status_viewer'),
    path('report-drafting/', views.report_drafting, name='report_drafting'),
    
    # Feedback Form URLs
    path("feedback/", views.feedback, name="feedback"),
    path('api/save-feedback/', views.save_feedback, name='save_feedback'),
    path('pdf-editor/<str:report_id>/', views.pdf_editor_page, name='pdf_editor_page'),
    path('api/get-report-data/<str:report_id>/', views.get_report_data, name='get_report_data'),
    path('api/finalize-pdf/', views.finalize_pdf, name='finalize_pdf'),
    path('api/auto-save/', views.auto_save_api, name='auto_save'),
    path('api/get-report-data/', views.get_site_report_data, name='get_site_report_data'),
    path('api/save-corrections/', views.save_office_corrections, name='save_office_corrections'),
    path('api/create-folder/', views.create_folder_api, name='create_folder_api'),
    path('api/get-sequence/', views.get_next_sequence_api, name='get_sequence'),
    path('api/check-duplicate/', views.check_duplicate_api, name='check_duplicate'),
    path('api/upload-site-photos/', views.upload_site_photos_api, name='upload_site_photos'),
    path('api/db-case-search/', views.db_case_search_api, name='db_case_search'),
    path('api/save-verification/', views.save_verification_data, name='save_verification_data'),
    path('api/utility-hub-chat/', views.utility_hub_chat, name='utility_hub_chat'),
    path('api/transcribe-audio/', views.transcribe_audio_api, name='transcribe_audio'),

    path('api/export-status-excel/', views.export_status_excel_api, name='export_status_excel'),
    path('api/export-master-excel/', views.export_master_status_excel_api, name='export_master_excel'),
    path('api/get-drafting-payload/', views.get_drafting_mega_payload, name='get_drafting_payload'),
    path('api/save-drafting-data/', views.save_drafting_data, name='save_drafting_data'),
    path('api/get-property-photos/', views.get_property_photos_api, name='get_property_photos'),
    path('api/upload-geo-map/', views.upload_geo_map_api, name='upload_geo_map'),
    path('api/upload-eb-image/', views.upload_eb_image_api, name='upload_eb_image'),
    
    # Digital Signer
    path('digital-signer/', views.digital_signer, name='digital_signer'),
    path('api/digital-sign/', views.digital_sign_pdf_api, name='digital_sign_pdf_api'),
    path('api/serve-local-pdf/', views.serve_local_pdf, name='serve_local_pdf'),
]
