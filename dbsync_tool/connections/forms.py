"""
Forms for connection management
"""
from django import forms
from .models import DatabaseConnection
from core.constants import DB_TYPE_CHOICES, DEFAULT_PORTS


class DatabaseConnectionForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False, attrs={'class': 'form-control'}),
        required=True,
        help_text="Database password (will be encrypted)"
    )
    
    class Meta:
        model = DatabaseConnection
        fields = ['name', 'db_type', 'host', 'port', 'username', 'password', 'database_name', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'db_type': forms.Select(attrs={'class': 'form-control', 'id': 'id_db_type'}),
            'host': forms.TextInput(attrs={'class': 'form-control'}),
            'port': forms.NumberInput(attrs={'class': 'form-control', 'id': 'id_port'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'database_name': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set default port based on DB type
        if 'db_type' in self.data:
            db_type = self.data['db_type']
            if db_type in DEFAULT_PORTS:
                self.fields['port'].initial = DEFAULT_PORTS[db_type]
        elif self.instance and self.instance.pk:
            # Editing existing connection
            # Check if password needs to be reset
            if self.instance.password == 'RESET_REQUIRED' or not self.instance.password:
                self.fields['password'].required = True
                self.fields['password'].help_text = "⚠️ Password must be set. Previous password could not be decrypted."
                self.fields['password'].widget.attrs['class'] = 'form-control is-invalid'
            else:
                self.fields['password'].required = False
                self.fields['password'].help_text = "Leave blank to keep existing password"
        
        # For create mode (no instance), make database_name optional initially
        # JavaScript will populate it before submission
        if not self.instance or not self.instance.pk:
            self.fields['database_name'].required = False
    
    def clean_port(self):
        port = self.cleaned_data.get('port')
        if port and (port < 1 or port > 65535):
            raise forms.ValidationError("Port must be between 1 and 65535")
        return port
    
    def clean_database_name(self):
        database_name = self.cleaned_data.get('database_name')
        # Database name is required for final submission
        # For edit mode, use existing value if not provided
        if not database_name or not database_name.strip():
            if self.instance and self.instance.pk:
                # Edit mode: use existing database_name
                return self.instance.database_name
            else:
                # Create mode: must select database
                raise forms.ValidationError("Database name is required. Please select a database from the list after testing the connection.")
        return database_name.strip()
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        # Only update password if provided
        if 'password' in self.cleaned_data and self.cleaned_data['password']:
            instance.password = self.cleaned_data['password']
        if commit:
            instance.save()
        return instance
