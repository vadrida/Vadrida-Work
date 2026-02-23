# chat/routing.py
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/chat/global/$', consumers.ChatConsumer.as_asgi()),
    re_path(r'ws/chat/folder/$', consumers.FolderChatConsumer.as_asgi()),
    re_path(r'ws/presence/$', consumers.PresenceConsumer.as_asgi()),
    re_path(r'ws/terminal/$', consumers.TerminalConsumer.as_asgi()),
]