from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django.views.generic import RedirectView  # 1. Import RedirectView
from coreapi import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(pattern_name='coreapi:login_page', permanent=False)), 
    path('core/', include('core.urls')),
    path('coreapi/', include(('coreapi.urls', 'coreapi'), namespace='coreapi')), 
    path('chat/', include('chat.urls')),
    path('', include('pwa.urls')),
    path('.well-known/assetlinks.json', views.assetlinks, name='assetlinks'),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)