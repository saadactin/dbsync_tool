/**
 * Metadata loader utility for loading database schemas and tables
 */

class MetadataLoader {
    constructor(connectionId, csrfToken) {
        this.connectionId = connectionId;
        this.csrfToken = csrfToken;
        this.metadata = null;
    }
    
    /**
     * Load all metadata for the connection
     */
    async loadAllMetadata(includeRowCounts = false) {
        const url = `/metadata/api/${this.connectionId}/all/?include_row_counts=${includeRowCounts}`;
        
        try {
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json',
                },
                credentials: 'include',
            });
            
            if (!response.ok) {
                let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
                try {
                    const errorData = await response.json();
                    if (errorData.error) {
                        errorMessage = errorData.error;
                    } else if (errorData.detail) {
                        errorMessage = errorData.detail;
                    }
                } catch (e) {
                    // If response is not JSON, use status text
                    if (response.status === 401 || response.status === 403) {
                        errorMessage = 'Authentication required. Please log in again.';
                    } else if (response.status === 404) {
                        errorMessage = 'Connection not found or you do not have permission to access it.';
                    } else if (response.status >= 500) {
                        errorMessage = 'Server error occurred. Please try again later.';
                    }
                }
                throw new Error(errorMessage);
            }
            
            const data = await response.json();
            
            if (data.success) {
                this.metadata = data.data;
                return this.metadata;
            } else {
                throw new Error(data.error || 'Failed to load metadata');
            }
        } catch (error) {
            console.error('Error loading metadata:', error);
            throw error;
        }
    }
    
    /**
     * Load schemas only
     */
    async loadSchemas() {
        const url = `/metadata/api/${this.connectionId}/schemas/`;
        
        try {
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                },
                credentials: 'same-origin',
            });
            
            const data = await response.json();
            
            if (data.success) {
                return data.data;
            } else {
                throw new Error(data.error || 'Failed to load schemas');
            }
        } catch (error) {
            console.error('Error loading schemas:', error);
            throw error;
        }
    }
    
    /**
     * Load tables for a schema
     */
    async loadTables(schemaName) {
        const url = `/metadata/api/${this.connectionId}/schemas/${encodeURIComponent(schemaName)}/tables/`;
        
        try {
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                },
                credentials: 'same-origin',
            });
            
            const data = await response.json();
            
            if (data.success) {
                return data.data;
            } else {
                throw new Error(data.error || 'Failed to load tables');
            }
        } catch (error) {
            console.error('Error loading tables:', error);
            throw error;
        }
    }
}

