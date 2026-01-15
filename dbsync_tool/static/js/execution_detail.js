/**
 * Real-time execution status updates
 */

let updateInterval = null;
let isUpdating = false;

function initializeExecutionUpdates(executionId, jobId) {
    console.log('Initializing real-time updates for execution:', executionId);
    
    // Start polling immediately
    updateExecutionStatus(executionId, jobId);
    
    // Set up polling interval (every 2 seconds)
    updateInterval = setInterval(function() {
        if (!isUpdating) {
            updateExecutionStatus(executionId, jobId);
        }
    }, 2000);
    
    // Stop polling when page is hidden (performance optimization)
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            if (updateInterval) {
                clearInterval(updateInterval);
                updateInterval = null;
            }
        } else {
            if (!updateInterval && isExecutionRunning()) {
                updateInterval = setInterval(function() {
                    if (!isUpdating) {
                        updateExecutionStatus(executionId, jobId);
                    }
                }, 2000);
            }
        }
    });
}

function updateExecutionStatus(executionId, jobId) {
    if (isUpdating) {
        return;
    }
    
    isUpdating = true;
    
    const url = `/sync-jobs/${jobId}/executions/${executionId}/status/`;
    
    fetch(url, {
        method: 'GET',
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
        },
        credentials: 'same-origin'
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        updateExecutionUI(data);
        
        // Stop polling if execution is completed or failed
        if (data.execution.status === 'completed' || 
            data.execution.status === 'failed' || 
            data.execution.status === 'cancelled') {
            stopPolling();
            
            // Show completion message
            if (data.execution.status === 'completed') {
                showNotification('Execution completed successfully!', 'success');
            } else if (data.execution.status === 'failed') {
                showNotification('Execution failed. Check error details.', 'error');
            }
        }
    })
    .catch(error => {
        console.error('Error updating execution status:', error);
        // Don't stop polling on error, just log it
    })
    .finally(() => {
        isUpdating = false;
    });
}

function updateExecutionUI(data) {
    const execution = data.execution;
    const logs = data.logs;
    const stats = data.statistics;
    
    // Update execution status badge
    updateStatusBadge(execution.status, execution.status_display);
    
    // Update execution statistics
    updateStatistics(execution, stats);
    
    // Update logs table
    updateLogsTable(logs);
    
    // Update progress bar
    updateProgressBar(execution.completed_tables, execution.total_tables);
    
    // Update duration
    if (execution.duration_seconds !== null) {
        updateDuration(execution.duration_seconds);
    }
}

function updateStatusBadge(status, statusDisplay) {
    const badge = document.querySelector('.execution-header .badge');
    if (badge) {
        badge.textContent = statusDisplay;
        badge.className = `badge bg-${getStatusBadgeClass(status)} fs-6 px-3 py-2`;
    }
}

function updateStatistics(execution, stats) {
    // Update tables progress - use actual counts from statistics
    const tablesProgress = document.querySelectorAll('.stat-card .stat-value');
    if (tablesProgress.length > 0 && tablesProgress[0].textContent.includes('/')) {
        // Use statistics counts (more accurate) or fallback to execution counts
        const completedCount = stats.completed_logs !== undefined ? stats.completed_logs : execution.completed_tables;
        const totalCount = stats.total_logs !== undefined ? stats.total_logs : execution.total_tables;
        tablesProgress[0].textContent = `${completedCount}/${totalCount}`;
        
        // Update progress bar
        const progressBar = document.querySelector('.progress-bar-fill');
        if (progressBar && totalCount > 0) {
            const percentage = (completedCount / totalCount) * 100;
            progressBar.style.width = `${percentage}%`;
        }
    }
    
    // Update rows synced
    if (tablesProgress.length > 1) {
        tablesProgress[1].textContent = formatNumber(execution.total_rows_synced);
    }
    
    // Update completed/failed counts
    const completedCount = document.querySelectorAll('.stat-card .stat-value.text-success');
    if (completedCount.length > 0) {
        completedCount[0].textContent = stats.completed_logs;
    }
    
    const failedCount = document.querySelectorAll('.stat-card .stat-value.text-danger');
    if (failedCount.length > 0) {
        failedCount[0].textContent = stats.failed_logs;
    }
}

