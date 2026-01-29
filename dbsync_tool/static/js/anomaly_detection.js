/**
 * Anomaly Detection UI
 * Handles alert banner, anomaly list, and real-time updates
 */

let anomalyPollInterval = null;

function initAnomalyDetection(anomaliesData, anomalyStats) {
    // Update alert banner
    updateAlertBanner(anomalyStats);
    
    // Start polling for updates every 30 seconds
    if (anomalyPollInterval) {
        clearInterval(anomalyPollInterval);
    }
    
    anomalyPollInterval = setInterval(function() {
        refreshAnomalies(true); // Silent refresh
    }, 30000); // 30 seconds
}

function updateAlertBanner(stats) {
    const banner = document.getElementById('anomalyAlertBanner');
    const criticalCount = document.getElementById('anomalyCriticalCount');
    
    if (!banner || !criticalCount) return;
    
    if (stats.critical > 0) {
        criticalCount.textContent = stats.critical;
        banner.classList.remove('alert-warning');
        banner.classList.add('alert-danger');
        banner.style.display = 'block';
        banner.classList.add('show');
    } else if (stats.unacknowledged > 0) {
        criticalCount.textContent = stats.unacknowledged;
        banner.classList.remove('alert-danger');
        banner.classList.add('alert-warning');
        banner.style.display = 'block';
        banner.classList.add('show');
    } else {
        banner.style.display = 'none';
        banner.classList.remove('show');
    }
}

function scrollToAnomalies() {
    const panel = document.getElementById('anomalyPanel');
    if (panel) {
        panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function refreshAnomalies(silent = false) {
    if (!silent) {
        // Show loading indicator
        const anomalyList = document.getElementById('anomalyList');
        if (anomalyList) {
            anomalyList.innerHTML = '<p class="text-muted text-center">Loading...</p>';
        }
    }
    
    // Fetch anomalies from API
    fetch('/api/jobs/anomalies/', {
        method: 'GET',
        headers: {
            'X-CSRFToken': getCsrfToken(),
            'Content-Type': 'application/json',
        },
        credentials: 'same-origin'
    })
    .then(response => response.json())
    .then(data => {
        updateAnomalyList(data.results || []);
        
        // Fetch stats
        return fetch('/api/jobs/anomalies/stats/', {
            method: 'GET',
            headers: {
                'X-CSRFToken': getCsrfToken(),
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin'
        });
    })
    .then(response => response.json())
    .then(stats => {
        updateAnomalyStats(stats);
        updateAlertBanner(stats);
    })
    .catch(error => {
        console.error('Error refreshing anomalies:', error);
        if (!silent) {
            const anomalyList = document.getElementById('anomalyList');
            if (anomalyList) {
                anomalyList.innerHTML = '<p class="text-danger text-center">Error loading anomalies. Please refresh the page.</p>';
            }
        }
    });
}

function updateAnomalyList(anomalies) {
    const anomalyList = document.getElementById('anomalyList');
    if (!anomalyList) return;
    
    if (anomalies.length === 0) {
        anomalyList.innerHTML = '<p class="text-muted text-center mb-0">No active anomalies detected</p>';
        return;
    }
    
    let html = '';
    anomalies.forEach(anomaly => {
        const severityClass = anomaly.severity === 'critical' ? 'danger' : 'warning';
        const severityIcon = anomaly.severity === 'critical' ? '🔴' : '🟡';
        const detectedTime = formatTimeAgo(anomaly.detected_at);
        
        html += `
            <div class="alert alert-${severityClass} alert-dismissible fade show mb-2" data-anomaly-id="${anomaly.id}">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <strong>
                            ${severityIcon} ${anomaly.severity_display}: ${anomaly.anomaly_type_display}
                        </strong>
                        <br>
                        <small>
                            <strong>Job:</strong> <a href="/sync-jobs/${anomaly.job.id}/">${escapeHtml(anomaly.job.name)}</a><br>
                            <strong>Description:</strong> ${escapeHtml(anomaly.description)}<br>
                            <strong>Detected:</strong> ${detectedTime}
                        </small>
                    </div>
                    <button type="button" class="btn btn-sm btn-outline-${severityClass}" onclick="acknowledgeAnomaly('${anomaly.id}')">
                        Acknowledge
                    </button>
                </div>
            </div>
        `;
    });
    
    anomalyList.innerHTML = html;
}

function updateAnomalyStats(stats) {
    const countElement = document.getElementById('anomalyCount');
    if (countElement) {
        countElement.textContent = stats.unacknowledged || 0;
    }
}

function acknowledgeAnomaly(anomalyId) {
    if (!confirm('Are you sure you want to acknowledge this anomaly?')) {
        return;
    }
    
    fetch(`/api/jobs/anomalies/acknowledge/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCsrfToken(),
            'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ anomaly_id: anomalyId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            alert('Error: ' + data.error);
            return;
        }
        
        // Remove the anomaly from the list
        const anomalyElement = document.querySelector(`[data-anomaly-id="${anomalyId}"]`);
        if (anomalyElement) {
            anomalyElement.remove();
        }
        
        // Refresh stats
        refreshAnomalies(true);
    })
    .catch(error => {
        console.error('Error acknowledging anomaly:', error);
        alert('Error acknowledging anomaly. Please try again.');
    });
}

function formatTimeAgo(dateString) {
    if (!dateString) return 'Unknown';
    
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) {
        return 'Just now';
    } else if (diffMins < 60) {
        return `${diffMins} minute${diffMins !== 1 ? 's' : ''} ago`;
    } else if (diffHours < 24) {
        return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
    } else {
        return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

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
