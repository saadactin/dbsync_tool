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
    const endpointSection = document.getElementById('endpoint-selection-section');
    const selectedModulesField = document.getElementById('id_selected_modules');
    const sapEndpointsField = document.getElementById('id_sap_endpoints');
    const csrftoken = getCookie('csrftoken');
    
    if (!testBtn) return;
    
    testBtn.addEventListener('click', function() {
        const apiType = (document.getElementById('id_api_type') || {}).value;
        let formData;
        if (apiType === 'sap_b1') {
            formData = {
                name: document.getElementById('id_name').value,
                api_type: apiType,
                sap_base_url: (document.getElementById('id_sap_base_url') || {}).value,
                sap_user_name: (document.getElementById('id_sap_user_name') || {}).value,
                sap_company_db: (document.getElementById('id_sap_company_db') || {}).value,
                sap_password: (document.getElementById('id_sap_password') || {}).value,
            };
            var needPassword = (typeof IS_EDIT_MODE === 'undefined') ? true : !IS_EDIT_MODE;
            if (!formData.sap_base_url || !formData.sap_user_name || !formData.sap_company_db || (needPassword && !formData.sap_password)) {
                testMessage.innerHTML = '<div class="alert alert-danger">Please fill in SAP Base URL, User Name, Company DB' + (needPassword ? ', and Password' : '') + ' before testing. ' + (needPassword ? 'Check that the Base URL uses HTTPS (e.g. https://yourserver:50000/b1s/v2/).' : 'On edit, leave password blank to use the existing stored password.') + '</div>';
                return;
            }
        } else {
            formData = {
                name: document.getElementById('id_name').value,
                api_type: apiType || 'zoho_crm',
                client_id: (document.getElementById('id_client_id') || {}).value,
                client_secret: (document.getElementById('id_client_secret') || {}).value,
                refresh_token: (document.getElementById('id_refresh_token') || {}).value,
                api_domain: (document.getElementById('id_api_domain') || {}).value,
                token_url: (document.getElementById('id_token_url') || {}).value,
            };
            if (!formData.client_id || !formData.client_secret || !formData.refresh_token || !formData.api_domain) {
                testMessage.innerHTML = '<div class="alert alert-danger">Please fill in all required Zoho fields before testing.</div>';
                return;
            }
        }
        
        testBtn.disabled = true;
        testText.textContent = 'Testing...';
        testSpinner.classList.remove('d-none');
        testMessage.innerHTML = '';
        const testUrl = typeof TEST_CONNECTION_URL !== 'undefined' ? TEST_CONNECTION_URL : '/connections/api/test/';
        
        fetch(testUrl, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrftoken, 'Content-Type': 'application/json' },
            body: JSON.stringify(formData),
        })
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.success) {
                testMessage.innerHTML = '<div class="alert alert-success"><i class="bi bi-check-circle-fill"></i> <strong>Connection Successful!</strong> ' + data.message + '</div>';
                testBtn.classList.remove('btn-info');
                testBtn.classList.add('btn-success');
                testText.textContent = '✓ Connection Successful';
                if (apiType === 'sap_b1') {
                    const endpoints = data.endpoints || data.modules || (typeof SAP_DOCUMENT_TYPES !== 'undefined' ? SAP_DOCUMENT_TYPES : []);
                    if (endpoints && endpoints.length > 0) {
                        var existingSelected = sapEndpointsField && sapEndpointsField.value ? (function() { try { return JSON.parse(sapEndpointsField.value); } catch (e) { return []; } })() : [];
                        displayEndpointSelection(endpoints, sapEndpointsField, existingSelected.length > 0 ? existingSelected : endpoints);
                        if (endpointSection) endpointSection.style.display = 'block';
                    } else {
                        if (typeof SAP_DOCUMENT_TYPES !== 'undefined' && SAP_DOCUMENT_TYPES.length > 0) {
                            displayEndpointSelection(SAP_DOCUMENT_TYPES, sapEndpointsField, SAP_DOCUMENT_TYPES);
                            if (endpointSection) endpointSection.style.display = 'block';
                        } else {
                            testMessage.innerHTML += '<div class="alert alert-warning mt-2">No endpoints list available. Select endpoints below if shown.</div>';
                        }
                    }
                    if (moduleSection) moduleSection.style.display = 'none';
                } else {
                    if (data.modules && data.modules.length > 0) {
                        displayModuleSelection(data.modules, selectedModulesField);
                        if (moduleSection) moduleSection.style.display = 'block';
                    } else {
                        testMessage.innerHTML += '<div class="alert alert-warning mt-2">No modules found.</div>';
                    }
                    if (endpointSection) endpointSection.style.display = 'none';
                }
            } else {
                testMessage.innerHTML = '<div class="alert alert-danger"><i class="bi bi-x-circle-fill"></i> <strong>Connection Failed:</strong> ' + data.message + '</div>';
                if (moduleSection) moduleSection.style.display = 'none';
                if (endpointSection) endpointSection.style.display = 'none';
                testBtn.classList.remove('btn-success');
                testBtn.classList.add('btn-info');
            }
        })
        .catch(function(error) {
            testMessage.innerHTML = '<div class="alert alert-danger">Error testing connection: ' + error.message + '</div>';
            if (moduleSection) moduleSection.style.display = 'none';
            if (endpointSection) endpointSection.style.display = 'none';
            testBtn.classList.remove('btn-success');
            testBtn.classList.add('btn-info');
            testBtn.disabled = false;
            testText.textContent = 'Test Connection';
            testSpinner.classList.add('d-none');
        })
        .finally(function() {
            testSpinner.classList.add('d-none');
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

// Load existing modules or endpoints if editing
function loadExistingModules() {
    if (typeof MODULES_URL === 'undefined' || !MODULES_URL) return;
    const apiTypeSelect = document.getElementById('id_api_type');
    const apiType = apiTypeSelect ? apiTypeSelect.value : '';
    const csrftoken = getCookie('csrftoken');
    const selectedModulesField = document.getElementById('id_selected_modules');
    const sapEndpointsField = document.getElementById('id_sap_endpoints');
    const moduleSection = document.getElementById('module-selection-section');
    const endpointSection = document.getElementById('endpoint-selection-section');
    fetch(MODULES_URL, { method: 'GET', headers: { 'X-CSRFToken': csrftoken } })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            if (apiType === 'sap_b1') {
                const endpoints = data.modules || (typeof SAP_DOCUMENT_TYPES !== 'undefined' ? SAP_DOCUMENT_TYPES : []);
                const selected = data.selected || (sapEndpointsField && sapEndpointsField.value ? (function() { try { return JSON.parse(sapEndpointsField.value); } catch (e) { return []; } })() : []);
                if (endpoints && endpoints.length > 0) {
                    displayEndpointSelection(endpoints, sapEndpointsField, selected);
                    if (endpointSection) endpointSection.style.display = 'block';
                }
            } else if (data.modules && data.modules.length > 0) {
                displayModuleSelection(data.modules, selectedModulesField);
                if (moduleSection) moduleSection.style.display = 'block';
            }
        })
        .catch(function(error) { console.error('Error loading modules/endpoints:', error); });
}