function updateLogsTable(logs) {
    const tbody = document.getElementById('logs-table-body');
    if (!tbody) return;
    
    logs.forEach(log => {
        const row = tbody.querySelector(`tr[data-log-id="${log.id}"]`);
        if (row) {
            // Update existing row
            updateLogRow(row, log);
        } else {
            // Add new row (if log was just created)
            addLogRow(tbody, log);
        }
    });
}

function updateLogRow(row, log) {
    const cells = row.querySelectorAll('td');
    if (cells.length < 7) return;
    
    // Update status
    cells[1].innerHTML = `
        <span class="badge bg-${getStatusBadgeClass(log.status)}">
            ${log.status_display}
        </span>
        ${log.status === 'running' ? '<span class="spinner-border spinner-border-sm ms-1"></span>' : ''}
    `;
    
    // Update batch number
    cells[2].textContent = log.batch_number || '-';
    
    // Update rows fetched
    cells[3].textContent = formatNumber(log.rows_fetched);
    
    // Update rows inserted
    cells[4].textContent = formatNumber(log.rows_inserted);
    
    // Update duration (if completed)
    if (log.completed_at && log.started_at) {
        const start = new Date(log.started_at);
        const end = new Date(log.completed_at);
        const duration = formatDuration((end - start) / 1000);
        cells[5].textContent = duration;
    } else if (log.status === 'running') {
        cells[5].innerHTML = '<span class="text-info">Running...</span>';
    }
    
    // Update error message
    if (log.error_message) {
        cells[6].innerHTML = `
            <button class="btn btn-sm btn-outline-danger" 
                    data-bs-toggle="modal" 
                    data-bs-target="#errorModal${log.id}">
                View Error
            </button>
        `;
    }
}

function addLogRow(tbody, log) {
    const row = document.createElement('tr');
    row.setAttribute('data-log-id', log.id);
    row.className = 'log-row';
    
    row.innerHTML = `
        <td><strong>${log.schema_name}.${log.table_name}</strong></td>
        <td>
            <span class="badge bg-${getStatusBadgeClass(log.status)}">
                ${log.status_display}
            </span>
            ${log.status === 'running' ? '<span class="spinner-border spinner-border-sm ms-1"></span>' : ''}
        </td>
        <td>${log.batch_number || '-'}</td>
        <td>${formatNumber(log.rows_fetched)}</td>
        <td>${formatNumber(log.rows_inserted)}</td>
        <td>${log.status === 'running' ? '<span class="text-info">Running...</span>' : '-'}</td>
        <td>${log.error_message ? '<button class="btn btn-sm btn-outline-danger">View Error</button>' : '-'}</td>
    `;
    
    tbody.appendChild(row);
}

function updateProgressBar(completed, total) {
    const progressBar = document.querySelector('.progress-bar-fill');
    if (progressBar && total > 0) {
        const percentage = (completed / total) * 100;
        progressBar.style.width = `${percentage}%`;
    }
}

function updateDuration(seconds) {
    // Duration is already calculated server-side, just display it
    // This could be enhanced to show live updating duration
}

function stopPolling() {
    if (updateInterval) {
        clearInterval(updateInterval);
        updateInterval = null;
        console.log('Stopped polling (execution finished)');
    }
}

function isExecutionRunning() {
    const badge = document.querySelector('.execution-header .badge');
    if (badge) {
        const status = badge.textContent.toLowerCase();
        return status.includes('running');
    }
    return false;
}

function getStatusBadgeClass(status) {
    const statusMap = {
        'pending': 'secondary',
        'running': 'info',
        'completed': 'success',
        'failed': 'danger',
        'cancelled': 'warning'
    };
    return statusMap[status] || 'secondary';
}

function formatNumber(num) {
    if (num === null || num === undefined) return '-';
    return num.toLocaleString();
}

function formatDuration(seconds) {
    if (seconds < 60) {
        return `${Math.floor(seconds)}s`;
    } else if (seconds < 3600) {
        const minutes = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${minutes}m ${secs}s`;
    } else {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return `${hours}h ${minutes}m`;
    }
}

function showNotification(message, type) {
    // Create and show a notification (you can use a toast library or custom implementation)
    const alertClass = type === 'success' ? 'alert-success' : 'alert-danger';
    const alert = document.createElement('div');
    alert.className = `alert ${alertClass} alert-dismissible fade show position-fixed top-0 end-0 m-3`;
    alert.style.zIndex = '9999';
    alert.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    document.body.appendChild(alert);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        alert.remove();
    }, 5000);
}


