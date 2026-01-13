/**
 * Checkpoint management JavaScript for incremental sync jobs
 * Handles checkpoint reset functionality and periodic refresh
 */

(function() {
    'use strict';

    /**
     * Get CSRF token from cookies
     */
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

    /**
     * Reset checkpoint for a specific table
     * @param {string} jobId - Job ID
     * @param {string} schemaName - Schema name
     * @param {string} tableName - Table name
     */
    function resetCheckpoint(jobId, schemaName, tableName) {
        const url = `/sync-jobs/${jobId}/checkpoints/reset/${encodeURIComponent(schemaName)}/${encodeURIComponent(tableName)}/`;
        const csrftoken = getCookie('csrftoken');

        // Show loading state
        const button = document.querySelector(
            `button[data-job-id="${jobId}"][data-schema="${schemaName}"][data-table="${tableName}"]`
        );
        const originalText = button.textContent;
        button.disabled = true;
        button.textContent = 'Resetting...';

        fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrftoken,
                'Content-Type': 'application/json',
            },
        })
        .then(response => {
            if (response.ok) {
                return response;
            }
            throw new Error('Network response was not ok');
        })
        .then(() => {
            // Reload page to show updated checkpoints
            window.location.reload();
        })
        .catch(error => {
            console.error('Error resetting checkpoint:', error);
            button.disabled = false;
            button.textContent = originalText;
            alert('Failed to reset checkpoint: ' + error.message);
        });
    }

    /**
     * Refresh checkpoints periodically (if job is running)
     */
    function refreshCheckpoints() {
        // Only refresh if job status is running
        const statusBadge = document.querySelector('.status-badge-large');
        if (!statusBadge || !statusBadge.textContent.includes('Running')) {
            return;
        }

        // Get job ID from page
        const jobId = window.location.pathname.match(/\/sync-jobs\/([^\/]+)\//);
        if (!jobId || !jobId[1]) {
            return;
        }

        const url = `/sync-jobs/${jobId[1]}/checkpoints/`;
        
        fetch(url, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            },
        })
        .then(response => response.json())
        .then(data => {
            if (data.checkpoints) {
                // Update checkpoint display (simplified - can be enhanced)
                updateCheckpointDisplay(data.checkpoints);
            }
        })
        .catch(error => {
            console.error('Error refreshing checkpoints:', error);
        });
    }

    /**
     * Update checkpoint display in the table
     * @param {Array} checkpoints - Array of checkpoint objects
     */
    function updateCheckpointDisplay(checkpoints) {
        checkpoints.forEach(function(cp) {
            const row = document.querySelector(
                `tr:has(strong:contains("${cp.schema_name}.${cp.table_name}"))`
            );
            
            if (row) {
                // Update checkpoint value cell
                const valueCell = row.querySelector('td:nth-child(2)');
                if (valueCell && cp.last_value) {
                    valueCell.innerHTML = `<code class="text-success">${cp.last_value.substring(0, 50)}</code>`;
                }
                
                // Update last updated cell
                const updatedCell = row.querySelector('td:nth-child(3)');
                if (updatedCell && cp.updated_at) {
                    const date = new Date(cp.updated_at);
                    updatedCell.textContent = date.toLocaleString('en-US', {
                        year: 'numeric',
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit'
                    });
                }
            }
        });
    }

    /**
     * Initialize checkpoint management functionality
     */
    function initCheckpointManagement() {
        // Attach event listeners to reset buttons
        document.querySelectorAll('.reset-checkpoint-btn').forEach(function(button) {
            button.addEventListener('click', function() {
                const jobId = this.dataset.jobId;
                const schema = this.dataset.schema;
                const table = this.dataset.table;
                
                if (confirm(`Reset checkpoint for ${schema}.${table}?\n\nThis will cause the next sync to process all rows from this table.`)) {
                    resetCheckpoint(jobId, schema, table);
                }
            });
        });

        // Refresh checkpoints every 30 seconds if job is running
        setInterval(refreshCheckpoints, 30000);
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCheckpointManagement);
    } else {
        initCheckpointManagement();
    }
})();

