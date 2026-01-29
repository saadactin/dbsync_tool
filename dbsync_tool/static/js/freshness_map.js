/**
 * Freshness Map Visualization
 * Displays data freshness heatmap for all sync jobs
 */

let currentTimePeriod = '7d';
let currentStatusFilter = '';
let freshnessData = null;

/**
 * Load freshness map data from API
 */
function loadFreshnessMap(timePeriod = '7d', buttonElement = null) {
    currentTimePeriod = timePeriod;
    
    // Update active button
    if (buttonElement) {
        document.querySelectorAll('.btn-group button').forEach(btn => {
            btn.classList.remove('active');
        });
        buttonElement.classList.add('active');
    }
    
    const container = document.getElementById('freshnessMapContainer');
    if (!container) return;
    
    // Show loading
    container.innerHTML = `
        <div class="text-center p-5">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <p class="mt-2">Loading freshness map...</p>
        </div>
    `;
    
    // Build API URL
    let url = '/api/jobs/freshness-map/?time_period=' + timePeriod;
    if (currentStatusFilter) {
        url += '&status=' + currentStatusFilter;
    }
    
    // Fetch data
    fetch(url, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        credentials: 'same-origin'
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Failed to load freshness map');
        }
        return response.json();
    })
    .then(data => {
        freshnessData = data;
        renderFreshnessMap(data);
    })
    .catch(error => {
        console.error('Error loading freshness map:', error);
        container.innerHTML = `
            <div class="alert alert-danger">
                <strong>Error:</strong> Failed to load freshness map. Please try again.
            </div>
        `;
    });
}

/**
 * Filter freshness map by status
 */
function filterFreshnessMap() {
    const filterSelect = document.getElementById('freshnessStatusFilter');
    if (!filterSelect) return;
    
    currentStatusFilter = filterSelect.value;
    loadFreshnessMap(currentTimePeriod);
}

/**
 * Refresh freshness map
 */
function refreshFreshnessMap() {
    loadFreshnessMap(currentTimePeriod);
}

/**
 * Render freshness map heatmap
 */
