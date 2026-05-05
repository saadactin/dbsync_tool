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
    const databaseNameLabel = document.getElementById('database-name-label');
    const databaseNameHelp = document.getElementById('database-name-help');
    const oracleAdwHint = document.getElementById('oracle-adw-hint');
    
    const defaultPorts = {
        'postgres': '5432',
        'mysql': '3306',
        'sqlserver': '1433',
        'clickhouse': '9000',
        'oracle_adw': '1522',
        'mongodb': '27017',
    };

    function isLocalMongoHost(host) {
        const h = (host || '').trim().toLowerCase();
        return h === 'localhost' || h === '127.0.0.1' || h === '::1';
    }

    function mongoLocalCredentialsOk(host, username, password) {
        if (!isLocalMongoHost(host)) {
            return !!(username && password);
        }
        const u = (username || '').trim();
        const p = password || '';
        if (!u && !p) return true;
        return !!(u && p);
    }
    
    function updateDbTypeUI() {
        if (!dbTypeSelect) return;
        const selectedType = dbTypeSelect.value;

        // Set default port if empty and we know a default for this type
        if (portInput && selectedType in defaultPorts && !portInput.value) {
            portInput.value = defaultPorts[selectedType];
        }

        const isOracle = selectedType === 'oracle_adw';
        const isMongo = selectedType === 'mongodb';

        // Toggle Oracle-specific hint
        if (oracleAdwHint) {
            oracleAdwHint.style.display = isOracle ? 'block' : 'none';
        }

        // Set or clear placeholders for Oracle
        const hostInput = document.getElementById('id_host');
        if (hostInput) {
            hostInput.placeholder = isOracle ? 'adw-instance.region.tenant.oraclecloud.com' : '';
            hostInput.title = isOracle ? 'Oracle ADW host from your cloud console or connection string.' : '';
        }
        if (portInput) {
            portInput.placeholder = isOracle ? '1522' : '';
        }
        if (databaseNameInput) {
            databaseNameInput.placeholder = isOracle ? 'mytpdb_high' : '';
            databaseNameInput.title = isOracle ? 'Use the service name from your JDBC/connection string (e.g. mytpdb_high). Required for Oracle ADW.' : '';
        }

        // Adjust database/service name label & help text
        if (databaseNameLabel) {
            if (isOracle) {
                databaseNameLabel.textContent = 'Service Name (Oracle ADW) *';
            } else if (isMongo) {
                databaseNameLabel.textContent = 'Database Name (optional for MongoDB)';
            } else {
                databaseNameLabel.textContent = 'Database Name *';
            }
        }
        if (databaseNameHelp) {
            if (isOracle) {
                databaseNameHelp.textContent =
                    'Use the Oracle ADW service name from your JDBC/connection string, e.g. mytpdb_high.';
            } else if (isMongo) {
                databaseNameHelp.textContent =
                    'Leave empty for typical `root` users (auth defaults apply). Pick a database after testing.';
            } else {
                databaseNameHelp.textContent =
                    'Select a database from the list below after testing connection';
            }
        }

        // For Oracle ADW always show the Service Name field; on create form hide it for other types.
        if (databaseNameField) {
            databaseNameField.style.display = isOracle ? 'block' : (databaseNameField.dataset.createForm === 'true' ? 'none' : 'block');
        }
        if (databaseSelectionSection) {
            databaseSelectionSection.style.display = isOracle ? 'none' : (databaseSelectionSection.style.display || 'none');
        }
    }

    // Set default port and Oracle-specific UI based on database type
    if (dbTypeSelect) {
        dbTypeSelect.addEventListener('change', updateDbTypeUI);
        // Initialize on load
        updateDbTypeUI();
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
            const databaseName = databaseNameInput ? databaseNameInput.value.trim() : '';
            
            // Validate required fields
            const credsOk =
                dbType === 'mongodb'
                    ? mongoLocalCredentialsOk(host, username, password)
                    : !!(username && password);

            if (!name || !dbType || !host || !port || !credsOk ||
                (dbType === 'oracle_adw' && !databaseName)) {
                if (dbType === 'oracle_adw' && !databaseName) {
                    showTestMessage('Service name is required for Oracle ADW before testing the connection.', 'danger');
                } else if (dbType === 'mongodb' && !credsOk) {
                    showTestMessage(
                        'For MongoDB, provide both Username and Password (or leave both empty for local root/root default).',
                        'danger'
                    );
                } else {
                    showTestMessage('Please fill in all required fields (Name, Database Type, Host, Port, Username, Password)', 'danger');
                }
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
                name: name,
                db_type: dbType,
                host: host,
                port: portNum,
                username: username,
                password: password
            };
            if (databaseName) {
                requestData.database_name = databaseName;
            }
            
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
            .then(response => response.text().then(text => ({ response, text })))
            .then(({ response, text }) => {
                testConnectionBtn.disabled = false;
                document.getElementById('test-connection-text').textContent = 'Test Connection';
                document.getElementById('test-connection-spinner').classList.add('d-none');

                const parsed = parseConnectionTestResponse(response, text);
                if (!parsed.ok) {
                    showTestMessage(parsed.errorMessage, 'danger');
                    if (typeof showConnectionTestModal === 'function') {
                        showConnectionTestModal({
                            success: false,
                            message: parsed.errorMessage || 'Invalid response from server.',
                            details: {}
                        }, { title: 'Connection Test Failed' });
                    }
                    return;
                }
                const data = parsed.data;

                if (data.success) {
                    showTestMessage(formatConnectionTestMessageHtml(data), 'success');

                    if (data.databases && data.databases.length > 0) {
                        databaseSelect.innerHTML = '<option value="">-- Select a database --</option>';
                        data.databases.forEach(db => {
                            const option = document.createElement('option');
                            option.value = db;
                            option.textContent = db;
                            databaseSelect.appendChild(option);
                        });

                        databaseSelectionSection.style.display = 'block';

                        if (databaseNameField) {
                            databaseNameField.style.display = 'block';
                        }
                    } else {
                        showTestMessage(
                            formatConnectionTestMessageHtml({
                                success: true,
                                message: 'Connection successful but no databases found.',
                                latency_ms: data.latency_ms,
                                details: data.details,
                            }),
                            'warning'
                        );
                    }
                } else {
                    showTestMessage(formatConnectionTestMessageHtml(data), 'danger');
                    if (typeof showConnectionTestModal === 'function') {
                        showConnectionTestModal(data, { title: 'Connection Test Failed' });
                    }
                    databaseSelectionSection.style.display = 'none';
                    if (databaseNameField && (!dbTypeSelect || dbTypeSelect.value !== 'oracle_adw')) {
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
                if (typeof showConnectionTestModal === 'function') {
                    showConnectionTestModal({
                        success: false,
                        message: 'An error occurred while testing the connection: ' + error.message,
                        details: {}
                    }, { title: 'Connection Test Failed' });
                }
                if (databaseSelectionSection) databaseSelectionSection.style.display = 'none';
                if (databaseNameField && (!dbTypeSelect || dbTypeSelect.value !== 'oracle_adw')) {
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
            .then(response => response.text().then(text => ({ response, text })))
            .then(({ response, text }) => {
                testConnectionBtnEdit.disabled = false;
                if (testTextEdit) testTextEdit.textContent = 'Test Connection';
                if (testSpinnerEdit) testSpinnerEdit.classList.add('d-none');

                const parsed = parseConnectionTestResponse(response, text);
                if (!parsed.ok) {
                    showTestMessageEdit(parsed.errorMessage, 'danger');
                    if (typeof showConnectionTestModal === 'function') {
                        showConnectionTestModal({
                            success: false,
                            message: parsed.errorMessage || 'Invalid response from server.',
                            details: {}
                        }, { title: 'Connection Test Failed' });
                    }
                    return;
                }
                const data = parsed.data;
                showTestMessageEdit(
                    formatConnectionTestMessageHtml(data),
                    data.success ? 'success' : 'danger'
                );
                if (!data.success && typeof showConnectionTestModal === 'function') {
                    showConnectionTestModal(data, { title: 'Connection Test Failed' });
                }
            })
            .catch(error => {
                console.error('Connection test error:', error);
                testConnectionBtnEdit.disabled = false;
                if (testTextEdit) testTextEdit.textContent = 'Test Connection';
                if (testSpinnerEdit) testSpinnerEdit.classList.add('d-none');
                showTestMessageEdit('An error occurred while testing the connection: ' + error.message, 'danger');
                if (typeof showConnectionTestModal === 'function') {
                    showConnectionTestModal({
                        success: false,
                        message: 'An error occurred while testing the connection: ' + error.message,
                        details: {}
                    }, { title: 'Connection Test Failed' });
                }
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

