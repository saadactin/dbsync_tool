"""
URL configuration for metadata app
"""
from django.urls import path
from . import views

app_name = 'metadata'

urlpatterns = [
    path('api/<uuid:connection_id>/schemas/', views.load_schemas_view, name='schemas'),
    path('api/<uuid:connection_id>/schemas/<str:schema>/tables/', views.load_tables_view, name='tables'),
    path('api/<uuid:connection_id>/schemas/<str:schema>/tables/<str:table>/', views.load_table_metadata_view, name='table_metadata'),
    path('api/<uuid:connection_id>/schemas/<str:schema>/tables/<str:table>/columns/', views.load_table_columns_view, name='columns'),
    path('api/<uuid:connection_id>/schemas/<str:schema>/tables/<str:table>/row-count/', views.get_table_row_count_view, name='row_count'),
    path('api/<uuid:connection_id>/all/', views.load_all_metadata_view, name='all_metadata'),
]



