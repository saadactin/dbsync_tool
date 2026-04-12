/**
 * Step 2: Table selection functionality with lazy loading
 * Loads schemas first, then tables on demand when user expands schema
 */

// Global safeguard: Prevent innerHTML assignment on null elements
(function() {
    const originalSetProperty = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML') || 
                                 Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'innerHTML');
    
    if (originalSetProperty && originalSetProperty.set) {
        Object.defineProperty(Element.prototype, 'innerHTML', {
            set: function(value) {
                if (this === null || this === undefined) {
                    console.error('Attempted to set innerHTML on null/undefined element. Stack:', new Error().stack);
                    return;
                }
                try {
                    originalSetProperty.set.call(this, value);
                } catch (e) {
                    console.error('Error setting innerHTML:', e, 'Element:', this, 'Value:', value);
                    throw e;
                }
            },
            get: originalSetProperty.get,
            configurable: true
        });
    }
})();

// Global error handler to catch any unhandled errors
window.addEventListener('error', function(event) {
    console.error('Global error caught:', event.error, event.filename, event.lineno, event.colno);
    try {
        const errorMsg = document.getElementById('error-message');
        if (errorMsg) {
            // Use textContent instead of innerHTML to avoid any issues
            errorMsg.textContent = `An unexpected error occurred: ${event.error ? event.error.message : 'Unknown error'}. Please refresh the page.`;
            errorMsg.style.display = 'block';
        } else {
            console.error('Error message element not found in global error handler');
            alert(`An unexpected error occurred: ${event.error ? event.error.message : 'Unknown error'}. Please refresh the page.`);
        }
    } catch (e) {
        console.error('Error in global error handler:', e);
        alert(`An unexpected error occurred. Please refresh the page.`);
    }
});