function renderFreshnessMap(data) {
    const container = document.getElementById('freshnessMapContainer');
    if (!container) return;
    
    if (!data.jobs || data.jobs.length === 0) {
        container.innerHTML = `
            <div class="alert alert-info">
                <strong>No jobs found.</strong> Create a sync job to see freshness data.
            </div>
        `;
        return;
    }
    
    // Build time periods (for now, just show current status)
    // In future, can add historical time periods
    const timePeriods = ['Current'];
    
    // Create table
    let html = `
        <div class="table-responsive">
            <table class="table table-bordered table-sm" style="font-size: 0.85rem;">
                <thead>
                    <tr>
                        <th style="min-width: 200px; position: sticky; left: 0; background: white; z-index: 10;">Job Name</th>
                        <th style="min-width: 100px;">Status</th>
                        <th style="min-width: 120px;">Freshness</th>
                        <th style="min-width: 120px;">Expected</th>
                        <th style="min-width: 150px;">Last Sync</th>
                        <th style="min-width: 80px;">Current</th>
                    </tr>
                </thead>
                <tbody>
    `;
    
    // Sort jobs by freshness status (critical first, then stale, then fresh, then never_run)
    const statusOrder = { 'critical': 0, 'stale': 1, 'fresh': 2, 'never_run': 3 };
    const sortedJobs = [...data.jobs].sort((a, b) => {
        return (statusOrder[a.freshness_status] || 99) - (statusOrder[b.freshness_status] || 99);
    });
    
    sortedJobs.forEach(job => {
        const statusColor = getStatusColor(job.freshness_status);
        const statusBadge = getStatusBadge(job.freshness_status);
        const freshnessText = formatFreshness(job.freshness_minutes);
        const expectedText = formatFreshness(job.expected_freshness_minutes);
        const lastSyncText = job.last_successful_sync 
            ? new Date(job.last_successful_sync).toLocaleString() 
            : 'Never';
        
        html += `
            <tr>
                <td style="position: sticky; left: 0; background: white; z-index: 9;">
                    <strong>${escapeHtml(job.name)}</strong>
                </td>
                <td>${statusBadge}</td>
                <td>${freshnessText}</td>
                <td>${expectedText}</td>
                <td>${lastSyncText}</td>
                <td class="text-center">
                    <div class="freshness-cell" 
                         style="width: 40px; height: 40px; margin: 0 auto; background-color: ${statusColor}; border: 1px solid #ddd; border-radius: 4px; cursor: pointer;"
                         data-job-id="${job.id}"
                         data-job-name="${escapeHtml(job.name)}"
                         data-freshness-minutes="${job.freshness_minutes || 0}"
                         data-freshness-status="${job.freshness_status}"
                         data-last-sync="${job.last_successful_sync || ''}"
                         onclick="showJobDetails('${job.id}')"
                         title="Click for details">
                    </div>
                </td>
            </tr>
        `;
    });
    
    html += `
                </tbody>
            </table>
        </div>
        <div class="mt-3">
            <strong>Summary:</strong>
            <span class="badge bg-success">Fresh: ${data.summary.fresh || 0}</span>
            <span class="badge bg-warning text-dark">Stale: ${data.summary.stale || 0}</span>
            <span class="badge bg-danger">Critical: ${data.summary.critical || 0}</span>
            <span class="badge bg-secondary">Never Run: ${data.summary.never_run || 0}</span>
            <span class="badge bg-info">Total: ${data.summary.total || 0}</span>
        </div>
    `;
    
    container.innerHTML = html;
    
    // Add hover tooltips
    container.querySelectorAll('.freshness-cell').forEach(cell => {
        cell.addEventListener('mouseenter', function(e) {
            const minutes = this.getAttribute('data-freshness-minutes');
            const status = this.getAttribute('data-freshness-status');
            const lastSync = this.getAttribute('data-last-sync');
            
            let tooltipText = `Status: ${status}\nFreshness: ${formatFreshness(parseInt(minutes))}`;
            if (lastSync) {
                tooltipText += `\nLast Sync: ${new Date(lastSync).toLocaleString()}`;
            }
            
            // Simple tooltip (can be enhanced with Bootstrap tooltip)
            this.setAttribute('title', tooltipText);
        });
    });
}

/**
 * Get color for freshness status
 */
function getStatusColor(status) {
    const colors = {
        'fresh': '#28a745',
        'stale': '#ffc107',
        'critical': '#dc3545',
        'never_run': '#6c757d'
    };
    return colors[status] || '#6c757d';
}

/**
 * Get badge HTML for freshness status
 */
function getStatusBadge(status) {
    const badges = {
        'fresh': '<span class="badge bg-success">Fresh</span>',
        'stale': '<span class="badge bg-warning text-dark">Stale</span>',
        'critical': '<span class="badge bg-danger">Critical</span>',
        'never_run': '<span class="badge bg-secondary">Never Run</span>'
    };
    return badges[status] || '<span class="badge bg-secondary">Unknown</span>';
}

/**
 * Format freshness minutes to human-readable text
 */
function formatFreshness(minutes) {
    if (minutes === null || minutes === undefined) {
        return 'N/A';
    }
    
    if (minutes < 60) {
        return `${minutes} min`;
    } else if (minutes < 1440) {
        const hours = Math.floor(minutes / 60);
        const mins = minutes % 60;
        return `${hours}h ${mins}m`;
    } else {
        const days = Math.floor(minutes / 1440);
        const hours = Math.floor((minutes % 1440) / 60);
        return `${days}d ${hours}h`;
    }
}

/**
 * Show job details modal
 */
function showJobDetails(jobId) {
    // Navigate to job detail page
    window.location.href = `/sync-jobs/job/${jobId}/`;
}

/**
 * Get CSRF token
 */
function getCsrfToken() {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrftoken') {
            return value;
        }
    }
    return '';
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Initialize freshness map on page load
 */
document.addEventListener('DOMContentLoaded', function() {
    // Load freshness map after a short delay to ensure other scripts are loaded
    setTimeout(function() {
        if (document.getElementById('freshnessMapContainer')) {
            loadFreshnessMap('7d');
        }
    }, 500);
});
