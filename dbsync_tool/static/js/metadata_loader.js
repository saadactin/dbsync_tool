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
     * Load schemas only (lazy loading)
     */
    async loadSchemas(useCache = true) {
        const url = `/metadata/api/${this.connectionId}/schemas/?use_cache=${useCache}`;
        
        console.log('MetadataLoader: Loading schemas from URL:', url);
        console.log('MetadataLoader: Connection ID:', this.connectionId);
        
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => {
                console.error('MetadataLoader: Request timeout after 30 seconds');
                controller.abort();
            }, 30000); // Increased to 30 seconds for slow databases
            
            console.log('MetadataLoader: Sending fetch request...');
            const fetchStartTime = Date.now();
            
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json',
                },
                credentials: 'include',
                signal: controller.signal
            });
            
            const fetchDuration = Date.now() - fetchStartTime;
            console.log(`MetadataLoader: Fetch completed in ${fetchDuration}ms, status: ${response.status}`);
            
            clearTimeout(timeoutId);
            
            if (!response.ok) {
                let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
                try {
                    const errorData = await response.json();
                    console.error('MetadataLoader: Error response data:', errorData);
                    if (errorData.error) {
                        errorMessage = errorData.error;
                    } else if (errorData.detail) {
                        errorMessage = errorData.detail;
                    } else if (errorData.message) {
                        errorMessage = errorData.message;
                    }
                } catch (e) {
                    console.error('MetadataLoader: Failed to parse error response as JSON:', e);
                    // Try to get text response
                    try {
                        const text = await response.text();
                        console.error('MetadataLoader: Error response text:', text);
                        if (text) {
                            errorMessage = text.substring(0, 500); // Limit length
                        }
                    } catch (e2) {
                        console.error('MetadataLoader: Failed to read error response text:', e2);
                    }
                }
                throw new Error(errorMessage);
            }
            
            console.log('MetadataLoader: Parsing JSON response...');
            const data = await response.json();
            console.log('MetadataLoader: Response data received:', data);
            
            if (data.success) {
                console.log(`MetadataLoader: Successfully loaded ${data.data?.length || 0} schemas`);
                return data.data;
            } else {
                const errorMsg = data.error || data.message || 'Failed to load schemas';
                console.error('MetadataLoader: API returned success=false:', errorMsg);
                throw new Error(errorMsg);
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                const timeoutError = new Error(
                    'Request timeout: The database may be slow or unreachable. ' +
                    'Please check:\n' +
                    '1. Database server is running\n' +
                    '2. Network connectivity to database\n' +
                    '3. Connection credentials are correct\n' +
                    '4. Firewall allows connections'
                );
                console.error('MetadataLoader: Request aborted (timeout)');
                throw timeoutError;
            }
            console.error('MetadataLoader: Error loading schemas:', error);
            console.error('MetadataLoader: Error stack:', error.stack);
            throw error;
        }
    }
    
    /**
     * Load tables for a schema (lazy loading)
     */
    async loadTables(schemaName, useCache = true) {
        const url = `/metadata/api/${this.connectionId}/schemas/${encodeURIComponent(schemaName)}/tables/?use_cache=${useCache}`;
        
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout
            
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json',
                },
                credentials: 'include',
                signal: controller.signal
            });
            
            clearTimeout(timeoutId);
            
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
                }
                throw new Error(errorMessage);
            }
            
            const data = await response.json();
            
            if (data.success) {
                return data.data;
            } else {
                throw new Error(data.error || 'Failed to load tables');
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                throw new Error('Request timeout: Database may be slow or unreachable');
            }
            console.error('Error loading tables:', error);
            throw error;
        }
    }
    
    /**
     * Load columns for a table (lazy loading, optional)
     */
    async loadColumns(schemaName, tableName, useCache = true) {
        const url = `/metadata/api/${this.connectionId}/schemas/${encodeURIComponent(schemaName)}/tables/${encodeURIComponent(tableName)}/columns/?use_cache=${useCache}`;
        
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout
            
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json',
                },
                credentials: 'include',
                signal: controller.signal
            });
            
            clearTimeout(timeoutId);
            
            if (!response.ok) {
                let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
                try {
                    const errorData = await response.json();
                    if (errorData.error) {
                        errorMessage = errorData.error;
                    }
                } catch (e) {
                    // If response is not JSON, use status text
                }
                throw new Error(errorMessage);
            }
            
            const data = await response.json();
            
            if (data.success) {
                return data.data;
            } else {
                throw new Error(data.error || 'Failed to load columns');
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                throw new Error('Request timeout: Database may be slow or unreachable');
            }
            console.error('Error loading columns:', error);
            throw error;
        }
    }
}

