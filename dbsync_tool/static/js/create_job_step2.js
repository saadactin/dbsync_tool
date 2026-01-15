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
    // Get connection ID from global variable set in template
    const connectionId = typeof SOURCE_CONNECTION_ID !== 'undefined' ? SOURCE_CONNECTION_ID : null;
    
    if (!connectionId) {
        console.error('Source connection ID not found');
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
    
    // Initial load: Load schemas only (with a small delay to ensure DOM is ready)
    setTimeout(() => {
        loadSchemas();
    }, 100);
    
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
            console.log('Loading schemas for connection:', connectionId);
            const schemas = await loader.loadSchemas(useCache);
            console.log('Schemas loaded successfully:', schemas?.length || 0);
            
            if (!schemas || schemas.length === 0) {
                throw new Error('No schemas found in the database.');
            }
            
            displaySchemas(schemas);
            loadingIndicator.style.display = 'none';
            tableSelectionArea.style.display = 'block';
            
            // Hide no-schemas message
            const noSchemasMsg = document.getElementById('no-schemas-message');
            if (noSchemasMsg) {
                noSchemasMsg.style.display = 'none';
            }
        } catch (error) {
            if (loadingIndicator) {
                loadingIndicator.style.display = 'none';
            }
            console.error('Error loading schemas:', error);
            
            let errorText = error.message || 'Unknown error occurred. Please check the browser console for details.';
            
            if (errorText.toLowerCase().includes('password') && 
                (errorText.toLowerCase().includes('decrypt') || 
                 errorText.toLowerCase().includes('update') ||
                 errorText.toLowerCase().includes('edit'))) {
                errorText = 'Password decryption failed. Please update your connection password by editing it in the Connections page, then try again.';
            }
            
            // Use textContent instead of innerHTML to avoid any issues
            // Re-check errorMessage in case it became null
            const currentErrorMessage = document.getElementById('error-message');
            if (currentErrorMessage && currentErrorMessage.nodeType === 1) {
                try {
                    // Clear any existing content first
                    while (currentErrorMessage.firstChild) {
                        currentErrorMessage.removeChild(currentErrorMessage.firstChild);
                    }
                    
                    // Create and add error text node
                    const errorTextNode = document.createTextNode(`Error loading schemas: ${errorText}`);
                    currentErrorMessage.appendChild(errorTextNode);
                    
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
                        
                        currentErrorMessage.appendChild(br1);
                        currentErrorMessage.appendChild(br2);
                        currentErrorMessage.appendChild(retryBtn);
                        currentErrorMessage.appendChild(connectionsLink);
                    } catch (e) {
                        console.error('Error adding buttons to error message:', e);
                        // Continue without buttons - error text is already displayed
                    }
                    
                    currentErrorMessage.style.display = 'block';
                } catch (e) {
                    console.error('Error setting error message:', e, 'Element:', currentErrorMessage);
                    alert(`Error loading schemas: ${errorText}`);
                }
            } else {
                console.error('Error message element not found or invalid. Error:', errorText, 'Element:', currentErrorMessage);
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
                
                tableItem.appendChild(checkbox);
                tableItem.appendChild(label);
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
                const errorText = error.message || 'Unknown error';
                
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
    });
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
