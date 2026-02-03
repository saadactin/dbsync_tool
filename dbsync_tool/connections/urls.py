from django.urls import path
from . import views

app_name = 'connections'

urlpatterns = [
    # Database connection URLs
    path('', views.ConnectionListView.as_view(), name='list'),
    path('create/', views.ConnectionCreateView.as_view(), name='create'),
    path('<uuid:pk>/', views.ConnectionDetailView.as_view(), name='detail'),
    path('<uuid:pk>/edit/', views.ConnectionUpdateView.as_view(), name='update'),
    path('<uuid:pk>/delete/', views.ConnectionDeleteView.as_view(), name='delete'),
    path('<uuid:pk>/test/', views.ConnectionTestView.as_view(), name='test'),
    path('test-and-list-databases/', views.ConnectionTestAndListDatabasesView.as_view(), name='test_and_list_databases'),
    
    # API connection URLs
    path('api/', views.APIConnectionListView.as_view(), name='api_list'),
    path('api/create/', views.APIConnectionCreateView.as_view(), name='api_create'),
    path('api/<uuid:pk>/', views.APIConnectionDetailView.as_view(), name='api_detail'),
    path('api/<uuid:pk>/edit/', views.APIConnectionUpdateView.as_view(), name='api_update'),
    path('api/<uuid:pk>/delete/', views.APIConnectionDeleteView.as_view(), name='api_delete'),
    path('api/<uuid:pk>/test/', views.APIConnectionTestView.as_view(), name='api_test'),
    path('api/test/', views.APIConnectionTestView.as_view(), name='api_test_new'),
    path('api/<uuid:pk>/modules/', views.APIConnectionModulesView.as_view(), name='api_modules'),
]
