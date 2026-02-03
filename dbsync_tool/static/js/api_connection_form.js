// API Connection Form JavaScript
// Handles form interactions, connection testing, and module selection

// Get CSRF token
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// Token URL mapping based on API domain
const TOKEN_URL_MAP = {
    'https://www.zohoapis.in': 'https://accounts.zoho.in/oauth/v2/token',
    'https://www.zohoapis.com': 'https://accounts.zoho.com/oauth/v2/token',
    'https://www.zohoapis.eu': 'https://accounts.zoho.eu/oauth/v2/token',
    'https://www.zohoapis.com.au': 'https://accounts.zoho.com.au/oauth/v2/token',
};

// Auto-populate token URL when API domain changes
function autoPopulateTokenUrl() {
    const apiDomainField = document.getElementById('id_api_domain');
    const tokenUrlField = document.getElementById('id_token_url');
    
    if (apiDomainField && tokenUrlField) {
        // Make token_url read-only and styled
        tokenUrlField.setAttribute('readonly', 'readonly');
        tokenUrlField.style.backgroundColor = '#e9ecef';
        tokenUrlField.style.cursor = 'not-allowed';
        
        // Set initial value if api_domain is already selected
        if (apiDomainField.value && TOKEN_URL_MAP[apiDomainField.value]) {
            tokenUrlField.value = TOKEN_URL_MAP[apiDomainField.value];
        }
        
        apiDomainField.addEventListener('change', function() {
            const selectedDomain = this.value;
            if (selectedDomain && TOKEN_URL_MAP[selectedDomain]) {
                tokenUrlField.value = TOKEN_URL_MAP[selectedDomain];
            } else {
                tokenUrlField.value = '';
            }
        });
    }
}

// Test connection handler
function handleTestConnection() {
    const testBtn = document.getElementById('test-connection-btn');
    const testText = document.getElementById('test-connection-text');
    const testSpinner = document.getElementById('test-connection-spinner');
    const testMessage = document.getElementById('test-connection-message');
    const moduleSection = document.getElementById('module-selection-section');
    const moduleCheckboxes = document.getElementById('module-checkboxes');
    const selectedModulesField = document.getElementById('id_selected_modules');
    const csrftoken = getCookie('csrftoken');
    
    if (!testBtn) return;
    
    testBtn.addEventListener('click', function() {
        // Collect form data
        const formData = {
            name: document.getElementById('id_name').value,
            api_type: document.getElementById('id_api_type').value,
            client_id: document.getElementById('id_client_id').value,
            client_secret: document.getElementById('id_client_secret').value,
            refresh_token: document.getElementById('id_refresh_token').value,
            api_domain: document.getElementById('id_api_domain').value,
            token_url: document.getElementById('id_token_url').value,
        };
        
        // Validate required fields
        if (!formData.client_id || !formData.client_secret || !formData.refresh_token || !formData.api_domain) {
            testMessage.innerHTML = '<div class="alert alert-danger">Please fill in all required fields before testing.</div>';
            return;
        }
        
        // Show loading state
        testBtn.disabled = true;
        testText.textContent = 'Testing...';
        testSpinner.classList.remove('d-none');
        testMessage.innerHTML = '';
        
        // Determine test URL
        const testUrl = typeof TEST_CONNECTION_URL !== 'undefined' ? TEST_CONNECTION_URL : '/connections/api/test/';
        
        // Send AJAX request
        fetch(testUrl, {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrftoken,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(formData),
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Show success message with green indicator
                testMessage.innerHTML = `<div class="alert alert-success">
                    <i class="bi bi-check-circle-fill"></i> <strong>Connection Successful!</strong> ${data.message}
                </div>`;
                
                // Change button to success state (green)
                testBtn.classList.remove('btn-info');
                testBtn.classList.add('btn-success');
                testText.textContent = '✓ Connection Successful';
                
                // Display modules if available
                if (data.modules && data.modules.length > 0) {
                    displayModuleSelection(data.modules, selectedModulesField);
                    moduleSection.style.display = 'block';
                } else {
                    testMessage.innerHTML += '<div class="alert alert-warning mt-2">No modules found.</div>';
                }
            } else {
                // Show error message
                testMessage.innerHTML = `<div class="alert alert-danger">
                    <i class="bi bi-x-circle-fill"></i> <strong>Connection Failed:</strong> ${data.message}
                </div>`;
                moduleSection.style.display = 'none';
                // Reset button state
                testBtn.classList.remove('btn-success');
                testBtn.classList.add('btn-info');
            }
        })
        .catch(error => {
            testMessage.innerHTML = `<div class="alert alert-danger">Error testing connection: ${error.message}</div>`;
            moduleSection.style.display = 'none';
            // Reset button state on error
            testBtn.classList.remove('btn-success');
            testBtn.classList.add('btn-info');
            testBtn.disabled = false;
            testText.textContent = 'Test Connection';
            testSpinner.classList.add('d-none');
        })
        .finally(() => {
            // Only reset spinner, keep button state if successful
            testSpinner.classList.add('d-none');
            // If not successful, ensure button is enabled
            if (!testBtn.classList.contains('btn-success')) {
                testBtn.disabled = false;
                testText.textContent = 'Test Connection';
            }
        });
    });
}

