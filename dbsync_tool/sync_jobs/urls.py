from django.urls import path
from . import views

app_name = 'sync_jobs'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('jobs/', views.job_list, name='list'),
    path('create/step1/', views.create_job_step1_view, name='create_step1'),
    path('create/step2/', views.create_job_step2_view, name='create_step2'),
    path('create/step2/submit/', views.create_job_step2_submit, name='create_step2_submit'),
    path('api/validate-transformation-query/', views.validate_transformation_query, name='validate_transformation_query'),
    path('create/step3/', views.create_job_step3_view, name='create_step3'),
    path('create/step3/submit/', views.create_job_step3_submit, name='create_step3_submit'),
    path('api/table-columns/', views.get_table_columns_api, name='get_table_columns_api'),
    path('<uuid:job_id>/', views.job_detail, name='job_detail'),
    path('<uuid:job_id>/edit/', views.job_edit, name='job_edit'),
    path('<uuid:job_id>/delete/', views.job_delete, name='job_delete'),
    path('<uuid:job_id>/pause/', views.job_pause, name='job_pause'),
    path('<uuid:job_id>/resume/', views.job_resume, name='job_resume'),
    path('<uuid:job_id>/schedule/update/', views.update_schedule, name='update_schedule'),
    path('<uuid:job_id>/run/', views.job_run_now, name='job_run_now'),
    path('<uuid:job_id>/executions/<uuid:execution_id>/', views.execution_detail, name='execution_detail'),
    path('<uuid:job_id>/executions/<uuid:execution_id>/status/', views.execution_status_api, name='execution_status_api'),
    path('<uuid:job_id>/checkpoints/reset/<str:schema_name>/<str:table_name>/', views.reset_checkpoint, name='reset_checkpoint'),
    path('<uuid:job_id>/checkpoints/', views.view_checkpoints, name='view_checkpoints'),
    path('<uuid:job_id>/report/', views.job_report, name='job_report'),
    path('reports/', views.user_report, name='user_report'),
    path('bulk/pause/', views.bulk_pause, name='bulk_pause'),
    path('bulk/resume/', views.bulk_resume, name='bulk_resume'),
    path('bulk/delete/', views.bulk_delete, name='bulk_delete'),
]

