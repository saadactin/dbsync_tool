// JavaScript for connection form dynamic port defaults and database selection flow
document.addEventListener('DOMContentLoaded', function() {
    const dbTypeSelect = document.getElementById('id_db_type');
    const portInput = document.getElementById('id_port');
    const testConnectionBtn = document.getElementById('test-connection-btn');
    const testConnectionBtnEdit = document.getElementById('test-connection-btn-edit');
    const databaseSelect = document.getElementById('database-select');
    const databaseNameField = document.getElementById('database-name-field');
    const databaseNameInput = document.getElementById('id_database_name');
    const databaseSelectionSection = document.getElementById('database-selection-section');
    const form = document.querySelector('form');
    
    const defaultPorts = {
        'postgres': '5432',
        'mysql': '3306',
        'sqlserver': '1433',
        'clickhouse': '9000'
    };
    
    // Set default port based on database type
    if (dbTypeSelect && portInput) {
        dbTypeSelect.addEventListener('change', function() {
            const selectedType = this.value;
            if (selectedType in defaultPorts && !portInput.value) {
                portInput.value = defaultPorts[selectedType];
            }
        });
    }
    
    // Test connection and list databases (only for create mode)
    if (testConnectionBtn) {
        testConnectionBtn.addEventListener('click', function() {
            // Get form values
            const name = document.getElementById('id_name').value.trim();
            const dbType = document.getElementById('id_db_type').value;
            const host = document.getElementById('id_host').value.trim();
            const port = document.getElementById('id_port').value.trim();
            const username = document.getElementById('id_username').value.trim();
            const password = document.getElementById('id_password').value;
            
            // Validate required fields
            if (!name || !dbType || !host || !port || !username || !password) {
                showTestMessage('Please fill in all required fields (Name, Database Type, Host, Port, Username, Password)', 'danger');
                return;
            }
            
            // Validate port
            const portNum = parseInt(port);
            if (isNaN(portNum) || portNum < 1 || portNum > 65535) {
                showTestMessage('Port must be a number between 1 and 65535', 'danger');
                return;
            }
            
            // Show loading state
            testConnectionBtn.disabled = true;
            document.getElementById('test-connection-text').textContent = 'Testing...';
            document.getElementById('test-connection-spinner').classList.remove('d-none');
            showTestMessage('', '');
            
            // Prepare request data
            const requestData = {
                db_type: dbType,
                host: host,
                port: portNum,
                username: username,
                password: password
            };
            
            // Get CSRF token
            const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
            if (!csrfInput) {
                showTestMessage('CSRF token not found. Please refresh the page.', 'danger');
                testConnectionBtn.disabled = false;
                document.getElementById('test-connection-text').textContent = 'Test Connection';
                document.getElementById('test-connection-spinner').classList.add('d-none');
                return;
            }
            const csrfToken = csrfInput.value;
            
            // Check if URL is defined
            if (typeof TEST_AND_LIST_DATABASES_URL === 'undefined') {
                showTestMessage('Configuration error. Please refresh the page.', 'danger');
                testConnectionBtn.disabled = false;
                document.getElementById('test-connection-text').textContent = 'Test Connection';
                document.getElementById('test-connection-spinner').classList.add('d-none');
                return;
            }
            
            // Make AJAX request
            fetch(TEST_AND_LIST_DATABASES_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify(requestData)
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                testConnectionBtn.disabled = false;
                document.getElementById('test-connection-text').textContent = 'Test Connection';
                document.getElementById('test-connection-spinner').classList.add('d-none');
                
                if (data.success) {
                    showTestMessage(data.message, 'success');
                    
                    // Populate database dropdown
                    if (data.databases && data.databases.length > 0) {
                        databaseSelect.innerHTML = '<option value="">-- Select a database --</option>';
                        data.databases.forEach(db => {
                            const option = document.createElement('option');
                            option.value = db;
                            option.textContent = db;
                            databaseSelect.appendChild(option);
                        });
                        
                        // Show database selection section
                        databaseSelectionSection.style.display = 'block';
                        
                        // Show database name field (hidden)
                        if (databaseNameField) {
                            databaseNameField.style.display = 'block';
                        }
                    } else {
                        showTestMessage('Connection successful but no databases found.', 'warning');
                    }
                } else {
                    showTestMessage(data.message || 'Connection test failed', 'danger');
                    // Hide database selection if it was shown
                    databaseSelectionSection.style.display = 'none';
                    if (databaseNameField) {
                        databaseNameField.style.display = 'none';
                    }
                }
            })
            .catch(error => {
                console.error('Connection test error:', error);
                testConnectionBtn.disabled = false;
                const testText = document.getElementById('test-connection-text');
                const testSpinner = document.getElementById('test-connection-spinner');
                if (testText) testText.textContent = 'Test Connection';
                if (testSpinner) testSpinner.classList.add('d-none');
                showTestMessage('An error occurred while testing the connection: ' + error.message, 'danger');
                if (databaseSelectionSection) databaseSelectionSection.style.display = 'none';
                if (databaseNameField) {
                    databaseNameField.style.display = 'none';
                }
            });
        });
    }
    
    // Handle database selection
    if (databaseSelect) {
        databaseSelect.addEventListener('change', function() {
            const selectedDatabase = this.value;
            if (selectedDatabase && databaseNameInput) {
                databaseNameInput.value = selectedDatabase;
                // Clear any validation errors
                const errorDiv = document.getElementById('database-selection-error');
                if (errorDiv) {
                    errorDiv.style.display = 'none';
                    errorDiv.textContent = '';
                }
            } else if (databaseNameInput) {
                databaseNameInput.value = '';
            }
        });
    }
    
    // Validate form before submission (for create mode only)
    if (form && testConnectionBtn) {
        // This is create mode (test connection button exists)
        form.addEventListener('submit', function(e) {
            // Check if database is selected
            if (databaseSelect && databaseSelect.style.display !== 'none') {
                const selectedDatabase = databaseSelect.value;
                if (!selectedDatabase) {
                    e.preventDefault();
                    const errorDiv = document.getElementById('database-selection-error');
                    if (errorDiv) {
                        errorDiv.textContent = 'Please select a database before submitting';
                        errorDiv.style.display = 'block';
                    }
                    databaseSelect.focus();
                    return false;
                }
            }
            
            // Ensure database_name field has value
            if (databaseNameInput && !databaseNameInput.value.trim()) {
                e.preventDefault();
                const errorDiv = document.getElementById('database-selection-error');
                if (errorDiv) {
                    errorDiv.textContent = 'Please select a database before submitting';
                    errorDiv.style.display = 'block';
                }
                if (databaseSelect) {
                    databaseSelect.focus();
                }
                return false;
            }
        });
    }
    
    // Test connection in edit mode (uses existing connection)
    if (testConnectionBtnEdit && typeof TEST_CONNECTION_URL !== 'undefined') {
        testConnectionBtnEdit.addEventListener('click', function() {
            // Show loading state
            testConnectionBtnEdit.disabled = true;
            const testTextEdit = document.getElementById('test-connection-text-edit');
            const testSpinnerEdit = document.getElementById('test-connection-spinner-edit');
            if (testTextEdit) testTextEdit.textContent = 'Testing...';
            if (testSpinnerEdit) testSpinnerEdit.classList.remove('d-none');
            showTestMessageEdit('', '');
            
            // Get CSRF token
            const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
            if (!csrfInput) {
                showTestMessageEdit('CSRF token not found. Please refresh the page.', 'danger');
                testConnectionBtnEdit.disabled = false;
                if (testTextEdit) testTextEdit.textContent = 'Test Connection';
                if (testSpinnerEdit) testSpinnerEdit.classList.add('d-none');
                return;
            }
            const csrfToken = csrfInput.value;
            
            // Make AJAX request to test existing connection
            fetch(TEST_CONNECTION_URL, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                testConnectionBtnEdit.disabled = false;
                if (testTextEdit) testTextEdit.textContent = 'Test Connection';
                if (testSpinnerEdit) testSpinnerEdit.classList.add('d-none');
                
                if (data.success) {
                    showTestMessageEdit(data.message || 'Connection test successful!', 'success');
                } else {
                    showTestMessageEdit(data.message || 'Connection test failed', 'danger');
                }
            })
            .catch(error => {
                console.error('Connection test error:', error);
                testConnectionBtnEdit.disabled = false;
                if (testTextEdit) testTextEdit.textContent = 'Test Connection';
                if (testSpinnerEdit) testSpinnerEdit.classList.add('d-none');
                showTestMessageEdit('An error occurred while testing the connection: ' + error.message, 'danger');
            });
        });
    }
    
    // Helper function to show test connection messages (create mode)
    function showTestMessage(message, type) {
        const messageDiv = document.getElementById('test-connection-message');
        if (!messageDiv) return;
        
        if (!message) {
            messageDiv.innerHTML = '';
            messageDiv.className = 'mt-2';
            return;
        }
        
        const alertClass = type === 'success' ? 'alert-success' : 
                          type === 'danger' ? 'alert-danger' : 
                          type === 'warning' ? 'alert-warning' : 'alert-info';
        
        messageDiv.innerHTML = `<div class="alert ${alertClass} alert-dismissible fade show" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>`;
        messageDiv.className = 'mt-2';
    }
    
    // Helper function to show test connection messages (edit mode)
    function showTestMessageEdit(message, type) {
        const messageDiv = document.getElementById('test-connection-message-edit');
        if (!messageDiv) return;
        
        if (!message) {
            messageDiv.innerHTML = '';
            messageDiv.className = 'mt-2';
            return;
        }
        
        const alertClass = type === 'success' ? 'alert-success' : 
                          type === 'danger' ? 'alert-danger' : 
                          type === 'warning' ? 'alert-warning' : 'alert-info';
        
        messageDiv.innerHTML = `<div class="alert ${alertClass} alert-dismissible fade show" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>`;
        messageDiv.className = 'mt-2';
    }
});