// Display module selection checkboxes
function displayModuleSelection(modules, selectedModulesField) {
    const moduleCheckboxes = document.getElementById('module-checkboxes');
    const moduleError = document.getElementById('module-selection-error');
    
    if (!moduleCheckboxes || !selectedModulesField) return;
    
    // Clear existing checkboxes
    moduleCheckboxes.innerHTML = '';
    
    // Get previously selected modules (if editing)
    let selectedModules = [];
    if (selectedModulesField.value) {
        try {
            selectedModules = JSON.parse(selectedModulesField.value);
        } catch (e) {
            selectedModules = [];
        }
    }
    
    // Create checkboxes for each module
    modules.forEach(module => {
        const isChecked = selectedModules.includes(module);
        const checkboxDiv = document.createElement('div');
        checkboxDiv.className = 'form-check';
        checkboxDiv.innerHTML = `
            <input class="form-check-input" type="checkbox" value="${module}" id="module_${module}" ${isChecked ? 'checked' : ''}>
            <label class="form-check-label" for="module_${module}">
                ${module}
            </label>
        `;
        moduleCheckboxes.appendChild(checkboxDiv);
    });
    
    // Update selected modules when checkboxes change
    moduleCheckboxes.addEventListener('change', function(e) {
        if (e.target.type === 'checkbox') {
            updateSelectedModules(selectedModulesField);
        }
    });
    
    // Initial update
    updateSelectedModules(selectedModulesField);
}

// Update selected modules hidden field
function updateSelectedModules(selectedModulesField) {
    const checkboxes = document.querySelectorAll('#module-checkboxes input[type="checkbox"]:checked');
    const selected = Array.from(checkboxes).map(cb => cb.value);
    
    if (selectedModulesField) {
        selectedModulesField.value = JSON.stringify(selected);
    }
    
    // Validate at least one module is selected
    const moduleError = document.getElementById('module-selection-error');
    const submitBtn = document.getElementById('submit-btn');
    
    if (selected.length === 0) {
        if (moduleError) {
            moduleError.textContent = 'Please select at least one module.';
            moduleError.style.display = 'block';
        }
        if (submitBtn) {
            submitBtn.disabled = true;
        }
    } else {
        if (moduleError) {
            moduleError.style.display = 'none';
        }
        if (submitBtn) {
            submitBtn.disabled = false;
        }
    }
}

// Load existing modules if editing
function loadExistingModules() {
    if (typeof MODULES_URL !== 'undefined' && MODULES_URL) {
        const csrftoken = getCookie('csrftoken');
        const selectedModulesField = document.getElementById('id_selected_modules');
        const moduleSection = document.getElementById('module-selection-section');
        const moduleCheckboxes = document.getElementById('module-checkboxes');
        
        fetch(MODULES_URL, {
            method: 'GET',
            headers: {
                'X-CSRFToken': csrftoken,
            },
        })
        .then(response => response.json())
        .then(data => {
            if (data.success && data.modules && data.modules.length > 0) {
                displayModuleSelection(data.modules, selectedModulesField);
                moduleSection.style.display = 'block';
            }
        })
        .catch(error => {
            console.error('Error loading modules:', error);
        });
    }
}

// Form submission validation
function setupFormValidation() {
    const form = document.getElementById('api-connection-form');
    const selectedModulesField = document.getElementById('id_selected_modules');
    
    if (form) {
        form.addEventListener('submit', function(e) {
            // Check if modules are selected
            if (selectedModulesField) {
                let selectedModules = [];
                try {
                    selectedModules = JSON.parse(selectedModulesField.value || '[]');
                } catch (e) {
                    selectedModules = [];
                }
                
                if (selectedModules.length === 0) {
                    e.preventDefault();
                    const moduleError = document.getElementById('module-selection-error');
                    if (moduleError) {
                        moduleError.textContent = 'Please test the connection and select at least one module before saving.';
                        moduleError.style.display = 'block';
                    }
                    const moduleSection = document.getElementById('module-selection-section');
                    if (moduleSection) {
                        moduleSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    }
                    return false;
                }
            }
        });
    }
}

// Initialize form when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    autoPopulateTokenUrl();
    handleTestConnection();
    loadExistingModules();
    setupFormValidation();
    
    // Update selected modules on checkbox change
    const moduleCheckboxes = document.getElementById('module-checkboxes');
    const selectedModulesField = document.getElementById('id_selected_modules');
    
    if (moduleCheckboxes && selectedModulesField) {
        moduleCheckboxes.addEventListener('change', function(e) {
            if (e.target.type === 'checkbox') {
                updateSelectedModules(selectedModulesField);
            }
        });
    }
});