// Form submission validation
function setupFormValidation() {
    const form = document.getElementById('api-connection-form');
    const selectedModulesField = document.getElementById('id_selected_modules');
    const sapEndpointsField = document.getElementById('id_sap_endpoints');
    const apiTypeSelect = document.getElementById('id_api_type');
    if (!form) return;
    form.addEventListener('submit', function(e) {
        const apiType = apiTypeSelect ? apiTypeSelect.value : 'zoho_crm';
        if (apiType === 'sap_b1') {
            var endpointsList = (typeof SAP_DOCUMENT_TYPES !== 'undefined' && Array.isArray(SAP_DOCUMENT_TYPES)) ? SAP_DOCUMENT_TYPES : [];
            if (sapEndpointsField && endpointsList.length > 0) {
                updateSapEndpoints(sapEndpointsField, endpointsList);
            }
            var checkedCbs = document.querySelectorAll('#endpoint-checkboxes input.endpoint-cb:checked');
            if (checkedCbs.length === 0) {
                e.preventDefault();
                alert('Select at least one endpoint.');
                var endpointError = document.getElementById('endpoint-selection-error');
                if (endpointError) {
                    endpointError.textContent = 'Select at least one endpoint.';
                    endpointError.style.display = 'block';
                }
                var endpointSection = document.getElementById('endpoint-selection-section');
                if (endpointSection) endpointSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                return false;
            }
            var endpoints = [];
            try {
                endpoints = sapEndpointsField && sapEndpointsField.value ? JSON.parse(sapEndpointsField.value) : [];
            } catch (err) { endpoints = []; }
            if (!Array.isArray(endpoints) || endpoints.length === 0) {
                var list = endpointsList.length > 0 ? endpointsList : [];
                var fallback = [];
                checkedCbs.forEach(function(cb) {
                    var key = cb.value;
                    var obj = list.find(function(e) { return (e.endpoint || e) === key; });
                    fallback.push(obj || { endpoint: key, name: key, id_field: '' });
                });
                if (sapEndpointsField && fallback.length > 0) {
                    sapEndpointsField.value = JSON.stringify(fallback);
                }
            }
        } else {
            let selectedModules = [];
            try {
                selectedModules = selectedModulesField && selectedModulesField.value ? JSON.parse(selectedModulesField.value || '[]') : [];
            } catch (err) { selectedModules = []; }
            if (selectedModules.length === 0) {
                e.preventDefault();
                const moduleError = document.getElementById('module-selection-error');
                if (moduleError) {
                    moduleError.textContent = 'Please test the connection and select at least one module before saving.';
                    moduleError.style.display = 'block';
                }
                const moduleSection = document.getElementById('module-selection-section');
                if (moduleSection) moduleSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                return false;
            }
        }
    });
}

