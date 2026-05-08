from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/report-drafting/(?P<file_no>[^/]+)/$', consumers.DraftingConsumer.as_asgi()),
]
