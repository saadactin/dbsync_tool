/**
 * Step 2: Table selection functionality
 */

document.addEventListener('DOMContentLoaded', function() {
    // Get connection ID from global variable set in template
    const connectionId = typeof SOURCE_CONNECTION_ID !== 'undefined' ? SOURCE_CONNECTION_ID : null;
    
    if (!connectionId) {
        console.error('Source connection ID not found');
        const errorMsg = document.getElementById('error-message');
        const loadingIndicator = document.getElementById('loading-indicator');
        loadingIndicator.style.display = 'none';
        errorMsg.textContent = 'Source connection ID not found. Please go back to Step 1.';
        errorMsg.style.display = 'block';
        return;
    }
    
    // Get CSRF token
    const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
    if (!csrfInput) {
        console.error('CSRF token not found');
        const errorMsg = document.getElementById('error-message');
        const loadingIndicator = document.getElementById('loading-indicator');
        loadingIndicator.style.display = 'none';
        errorMsg.textContent = 'CSRF token not found. Please refresh the page.';
        errorMsg.style.display = 'block';
        return;
    }
    const csrfToken = csrfInput.value;
    
    const loader = new MetadataLoader(connectionId, csrfToken);
    const loadingIndicator = document.getElementById('loading-indicator');
    const errorMessage = document.getElementById('error-message');
    const tableSelectionArea = document.getElementById('table-selection-area');
    const tablesContainer = document.getElementById('tables-container');
    const tableSearch = document.getElementById('table-search');
    const selectAllBtn = document.getElementById('select-all-btn');
    const deselectAllBtn = document.getElementById('deselect-all-btn');
    const nextBtn = document.getElementById('next-btn');
    
    let allTables = [];
    let selectedTables = new Set();
    
    // Load metadata on page load
    loadMetadata();
    
    async function loadMetadata() {
        loadingIndicator.style.display = 'block';
        errorMessage.style.display = 'none';
        tableSelectionArea.style.display = 'none';
        
        try {
            const metadata = await loader.loadAllMetadata(false);
            
            // Check if metadata has schemas and tables
            if (!metadata || !metadata.schemas || metadata.schemas.length === 0) {
                throw new Error('No schemas found in the database.');
            }
            
            // Check if any schema has tables
            const hasTables = metadata.schemas.some(schema => schema.tables && schema.tables.length > 0);
            if (!hasTables) {
                throw new Error('No tables found in any schema.');
            }
            
            displayTables(metadata);
            loadingIndicator.style.display = 'none';
            
            // Check if any tables were displayed
            const totalTables = allTables.length;
            if (totalTables === 0) {
                document.getElementById('no-tables-message').style.display = 'block';
            } else {
                document.getElementById('no-tables-message').style.display = 'none';
            }
            
            tableSelectionArea.style.display = 'block';
        } catch (error) {
            loadingIndicator.style.display = 'none';
            console.error('Metadata loading error:', error);
            
            // Check if error is about password decryption
            let errorText = error.message || 'Unknown error occurred. Please check the browser console for details.';
            
            if (errorText.toLowerCase().includes('password') && 
                (errorText.toLowerCase().includes('decrypt') || 
                 errorText.toLowerCase().includes('update') ||
                 errorText.toLowerCase().includes('edit'))) {
                errorText = 'Password decryption failed. Please update your connection password by editing it in the Connections page, then try again.';
            }
            
            errorMessage.innerHTML = `
                <strong>Error loading tables:</strong> ${errorText}
                <br><br>
                <a href="/connections/" class="btn btn-sm btn-primary">Go to Connections</a>
            `;
            errorMessage.style.display = 'block';
        }
    }
    
    function displayTables(metadata) {
        allTables = [];
        tablesContainer.innerHTML = '';
        
        metadata.schemas.forEach(schema => {
            const schemaDiv = document.createElement('div');
            schemaDiv.className = 'mb-4';
            
            const schemaHeader = document.createElement('h6');
            schemaHeader.className = 'text-muted mb-2';
            schemaHeader.textContent = `Schema: ${schema.name}`;
            schemaDiv.appendChild(schemaHeader);
            
            const tableList = document.createElement('div');
            tableList.className = 'table-list';
            
            schema.tables.forEach(table => {
                const tableKey = `${schema.name}.${table.name}`;
                allTables.push({
                    key: tableKey,
                    schema: schema.name,
                    table: table.name,
                    element: null
                });
                
                const tableItem = document.createElement('div');
                tableItem.className = 'form-check mb-2';
                tableItem.dataset.tableKey = tableKey;
                
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.className = 'form-check-input table-checkbox';
                checkbox.id = `table-${tableKey.replace(/\./g, '-')}`;
                checkbox.value = tableKey;
                checkbox.dataset.schema = schema.name;
                checkbox.dataset.table = table.name;
                
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
                label.textContent = `${schema.name}.${table.name}`;
                
                tableItem.appendChild(checkbox);
                tableItem.appendChild(label);
                tableList.appendChild(tableItem);
                
                allTables[allTables.length - 1].element = tableItem;
            });
            
            schemaDiv.appendChild(tableList);
            tablesContainer.appendChild(schemaDiv);
        });
    }
    
    // Search functionality
    tableSearch.addEventListener('input', function() {
        const searchTerm = this.value.toLowerCase();
        allTables.forEach(table => {
            const tableKey = table.key.toLowerCase();
            if (tableKey.includes(searchTerm)) {
                table.element.style.display = 'block';
            } else {
                table.element.style.display = 'none';
            }
        });
    });
    
    // Select all
    selectAllBtn.addEventListener('click', function() {
        document.querySelectorAll('.table-checkbox').forEach(checkbox => {
            if (checkbox.offsetParent !== null) { // Only visible checkboxes
                checkbox.checked = true;
                selectedTables.add(checkbox.value);
            }
        });
        updateNextButton();
    });
    
    // Deselect all
    deselectAllBtn.addEventListener('click', function() {
        document.querySelectorAll('.table-checkbox').forEach(checkbox => {
            checkbox.checked = false;
            selectedTables.delete(checkbox.value);
        });
        updateNextButton();
    });
    
    function updateNextButton() {
        nextBtn.disabled = selectedTables.size === 0;
        if (selectedTables.size > 0) {
            nextBtn.textContent = `Next (${selectedTables.size} selected)`;
        } else {
            nextBtn.textContent = 'Next';
        }
    }
    
    // Form submission
    document.getElementById('table-selection-form').addEventListener('submit', function(e) {
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
});