// Toggle Zoho vs SAP fields and sections by API type
function toggleApiTypeSections() {
    const apiTypeSelect = document.getElementById('id_api_type');
    const zohoFields = document.getElementById('zoho-fields');
    const sapFields = document.getElementById('sap-fields');
    const moduleSection = document.getElementById('module-selection-section');
    const endpointSection = document.getElementById('endpoint-selection-section');
    const sapEndpointsField = document.getElementById('id_sap_endpoints');
    if (!apiTypeSelect) return;
    const apiType = apiTypeSelect.value;
    if (apiType === 'sap_b1') {
        if (zohoFields) zohoFields.style.display = 'none';
        if (sapFields) sapFields.style.display = 'block';
        if (moduleSection) moduleSection.style.display = 'none';
        if (endpointSection) endpointSection.style.display = 'block';
        if (typeof SAP_DOCUMENT_TYPES !== 'undefined' && Array.isArray(SAP_DOCUMENT_TYPES) && SAP_DOCUMENT_TYPES.length > 0 && sapEndpointsField) {
            let selected = [];
            try { selected = sapEndpointsField.value ? JSON.parse(sapEndpointsField.value) : []; } catch (e) { selected = []; }
            displayEndpointSelection(SAP_DOCUMENT_TYPES, sapEndpointsField, selected.length > 0 ? selected : SAP_DOCUMENT_TYPES);
        }
    } else {
        if (zohoFields) zohoFields.style.display = 'block';
        if (sapFields) sapFields.style.display = 'none';
        if (moduleSection) moduleSection.style.display = 'block';
        if (endpointSection) endpointSection.style.display = 'none';
    }
}

