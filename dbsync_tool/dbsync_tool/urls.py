"""
URL configuration for dbsync_tool project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter
from sync_jobs.api_views import SyncJobViewSet

router = DefaultRouter()
router.register(r'jobs', SyncJobViewSet, basename='job')

urlpatterns = [
    path('login/', RedirectView.as_view(url='/accounts/login/', permanent=True)),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('connections/', include('connections.urls')),
    path('metadata/', include('metadata.urls')),
    path('sync-jobs/', include('sync_jobs.urls')),
    path('api/scheduler/', include('scheduler.urls')),
    path('api/', include(router.urls)),
    path('', include('core.urls')),
]

# Custom error handlers
handler403 = 'core.views.permission_denied_view'
handler404 = 'core.views.page_not_found_view'
handler500 = 'core.views.server_error_view'
