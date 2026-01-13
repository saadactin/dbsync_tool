from django.contrib import admin
from .models import DatabaseConnection, ConnectionTestLog


@admin.register(DatabaseConnection)
class DatabaseConnectionAdmin(admin.ModelAdmin):
    """Admin interface for DatabaseConnection model"""
    list_display = ['name', 'db_type', 'host', 'port', 'database_name', 'is_active', 'created_by', 'created_at']
    list_filter = ['db_type', 'is_active', 'created_at']
    search_fields = ['name', 'host', 'database_name', 'username']
    readonly_fields = ['id', 'created_at', 'updated_at', 'password_display']
    fieldsets = (
        ('Connection Information', {
            'fields': ('name', 'db_type', 'host', 'port', 'database_name')
        }),
        ('Authentication', {
            'fields': ('username', 'password', 'password_display')
        }),
        ('Metadata', {
            'fields': ('created_by', 'is_active', 'created_at', 'updated_at', 'id')
        }),
    )
    
    def password_display(self, obj):
        """Display masked password"""
        if obj.password:
            return "••••••••"  # Masked password
        return "Not set"
    password_display.short_description = "Password (encrypted)"
    
    def save_model(self, request, obj, form, change):
        """Set created_by to current user if new object"""
        if not change:  # New object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ConnectionTestLog)
class ConnectionTestLogAdmin(admin.ModelAdmin):
    """Admin interface for ConnectionTestLog model"""
    list_display = ['connection', 'status', 'tested_by', 'tested_at']
    list_filter = ['status', 'tested_at']
    search_fields = ['connection__name', 'error_message']
    readonly_fields = ['id', 'tested_at']
    date_hierarchy = 'tested_at'
    
    fieldsets = (
        ('Test Information', {
            'fields': ('connection', 'status', 'tested_by')
        }),
        ('Error Details', {
            'fields': ('error_message',)
        }),
        ('Metadata', {
            'fields': ('id', 'tested_at')
        }),
    )
