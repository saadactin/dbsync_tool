from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard, name='dashboard_redirect'),
    path('health/', views.health_check, name='health_check'),
    path('api/metrics/', views.performance_metrics, name='performance_metrics'),

    # Notifications Management
    path('notifications/', views.notifications_page, name='notifications'),
    path('api/notification-recipients/', views.notification_recipients_list, name='api_notification_recipients_list'),
    path('api/notification-recipients/create/', views.notification_recipients_create, name='api_notification_recipients_create'),
    path('api/notification-recipients/<int:recipient_id>/toggle/', views.notification_recipients_toggle, name='api_notification_recipients_toggle'),
    path('api/notification-recipients/<int:recipient_id>/delete/', views.notification_recipients_delete, name='api_notification_recipients_delete'),
]

