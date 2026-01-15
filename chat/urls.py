# chat/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('history/', views.chat_history, name='chat_history'),
    path('upload/', views.upload_chat_file, name='chat_upload'),
    path('api/folder-history/', views.folder_chat_history, name='folder_chat_history'),
    path('api/send-message/', views.send_folder_message, name='send_folder_message'),
]