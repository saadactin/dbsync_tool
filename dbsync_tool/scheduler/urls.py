from django.urls import path
from . import views

app_name = 'scheduler'

urlpatterns = [
    path('tasks/<str:task_id>/status/', views.task_status, name='task_status'),
]

