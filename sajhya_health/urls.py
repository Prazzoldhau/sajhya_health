from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

from . import views

handler403 = 'sajhya_health.views.permission_denied'
handler404 = 'sajhya_health.views.page_not_found'
handler500 = 'sajhya_health.views.server_error'

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path('', views.landing_page, name='landing'),
    path('healthz/', views.healthz, name='healthz'),
    path('accounts/', include('accounts.urls')),
    path('marketplace/', include('marketplace.urls')),
    path('exercises/', include('exercises.urls')),
    path('billing/', include('billing.urls')),
    path('lab-tests/', include('lab.urls')),
    path('profiles/', include('profiles.urls')),
    path('assessments/', include('assessments.urls')),
    path('clinics/', include('clinics.urls')),
    path('soapnotes/', include('soapnotes.urls')),
    path('portal/', include('portal.urls')),
]

if settings.SERVE_MEDIA:
    urlpatterns += [re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT})]
