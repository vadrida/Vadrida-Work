from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include, re_path
from django.views.generic import RedirectView
from coreapi import views
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(pattern_name='coreapi:login_page', permanent=False)), 
    path('core/', include('core.urls')),
    path('coreapi/', include(('coreapi.urls', 'coreapi'), namespace='coreapi')), 
    path('chat/', include('chat.urls')),
    path('', include('pwa.urls')),
    path('.well-known/assetlinks.json', views.assetlinks, name='assetlinks'),
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)