// Display SAP endpoint selection checkboxes
function displayEndpointSelection(endpoints, selectedEndpointsField, selectedList) {
    const container = document.getElementById('endpoint-checkboxes');
    const selectAllCb = document.getElementById('sap-select-all-cb');
    const endpointError = document.getElementById('endpoint-selection-error');
    if (!container || !selectedEndpointsField) return;
    container.innerHTML = '';
    const selected = selectedList || [];
    const selectedKeys = new Set(selected.map(function(e) { return e && e.endpoint ? e.endpoint : e; }));
    endpoints.forEach(function(ep) {
        const endpointKey = typeof ep === 'object' ? ep.endpoint : ep;
        const label = typeof ep === 'object' ? (ep.name || ep.endpoint) : ep;
        const isChecked = selectedKeys.has(endpointKey);
        const div = document.createElement('div');
        div.className = 'form-check';
        div.innerHTML = '<input class="form-check-input endpoint-cb" type="checkbox" value="' +
            endpointKey + '" id="endpoint_' + endpointKey + '" ' + (isChecked ? 'checked' : '') + '>' +
            '<label class="form-check-label" for="endpoint_' + endpointKey + '">' + label + '</label>';
        container.appendChild(div);
    });
    if (selectAllCb) {
        selectAllCb.checked = endpoints.length > 0 && selectedKeys.size === endpoints.length;
        selectAllCb.onchange = function() {
            const check = selectAllCb.checked;
            container.querySelectorAll('input.endpoint-cb').forEach(function(cb) { cb.checked = check; });
            updateSapEndpoints(selectedEndpointsField, endpoints);
        };
    }
    container.onchange = function() {
        updateSapEndpoints(selectedEndpointsField, endpoints);
        if (selectAllCb) {
            const all = container.querySelectorAll('input.endpoint-cb');
            selectAllCb.checked = all.length > 0 && all.length === container.querySelectorAll('input.endpoint-cb:checked').length;
        }
    };
    updateSapEndpoints(selectedEndpointsField, endpoints);
}

// Update sap_endpoints hidden field from endpoint checkboxes
function updateSapEndpoints(selectedEndpointsField, endpointsList) {
    const checkboxes = document.querySelectorAll('#endpoint-checkboxes input.endpoint-cb:checked');
    const endpoints = typeof SAP_DOCUMENT_TYPES !== 'undefined' && Array.isArray(SAP_DOCUMENT_TYPES) ? SAP_DOCUMENT_TYPES : (endpointsList || []);
    const selected = [];
    checkboxes.forEach(function(cb) {
        const key = cb.value;
        const obj = endpoints.find(function(e) { return (e.endpoint || e) === key; });
        selected.push(obj || { endpoint: key, name: key, id_field: '' });
    });
    if (selectedEndpointsField) {
        selectedEndpointsField.value = JSON.stringify(selected);
    }
    const endpointError = document.getElementById('endpoint-selection-error');
    const submitBtn = document.getElementById('submit-btn');
    if (selected.length === 0) {
        if (endpointError) { endpointError.textContent = 'Select at least one endpoint.'; endpointError.style.display = 'block'; }
        if (submitBtn) submitBtn.disabled = true;
    } else {
        if (endpointError) endpointError.style.display = 'none';
        if (submitBtn) submitBtn.disabled = false;
    }
}

// Initialize form when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    const apiTypeSelect = document.getElementById('id_api_type');
    if (apiTypeSelect) {
        toggleApiTypeSections();
        apiTypeSelect.addEventListener('change', toggleApiTypeSections);
    }
    autoPopulateTokenUrl();
    handleTestConnection();
    loadExistingModules();
    setupFormValidation();
    
    const moduleCheckboxes = document.getElementById('module-checkboxes');
    const selectedModulesField = document.getElementById('id_selected_modules');
    if (moduleCheckboxes && selectedModulesField) {
        moduleCheckboxes.addEventListener('change', function(e) {
            if (e.target.type === 'checkbox') updateSelectedModules(selectedModulesField);
        });
    }
    const endpointCheckboxes = document.getElementById('endpoint-checkboxes');
    const sapEndpointsField = document.getElementById('id_sap_endpoints');
    if (endpointCheckboxes && sapEndpointsField && typeof SAP_DOCUMENT_TYPES !== 'undefined' && Array.isArray(SAP_DOCUMENT_TYPES)) {
        endpointCheckboxes.addEventListener('change', function() {
            updateSapEndpoints(sapEndpointsField, SAP_DOCUMENT_TYPES);
        });
    }
});
