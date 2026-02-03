from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard, name='dashboard_redirect'),
    path('health/', views.health_check, name='health_check'),
    path('api/metrics/', views.performance_metrics, name='performance_metrics'),
]