document.addEventListener('DOMContentLoaded', function() {
    try {
    function getDisplayErrorText(error, fallback = 'Unknown error occurred. Please check the browser console for details.') {
        if (error === null || error === undefined) return fallback;
        if (typeof error === 'string') return error;
        if (error instanceof Error && typeof error.message === 'string') {
            return error.message;
        }
        if (typeof error === 'object') {
            if (typeof error.message === 'string') return error.message;
            if (typeof error.error === 'string') return error.error;
            if (typeof error.detail === 'string') return error.detail;
            try {
                return JSON.stringify(error);
            } catch (e) {
                return fallback;
            }
        }
        return String(error);
    }

    // Flat-file Step 2 mode (preview + target table persistence)
    const flatFileLoading = document.getElementById('flat-file-loading');
    if (flatFileLoading) {
        const flatFileError = document.getElementById('flat-file-error');
        const flatFileArea = document.getElementById('flat-file-preview-area');
        const statsEl = document.getElementById('flat-file-stats');
        const headEl = document.getElementById('flat-file-preview-head');
        const bodyEl = document.getElementById('flat-file-preview-body');
        const tableNameInput = document.getElementById('target_table_name');
        const hiddenTableName = document.getElementById('flat_file_target_table_name_hidden');
        const submitForm = document.getElementById('flat-file-submit-form');

        function sanitizeTableName(value) {
            let sanitized = String(value || '').replace(/[^0-9a-zA-Z_]/g, '_').replace(/^_+|_+$/g, '').toLowerCase();
            if (!sanitized) sanitized = 'flat_file_source';
            return sanitized.slice(0, 63);
        }

        fetch('/sync-jobs/create/step2/flat-file-preview/')
            .then(function(response) { return response.json(); })
            .then(function(data) {
                flatFileLoading.style.display = 'none';
                if (!data.success) {
                    flatFileError.textContent = data.message || 'Unable to load file preview.';
                    flatFileError.style.display = 'block';
                    return;
                }

                const columns = Array.isArray(data.columns) ? data.columns : [];
                const rows = Array.isArray(data.rows) ? data.rows : [];
                const stats = data.file_stats || {};
                const defaultTable = sanitizeTableName(data.default_table_name || '');
                tableNameInput.value = defaultTable;
                hiddenTableName.value = defaultTable;

                statsEl.textContent = 'Rows sampled: ' + (stats.sample_rows || 0)
                    + ' | Size: ' + (stats.size_bytes || 0) + ' bytes'
                    + ' | Encoding: ' + (stats.encoding || '')
                    + ' | Delimiter: ' + (stats.delimiter || ',');

                const headTr = document.createElement('tr');
                columns.forEach(function(col) {
                    const th = document.createElement('th');
                    th.textContent = String(col);
                    headTr.appendChild(th);
                });
                headEl.innerHTML = '';
                headEl.appendChild(headTr);

                bodyEl.innerHTML = '';
                rows.forEach(function(row) {
                    const tr = document.createElement('tr');
                    columns.forEach(function(_, idx) {
                        const td = document.createElement('td');
                        td.textContent = row[idx] !== undefined ? String(row[idx]) : '';
                        tr.appendChild(td);
                    });
                    bodyEl.appendChild(tr);
                });
                flatFileArea.style.display = 'block';
            })
            .catch(function(err) {
                flatFileLoading.style.display = 'none';
                flatFileError.textContent = 'Preview request failed: ' + getDisplayErrorText(err);
                flatFileError.style.display = 'block';
            });

        if (tableNameInput) {
            tableNameInput.addEventListener('input', function() {
                const sanitized = sanitizeTableName(tableNameInput.value);
                hiddenTableName.value = sanitized;
            });
        }
        if (submitForm) {
            submitForm.addEventListener('submit', function(e) {
                if (!hiddenTableName.value) {
                    e.preventDefault();
                    hiddenTableName.value = 'flat_file_source';
                }
            });
        }
        return;
    }
    // Get connection ID from global variable set in template
    const connectionId = typeof SOURCE_CONNECTION_ID !== 'undefined' ? SOURCE_CONNECTION_ID : null;
    const sourceDbType = typeof SOURCE_DB_TYPE !== 'undefined' ? SOURCE_DB_TYPE : null;
    
    console.log('Step 2: Initializing...');
    console.log('Step 2: SOURCE_CONNECTION_ID =', typeof SOURCE_CONNECTION_ID !== 'undefined' ? SOURCE_CONNECTION_ID : 'UNDEFINED');
    console.log('Step 2: connectionId =', connectionId);
    
    if (!connectionId) {
        console.error('[ERROR] Source connection ID not found');
        const errorMsg = document.getElementById('error-message');
        const loadingIndicator = document.getElementById('loading-indicator');
        if (loadingIndicator) {
            loadingIndicator.style.display = 'none';
        }
        if (errorMsg) {
            errorMsg.textContent = 'Source connection ID not found. Please go back to Step 1.';
            errorMsg.style.display = 'block';
        } else {
            alert('Source connection ID not found. Please go back to Step 1.');
        }
        return;
    }
    
    console.log('[OK] Connection ID found:', connectionId);
    
    // Get CSRF token
    const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
    if (!csrfInput) {
        console.error('CSRF token not found');
        const errorMsg = document.getElementById('error-message');
        const loadingIndicator = document.getElementById('loading-indicator');
        if (loadingIndicator) {
            loadingIndicator.style.display = 'none';
        }
        if (errorMsg) {
            errorMsg.textContent = 'CSRF token not found. Please refresh the page.';
            errorMsg.style.display = 'block';
        } else {
            alert('CSRF token not found. Please refresh the page.');
        }
        return;
    }
    const csrfToken = csrfInput.value;
    
    const loader = new MetadataLoader(connectionId, csrfToken);
    const loadingIndicator = document.getElementById('loading-indicator');
    const errorMessage = document.getElementById('error-message');
    const tableSelectionArea = document.getElementById('table-selection-area');
    const schemasContainer = document.getElementById('schemas-container');
    const tableSearch = document.getElementById('table-search');
    const selectAllBtn = document.getElementById('select-all-btn');
    const deselectAllBtn = document.getElementById('deselect-all-btn');
    const refreshBtn = document.getElementById('refresh-btn');
    const nextBtn = document.getElementById('next-btn');
    
    // Validate all required elements exist
    if (!loadingIndicator || !errorMessage || !tableSelectionArea || !schemasContainer || 
        !tableSearch || !selectAllBtn || !deselectAllBtn || !refreshBtn || !nextBtn) {
        console.error('Required DOM elements not found');
        if (errorMessage) {
            errorMessage.textContent = 'Page structure error. Please refresh the page.';
            errorMessage.style.display = 'block';
        }
        if (loadingIndicator) {
            loadingIndicator.style.display = 'none';
        }
        return;
    }
    
    let allTables = []; // {key: "schema.table", schema: "...", table: "...", element: ...}
    let selectedTables = new Set();
    let loadedSchemas = new Set(); // Track which schemas have been expanded
    let schemaElements = new Map(); // Map schema name to DOM element
    
    // Debounce search input
    let searchTimeout;
    const SEARCH_DEBOUNCE_MS = 300;
    
    // Safe function to set innerHTML with null checks
    function safeSetInnerHTML(element, html) {
        if (!element) {
            console.error('Attempted to set innerHTML on null element. Stack:', new Error().stack);
            return false;
        }
        if (typeof element.innerHTML === 'undefined') {
            console.error('Element does not have innerHTML property. Element:', element);
            return false;
        }
        try {
            element.innerHTML = html;
            return true;
        } catch (e) {
            console.error('Error setting innerHTML:', e, 'Element:', element, 'HTML:', html);
            return false;
        }
    }
    
    // Safe function to set textContent with null checks
    function safeSetTextContent(element, text) {
        if (!element) {
            console.error('Attempted to set textContent on null element');
            return false;
        }
        try {
            element.textContent = text;
            return true;
        } catch (e) {
            console.error('Error setting textContent:', e);
            return false;
        }
    }
    
    // Initial load: Load schemas - try multiple approaches to ensure it runs
    console.log('Step 2: Setting up schema load...');
    
    // Method 1: Immediate call if DOM is ready
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        console.log('Step 2: DOM ready, calling loadSchemas immediately...');
        setTimeout(() => loadSchemas(), 0);
    }
    
    // Method 2: setTimeout as backup
    setTimeout(() => {
        console.log('Step 2: Timeout fired, calling loadSchemas...');
        loadSchemas();
    }, 100);
    
    // Method 3: Event-based fallback
    window.addEventListener('load', () => {
        console.log('Step 2: Window load event fired, ensuring loadSchemas called...');
        setTimeout(() => {
            // Check if schemas already loaded
            const schemasContainer = document.getElementById('schemas-container');
            if (schemasContainer && schemasContainer.children.length === 0) {
                console.log('Step 2: No schemas loaded yet, calling loadSchemas from window.load event...');
                loadSchemas();
            }
        }, 200);
    });
    
    /**
     * Load schemas (lazy loading - step 1)
     */
    async function loadSchemas(useCache = true) {
        // Double-check elements exist
        if (!loadingIndicator || !errorMessage || !tableSelectionArea) {
            console.error('Required elements missing in loadSchemas:', {
                loadingIndicator: !!loadingIndicator,
                errorMessage: !!errorMessage,
                tableSelectionArea: !!tableSelectionArea
            });
            return;
        }
        
        loadingIndicator.style.display = 'block';
        errorMessage.style.display = 'none';
        tableSelectionArea.style.display = 'none';
        
        // Update loading text safely
        const loadingText = loadingIndicator.querySelector('p');
        if (loadingText) {
            loadingText.textContent = 'Loading schemas...';
        }
        
        try {
            console.log('Step 2: Starting schema load for connection:', connectionId);
            const loadStartTime = Date.now();
            
            // Load schemas with timeout protection
            const schemas = await loader.loadSchemas(useCache);
            
            const loadDuration = Date.now() - loadStartTime;
            console.log(`Step 2: Schemas loaded successfully in ${loadDuration}ms:`, schemas?.length || 0, 'schemas');
            
            if (!schemas || schemas.length === 0) {
                console.warn('Step 2: No schemas found in database');
                // Show no-schemas message instead of error
                const noSchemasMsg = document.getElementById('no-schemas-message');
                if (noSchemasMsg) {
                    noSchemasMsg.style.display = 'block';
                }
                loadingIndicator.style.display = 'none';
                tableSelectionArea.style.display = 'block';
                return;
            }
            
            console.log('Step 2: Displaying schemas...');
            
            // Get fresh element references
            const currentLoadingIndicator2 = document.getElementById('loading-indicator');
            const currentTableSelectionArea2 = document.getElementById('table-selection-area');
            const currentErrorMessage2 = document.getElementById('error-message');
            
            displaySchemas(schemas);
            console.log('Step 2: Schemas displayed successfully');
            
            if (currentLoadingIndicator2) {
                currentLoadingIndicator2.style.display = 'none';
            }
            if (currentTableSelectionArea2) {
                currentTableSelectionArea2.style.display = 'block';
            }
            
            // Hide no-schemas message
            const noSchemasMsg = document.getElementById('no-schemas-message');
            if (noSchemasMsg) {
                noSchemasMsg.style.display = 'none';
            }
        } catch (error) {
            console.error('Step 2: Error in loadSchemas:', error);
            console.error('Step 2: Error type:', error.constructor.name);
            console.error('Step 2: Error message:', error.message);
            console.error('Step 2: Error stack:', error.stack);
            
            // Get fresh element references for error handling
            const currentLoadingIndicator3 = document.getElementById('loading-indicator');
            const currentErrorMessage3 = document.getElementById('error-message');
            
            if (currentLoadingIndicator3) {
                currentLoadingIndicator3.style.display = 'none';
            }
            console.error('Error loading schemas:', error);
            
            let errorText = getDisplayErrorText(error);
            
            if (errorText.toLowerCase().includes('password') && 
                (errorText.toLowerCase().includes('decrypt') || 
                 errorText.toLowerCase().includes('update') ||
                 errorText.toLowerCase().includes('edit'))) {
                errorText = 'Password decryption failed. Please update your connection password by editing it in the Connections page, then try again.';
            }
            
            // Use textContent instead of innerHTML to avoid any issues
            // Use the error message element we already got
            if (currentErrorMessage3 && currentErrorMessage3.nodeType === 1) {
                try {
                    // Clear any existing content first
                    while (currentErrorMessage3.firstChild) {
                        currentErrorMessage3.removeChild(currentErrorMessage3.firstChild);
                    }
                    
                    // Create and add error text node
                    const errorTextNode = document.createTextNode(`Error loading schemas: ${errorText}`);
                    currentErrorMessage3.appendChild(errorTextNode);
                    
                    // Add buttons using DOM methods (safer than innerHTML)
                    try {
                        const br1 = document.createElement('br');
                        const br2 = document.createElement('br');
                        const retryBtn = document.createElement('button');
                        retryBtn.className = 'btn btn-sm btn-primary ms-2';
                        retryBtn.textContent = 'Retry';
                        retryBtn.onclick = () => location.reload();
                        
                        const connectionsLink = document.createElement('a');
                        connectionsLink.className = 'btn btn-sm btn-outline-primary ms-2';
                        connectionsLink.href = '/connections/';
                        connectionsLink.textContent = 'Go to Connections';
                        
                        currentErrorMessage3.appendChild(br1);
                        currentErrorMessage3.appendChild(br2);
                        currentErrorMessage3.appendChild(retryBtn);
                        currentErrorMessage3.appendChild(connectionsLink);
                    } catch (e) {
                        console.error('Error adding buttons to error message:', e);
                        // Continue without buttons - error text is already displayed
                    }
                    
                    currentErrorMessage3.style.display = 'block';
                } catch (e) {
                    console.error('Error setting error message:', e, 'Element:', currentErrorMessage3);
                    alert(`Error loading schemas: ${errorText}`);
                }
            } else {
                console.error('Error message element not found or invalid. Error:', errorText, 'Element:', currentErrorMessage3);
                alert(`Error loading schemas: ${errorText}`);
            }
        }
    }
    
    /**
     * Display schemas in tree structure
     */
    function displaySchemas(schemas) {
        if (!schemasContainer) {
            console.error('Schemas container not found');
            return;
        }
        // Clear schemas container safely
        try {
            if (schemasContainer && typeof schemasContainer.innerHTML !== 'undefined') {
                schemasContainer.innerHTML = '';
            } else {
                console.error('Schemas container is null or invalid:', schemasContainer);
                return;
            }
        } catch (e) {
            console.error('Error clearing schemas container:', e);
            return;
        }
        schemaElements.clear();
        
        schemas.forEach(schemaInfo => {
            const schemaName = schemaInfo.name;
            
            // Create schema item
            const schemaItem = document.createElement('div');
            schemaItem.className = 'schema-item mb-2';
            schemaItem.dataset.schema = schemaName;
            
            // Schema header (clickable to expand/collapse)
            const schemaHeader = document.createElement('div');
            schemaHeader.className = 'schema-header d-flex align-items-center p-2 border rounded cursor-pointer';
            schemaHeader.style.cursor = 'pointer';
            schemaHeader.style.backgroundColor = '#f8f9fa';
            
            // Expand/collapse icon
            const expandIcon = document.createElement('span');
            expandIcon.className = 'expand-icon me-2';
            safeSetInnerHTML(expandIcon, '▶');
            expandIcon.style.transition = 'transform 0.2s';
            
            // Schema name
            const schemaNameSpan = document.createElement('span');
            schemaNameSpan.className = 'fw-bold';
            schemaNameSpan.textContent = schemaName;
            
            // Loading indicator for tables
            const loadingSpinner = document.createElement('span');
            loadingSpinner.className = 'spinner-border spinner-border-sm ms-2';
            loadingSpinner.style.display = 'none';
            loadingSpinner.setAttribute('role', 'status');
            safeSetInnerHTML(loadingSpinner, '<span class="visually-hidden">Loading...</span>');
            
            schemaHeader.appendChild(expandIcon);
            schemaHeader.appendChild(schemaNameSpan);
            schemaHeader.appendChild(loadingSpinner);
            
            // Tables container (initially hidden)
            const tablesContainer = document.createElement('div');
            tablesContainer.className = 'tables-container ms-4 mt-2';
            tablesContainer.style.display = 'none';
            tablesContainer.dataset.schema = schemaName;
            
            // Error message for schema
            const schemaError = document.createElement('div');
            schemaError.className = 'alert alert-danger alert-sm mt-2';
            schemaError.style.display = 'none';
            schemaError.style.fontSize = '0.875rem';
            schemaError.style.padding = '0.5rem';
            
            schemaItem.appendChild(schemaHeader);
            schemaItem.appendChild(tablesContainer);
            schemaItem.appendChild(schemaError);
            
            // Click handler to expand/collapse and load tables
            schemaHeader.addEventListener('click', async function() {
                const isExpanded = tablesContainer.style.display !== 'none';
                
                if (isExpanded) {
                    // Collapse
                    tablesContainer.style.display = 'none';
                    expandIcon.style.transform = 'rotate(0deg)';
                    safeSetInnerHTML(expandIcon, '▶');
                } else {
                    // Expand
                    expandIcon.style.transform = 'rotate(90deg)';
                    safeSetInnerHTML(expandIcon, '▼');
                    tablesContainer.style.display = 'block';
                    
                    // Load tables if not already loaded
                    if (!loadedSchemas.has(schemaName)) {
                        await loadTablesForSchema(schemaName, tablesContainer, loadingSpinner, schemaError);
                    }
                }
            });
            
            schemaElements.set(schemaName, schemaItem);
            schemasContainer.appendChild(schemaItem);
        });
    }
    
    /**
     * Load tables for a specific schema (lazy loading - step 2)
     */
    async function loadTablesForSchema(schemaName, tablesContainer, loadingSpinner, errorElement) {
        console.log('Loading tables for schema:', schemaName);
        if (!tablesContainer) {
            console.error('Tables container not found for schema:', schemaName);
            return;
        }
        
        // Validate all parameters
        if (!schemaName) {
            console.error('Schema name is required');
            return;
        }
        if (loadingSpinner) {
            loadingSpinner.style.display = 'inline-block';
        }
        if (errorElement) {
            errorElement.style.display = 'none';
        }
        // Clear tables container safely
        try {
            if (tablesContainer && typeof tablesContainer.innerHTML !== 'undefined') {
                tablesContainer.innerHTML = '';
            } else {
                console.error('Tables container is null or invalid:', tablesContainer);
                return;
            }
        } catch (e) {
            console.error('Error clearing tables container:', e);
            return;
        }
        
        try {
            const tables = await loader.loadTables(schemaName, true);
            
            if (!tables || tables.length === 0) {
                try {
                    if (tablesContainer && typeof tablesContainer.innerHTML !== 'undefined') {
                        tablesContainer.innerHTML = '<p class="text-muted small">No tables found in this schema.</p>';
                    } else {
                        console.error('Tables container is null when trying to set "no tables" message');
                    }
                } catch (e) {
                    console.error('Error setting "no tables" message:', e);
                }
                loadedSchemas.add(schemaName);
                if (loadingSpinner) {
                    loadingSpinner.style.display = 'none';
                }
                return;
            }
            
            // Display tables
            tables.forEach(tableInfo => {
                const tableName = tableInfo.name;
                const tableKey = `${schemaName}.${tableName}`;
                
                const tableItem = document.createElement('div');
                tableItem.className = 'form-check mb-2';
                tableItem.dataset.tableKey = tableKey;
                
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.className = 'form-check-input table-checkbox';
                checkbox.id = `table-${tableKey.replace(/[\.\s]/g, '-')}`;
                checkbox.value = tableKey;
                checkbox.dataset.schema = schemaName;
                checkbox.dataset.table = tableName;
                
                checkbox.addEventListener('change', function() {
                    if (this.checked) {
                        selectedTables.add(tableKey);
                    } else {
                        selectedTables.delete(tableKey);
                    }
                    updateNextButton();
                });
                
                const label = document.createElement('label');
                label.className = 'form-check-label';
                label.htmlFor = checkbox.id;
                label.textContent = `${schemaName}.${tableName}`;
                
                const labelWrapper = document.createElement('span');
                labelWrapper.className = 'd-flex align-items-center';
                labelWrapper.appendChild(label);
                
                tableItem.appendChild(checkbox);
                tableItem.appendChild(labelWrapper);
                
                // Add transformation UI only for SQL sources (MongoDB is document-based; transforms are disabled).
                const transformsEnabled = sourceDbType !== 'mongodb';
                if (transformsEnabled) {
                    const transformBtn = document.createElement('button');
                    transformBtn.type = 'button';
                    transformBtn.className = 'btn btn-sm btn-outline-info ms-2 transform-btn';
                    transformBtn.textContent = '⚙️ Transform';
                    transformBtn.dataset.tableKey = tableKey;
                    transformBtn.addEventListener('click', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                        toggleTransformationPanel(tableKey, schemaName, tableName);
                    });
                    labelWrapper.appendChild(transformBtn);

                    const transformPanel = createTransformationPanel(tableKey, schemaName, tableName);
                    tableItem.appendChild(transformPanel);
                }
                
                tablesContainer.appendChild(tableItem);
                
                // Track table
                allTables.push({
                    key: tableKey,
                    schema: schemaName,
                    table: tableName,
                    element: tableItem
                });
            });
            
            loadedSchemas.add(schemaName);
            if (loadingSpinner) {
                try {
                    loadingSpinner.style.display = 'none';
                } catch (e) {
                    console.error('Error hiding loading spinner:', e);
                }
            }
            
            // Update search filter if active
            if (tableSearch && tableSearch.value) {
                try {
                    filterTables(tableSearch.value);
                } catch (e) {
                    console.error('Error filtering tables:', e);
                }
            }
            
        } catch (error) {
            // Completely safe error handling - no innerHTML, only textContent and DOM methods
            try {
                // Hide loading spinner safely
                if (loadingSpinner && loadingSpinner.nodeType === 1) {
                    try {
                        loadingSpinner.style.display = 'none';
                    } catch (e) {
                        console.error('Error hiding loading spinner:', e);
                    }
                }
                
                console.error(`Error loading tables for schema ${schemaName}:`, error);
                const errorText = getDisplayErrorText(error, 'Unknown error');
                
                // Try to display error in schema-specific error element first
                let errorDisplayed = false;
                if (errorElement && errorElement.nodeType === 1) {
                    try {
                        // Clear any existing content
                        while (errorElement.firstChild) {
                            errorElement.removeChild(errorElement.firstChild);
                        }
                        // Set text content
                        errorElement.textContent = `Failed to load tables: ${errorText}`;
                        errorElement.style.display = 'block';
                        errorDisplayed = true;
                    } catch (e) {
                        console.error('Error setting schema error element:', e);
                    }
                }
                
                // Fallback to main error message area if schema error element failed
                if (!errorDisplayed) {
                    // Re-query the error message element to ensure it exists
                    const mainErrorMsg = document.getElementById('error-message');
                    if (mainErrorMsg && mainErrorMsg.nodeType === 1) {
                        try {
                            // Clear any existing content
                            while (mainErrorMsg.firstChild) {
                                mainErrorMsg.removeChild(mainErrorMsg.firstChild);
                            }
                            // Set text content
                            mainErrorMsg.textContent = `Error loading tables for schema ${schemaName}: ${errorText}`;
                            mainErrorMsg.style.display = 'block';
                            errorDisplayed = true;
                        } catch (e) {
                            console.error('Error setting main error message:', e);
                        }
                    }
                }
                
                // Final fallback: use alert if all else fails
                if (!errorDisplayed) {
                    alert(`Error loading tables for schema ${schemaName}: ${errorText}`);
                }
            } catch (fatalError) {
                console.error('Fatal error in error handler:', fatalError);
                // Last resort: alert
                try {
                    alert(`Error loading tables: ${error.message || 'Unknown error'}`);
                } catch (e) {
                    console.error('Even alert failed:', e);
                }
            }
        }
    }
    
    /**
     * Filter tables based on search term
     */
    function filterTables(searchTerm) {
        const term = searchTerm.toLowerCase();
        let visibleCount = 0;
        
        allTables.forEach(table => {
            const tableKey = table.key.toLowerCase();
            if (tableKey.includes(term)) {
                table.element.style.display = 'block';
                visibleCount++;
            } else {
                table.element.style.display = 'none';
            }
        });
        
        // Show/hide schemas based on visible tables
        schemaElements.forEach((schemaItem, schemaName) => {
            if (!schemaItem) return;
            const tablesContainer = schemaItem.querySelector('.tables-container');
            if (!tablesContainer) {
                // Schema not expanded yet, show it if no search term
                schemaItem.style.display = !searchTerm ? 'block' : 'none';
                return;
            }
            const visibleTables = Array.from(tablesContainer.querySelectorAll('.table-checkbox'))
                .filter(cb => cb.offsetParent !== null);
            
            if (visibleTables.length > 0 || !searchTerm) {
                schemaItem.style.display = 'block';
            } else {
                schemaItem.style.display = 'none';
            }
        });
        
        // Show/hide no tables message
        const noTablesMsg = document.getElementById('no-tables-message');
        if (noTablesMsg) {
            if (visibleCount === 0 && searchTerm) {
                noTablesMsg.style.display = 'block';
            } else {
                noTablesMsg.style.display = 'none';
            }
        }
    }
    
    // Search functionality with debouncing
    if (tableSearch) {
        tableSearch.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                filterTables(this.value);
            }, SEARCH_DEBOUNCE_MS);
        });
    }
    
    // Select all (only visible tables)
    if (selectAllBtn) {
        selectAllBtn.addEventListener('click', function() {
            document.querySelectorAll('.table-checkbox').forEach(checkbox => {
                if (checkbox.offsetParent !== null) { // Only visible checkboxes
                    checkbox.checked = true;
                    selectedTables.add(checkbox.value);
                }
            });
            updateNextButton();
        });
    }
    
    // Deselect all
    if (deselectAllBtn) {
        deselectAllBtn.addEventListener('click', function() {
            document.querySelectorAll('.table-checkbox').forEach(checkbox => {
                checkbox.checked = false;
                selectedTables.delete(checkbox.value);
            });
            updateNextButton();
        });
    }
    
    // Refresh button
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async function() {
            // Clear cache and reload
            loadedSchemas.clear();
            allTables = [];
            selectedTables.clear();
            await loadSchemas(false); // useCache = false to force refresh
        });
    }
    
    function updateNextButton() {
        if (!nextBtn) return;
        nextBtn.disabled = selectedTables.size === 0;
        if (selectedTables.size > 0) {
            nextBtn.textContent = `Next (${selectedTables.size} selected)`;
        } else {
            nextBtn.textContent = 'Next';
        }
    }
    
    // Form submission
    const tableSelectionForm = document.getElementById('table-selection-form');
    if (tableSelectionForm) {
        tableSelectionForm.addEventListener('submit', function(e) {
        if (selectedTables.size === 0) {
            e.preventDefault();
            alert('Please select at least one table.');
            return false;
        }
        
        // Store selected tables in hidden inputs
        selectedTables.forEach(tableKey => {
            const [schema, table] = tableKey.split('.');
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'selected_tables';
            input.value = JSON.stringify({schema: schema, table: table});
            this.appendChild(input);
        });
        
        // Store transformation data
        const transformationsInput = document.createElement('input');
        transformationsInput.type = 'hidden';
        transformationsInput.name = 'table_transformations';
        transformationsInput.value = JSON.stringify(window.tableTransformations || {});
        this.appendChild(transformationsInput);
    });
    }
    
    // Transformation management
    window.tableTransformations = window.tableTransformations || {};
    
    function createTransformationPanel(tableKey, schema, table) {
        const panel = document.createElement('div');
        panel.className = 'transformation-panel mt-2 mb-3 p-3 border rounded bg-light';
        panel.id = `transform-panel-${tableKey.replace(/[\.\s]/g, '-')}`;
        panel.style.display = 'none';
        
        // Build panel HTML with proper escaping
        const sanitizedTableKey = tableKey.replace(/[\.\s]/g, '-');
        panel.innerHTML = 
            '<h6 class="mb-3">Transformations for ' + schema + '.' + table + '</h6>' +
            '<div class="mb-3">' +
            '<label for="where-' + sanitizedTableKey + '" class="form-label">WHERE Clause</label>' +
            '<textarea class="form-control" id="where-' + sanitizedTableKey + '" rows="2" placeholder="Price > 20 AND Status = \'Active\'"></textarea>' +
            '<small class="form-text text-muted"><strong>IMPORTANT:</strong> Enter only the WHERE condition (e.g., &quot;Price &gt; 20&quot;). DO NOT include SELECT, FROM, or WHERE keywords. The system will add them automatically.</small>' +
            '</div>' +
            '<div class="mb-3">' +
            '<label class="form-label">Column Transformations</label>' +
            '<div id="column-transforms-' + sanitizedTableKey + '" class="column-transforms-list mb-2"></div>' +
            '<button type="button" class="btn btn-sm btn-secondary add-column-transform" data-table-key="' + tableKey + '">+ Add Column Transformation</button>' +
            '</div>' +
            '<div class="d-flex gap-2">' +
            '<button type="button" class="btn btn-sm btn-primary validate-transform" data-table-key="' + tableKey + '">Validate</button>' +
            '<button type="button" class="btn btn-sm btn-outline-secondary clear-transform" data-table-key="' + tableKey + '">Clear</button>' +
            '</div>' +
            '<div class="transform-message mt-2" id="transform-msg-' + sanitizedTableKey + '"></div>';
        
        // Add event listeners
        panel.querySelector('.add-column-transform').addEventListener('click', function() {
            addColumnTransformation(tableKey, schema, table);
        });
        
        panel.querySelector('.validate-transform').addEventListener('click', function() {
            validateTransformation(tableKey, schema, table);
        });
        
        panel.querySelector('.clear-transform').addEventListener('click', function() {
            clearTransformation(tableKey);
        });
        
        return panel;
    }
    
    function toggleTransformationPanel(tableKey, schema, table) {
        const panelId = `transform-panel-${tableKey.replace(/[\.\s]/g, '-')}`;
        const panel = document.getElementById(panelId);
        if (!panel) return;
        
        if (panel.style.display === 'none') {
            panel.style.display = 'block';
            loadTableColumnsForTransform(tableKey, schema, table);
        } else {
            panel.style.display = 'none';
        }
    }
    
    function addColumnTransformation(tableKey, schema, table) {
        const containerId = `column-transforms-${tableKey.replace(/[\.\s]/g, '-')}`;
        const container = document.getElementById(containerId);
        if (!container) return;
        
        const row = document.createElement('div');
        row.className = 'transform-row mb-2 d-flex gap-2 align-items-center';
        
        // Get columns for this table (load if not cached)
        const columns = window.tableColumnsCache?.[tableKey] || [];
        
        const columnSelect = document.createElement('select');
        columnSelect.className = 'form-select form-select-sm';
        columnSelect.style.width = '200px';
        columnSelect.innerHTML = '<option value="">Select Column</option>';
        columns.forEach(col => {
            const option = document.createElement('option');
            option.value = col.name;
            option.textContent = col.name;
            columnSelect.appendChild(option);
        });
        
        const transformSelect = document.createElement('select');
        transformSelect.className = 'form-select form-select-sm';
        transformSelect.style.width = '150px';
        transformSelect.innerHTML = `
            <option value="">None</option>
            <option value="TRIM">TRIM</option>
            <option value="UPPER">UPPER</option>
            <option value="LOWER">LOWER</option>
        `;
        
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-sm btn-outline-danger';
        removeBtn.textContent = 'Remove';
        removeBtn.addEventListener('click', function() {
            row.remove();
            updateTransformationsForTable(tableKey);
        });
        
        row.appendChild(columnSelect);
        row.appendChild(transformSelect);
        row.appendChild(removeBtn);
        
        columnSelect.addEventListener('change', function() {
            updateTransformationsForTable(tableKey);
        });
        transformSelect.addEventListener('change', function() {
            updateTransformationsForTable(tableKey);
        });
        
        container.appendChild(row);
    }
    
    function loadTableColumnsForTransform(tableKey, schema, table) {
        // Check if already loaded
        if (window.tableColumnsCache && window.tableColumnsCache[tableKey]) {
            return;
        }
        
        // Load columns via API
        const connectionId = SOURCE_CONNECTION_ID;
        if (!connectionId) return;
        
        fetch(`/sync-jobs/api/table-columns/?connection_id=${connectionId}&schema=${encodeURIComponent(schema)}&table=${encodeURIComponent(table)}`, {
            headers: {
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
            }
        })
            .then(response => response.json())
            .then(data => {
                if (data.success && data.columns) {
                    if (!window.tableColumnsCache) window.tableColumnsCache = {};
                    window.tableColumnsCache[tableKey] = data.columns;
                }
            })
            .catch(err => console.error('Error loading columns:', err));
    }
    
    function updateTransformationsForTable(tableKey) {
        if (!window.tableTransformations) window.tableTransformations = {};
        
        const whereTextarea = document.getElementById(`where-${tableKey.replace(/[\.\s]/g, '-')}`);
        const containerId = `column-transforms-${tableKey.replace(/[\.\s]/g, '-')}`;
        const container = document.getElementById(containerId);
        
        const whereClause = whereTextarea ? whereTextarea.value.trim() : '';
        
        const columnTransforms = {};
        if (container) {
            container.querySelectorAll('.transform-row').forEach(row => {
                const colSelect = row.querySelector('select:first-child');
                const transformSelect = row.querySelector('select:last-of-type');
                if (colSelect && transformSelect && colSelect.value && transformSelect.value) {
                    columnTransforms[colSelect.value] = transformSelect.value;
                }
            });
        }
        
        if (whereClause || Object.keys(columnTransforms).length > 0) {
            window.tableTransformations[tableKey] = {
                where_clause: whereClause,
                column_transformations: columnTransforms
            };
        } else {
            delete window.tableTransformations[tableKey];
        }
    }
    
    function validateTransformation(tableKey, schema, table) {
        const connectionId = SOURCE_CONNECTION_ID;
        if (!connectionId) {
            showTransformMessage(tableKey, 'Error: Connection ID not available', 'danger');
            return;
        }
        
        const whereTextarea = document.getElementById(`where-${tableKey.replace(/[\.\s]/g, '-')}`);
        const whereClause = whereTextarea ? whereTextarea.value.trim() : '';
        
        const containerId = `column-transforms-${tableKey.replace(/[\.\s]/g, '-')}`;
        const container = document.getElementById(containerId);
        const columnTransforms = {};
        
        if (container) {
            container.querySelectorAll('.transform-row').forEach(row => {
                const colSelect = row.querySelector('select:first-child');
                const transformSelect = row.querySelector('select:last-of-type');
                if (colSelect && transformSelect && colSelect.value && transformSelect.value) {
                    columnTransforms[colSelect.value] = transformSelect.value;
                }
            });
        }
        
        showTransformMessage(tableKey, 'Validating...', 'info');
        
        const formData = new FormData();
        formData.append('connection_id', connectionId);
        formData.append('schema', schema);
        formData.append('table', table);
        formData.append('where_clause', whereClause);
        formData.append('column_transformations', JSON.stringify(columnTransforms));
        
        fetch('/sync-jobs/api/validate-transformation-query/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
            },
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.valid) {
                showTransformMessage(tableKey, data.message || '✓ Transformation is valid', 'success');
                updateTransformationsForTable(tableKey);
            } else {
                showTransformMessage(tableKey, '✗ ' + (data.error || 'Validation failed'), 'danger');
            }
        })
        .catch(err => {
            console.error('Validation error:', err);
            showTransformMessage(tableKey, '✗ Validation error: ' + err.message, 'danger');
        });
    }
    
    function clearTransformation(tableKey) {
        const whereTextarea = document.getElementById(`where-${tableKey.replace(/[\.\s]/g, '-')}`);
        if (whereTextarea) whereTextarea.value = '';
        
        const containerId = `column-transforms-${tableKey.replace(/[\.\s]/g, '-')}`;
        const container = document.getElementById(containerId);
        if (container) container.innerHTML = '';
        
        delete window.tableTransformations[tableKey];
        
        const msgEl = document.getElementById(`transform-msg-${tableKey.replace(/[\.\s]/g, '-')}`);
        if (msgEl) msgEl.innerHTML = '';
    }
    
    function showTransformMessage(tableKey, message, type) {
        const msgId = `transform-msg-${tableKey.replace(/[\.\s]/g, '-')}`;
        const msgEl = document.getElementById(msgId);
        if (!msgEl) return;
        
        msgEl.className = `transform-message mt-2 alert alert-${type}`;
        msgEl.textContent = message;
    }
    
    } catch (error) {
        console.error('Fatal error in create_job_step2.js:', error);
        const errorMsg = document.getElementById('error-message');
        if (errorMsg) {
            errorMsg.textContent = `A fatal error occurred: ${error.message || 'Unknown error'}. Please refresh the page.`;
            errorMsg.style.display = 'block';
        } else {
            alert(`A fatal error occurred: ${error.message || 'Unknown error'}. Please refresh the page.`);
        }
        const loadingIndicator = document.getElementById('loading-indicator');
        if (loadingIndicator) {
            loadingIndicator.style.display = 'none';
        }
    }
});
