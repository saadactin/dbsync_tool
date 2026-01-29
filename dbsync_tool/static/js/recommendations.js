/**
 * Recommendations Engine Frontend
 * Displays and manages recommendations on the dashboard
 */

// Priority colors
const PRIORITY_COLORS = {
    'high': '#dc3545',
    'medium': '#ffc107',
    'low': '#28a745'
};

// Category icons
const CATEGORY_ICONS = {
    'performance': '⚡',
    'reliability': '🛡️',
    'schedule': '📅',
    'configuration': '⚙️',
    'health': '💚'
};

/**
 * Initialize recommendations widget
 */
function initRecommendations(recommendationsData) {
    const container = document.getElementById('recommendationsContainer');
    if (!container) return;
    
    if (!recommendationsData || recommendationsData.length === 0) {
        container.innerHTML = `
            <div class="alert alert-info">
                <i class="bi bi-info-circle"></i> No recommendations at this time. Your sync system is running smoothly!
            </div>
        `;
        return;
    }
    
    // Sort by priority (high -> medium -> low)
    const priorityOrder = {'high': 0, 'medium': 1, 'low': 2};
    const sorted = recommendationsData.sort((a, b) => {
        return priorityOrder[a.priority] - priorityOrder[b.priority];
    });
    
    // Render recommendations
    let html = '<div class="list-group">';
    sorted.forEach(rec => {
        html += renderRecommendation(rec);
    });
    html += '</div>';
    
    container.innerHTML = html;
    
    // Attach event listeners
    attachRecommendationListeners();
}

/**
 * Render a single recommendation
 */
function renderRecommendation(rec) {
    const priorityColor = PRIORITY_COLORS[rec.priority] || '#6c757d';
    const categoryIcon = CATEGORY_ICONS[rec.category] || '📌';
    const priorityBadge = getPriorityBadge(rec.priority);
    
    let relatedInfo = '';
    if (rec.related_job) {
        relatedInfo = `<div class="small text-muted mb-2"><strong>Job:</strong> ${rec.related_job.name}</div>`;
    } else if (rec.related_connection) {
        relatedInfo = `<div class="small text-muted mb-2"><strong>Connection:</strong> ${rec.related_connection.name}</div>`;
    }
    
    let actionButtons = '';
    if (rec.action_url) {
        actionButtons = `<a href="${rec.action_url}" class="btn btn-sm btn-primary me-2">View Details</a>`;
    }
    actionButtons += `<button class="btn btn-sm btn-outline-secondary dismiss-btn" data-rec-id="${rec.id}">Dismiss</button>`;
    
    return `
        <div class="list-group-item recommendation-item" data-rec-id="${rec.id}">
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1">
                    <div class="d-flex align-items-center mb-2">
                        <span class="me-2">${categoryIcon}</span>
                        ${priorityBadge}
                        <h6 class="mb-0 ms-2">${escapeHtml(rec.title)}</h6>
                    </div>
                    ${relatedInfo}
                    <p class="mb-2 text-muted">${escapeHtml(rec.description)}</p>
                    <div class="mt-2">
                        ${actionButtons}
                    </div>
                </div>
            </div>
        </div>
    `;
}

/**
 * Get priority badge HTML
 */
function getPriorityBadge(priority) {
    const badges = {
        'high': '<span class="badge bg-danger">High</span>',
        'medium': '<span class="badge bg-warning text-dark">Medium</span>',
        'low': '<span class="badge bg-success">Low</span>'
    };
    return badges[priority] || '<span class="badge bg-secondary">Unknown</span>';
}

/**
 * Attach event listeners for recommendations
 */
function attachRecommendationListeners() {
    // Dismiss buttons
    document.querySelectorAll('.dismiss-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const recId = this.getAttribute('data-rec-id');
            dismissRecommendation(recId);
        });
    });
}

/**
 * Dismiss a recommendation
 */
function dismissRecommendation(recId) {
    if (!confirm('Are you sure you want to dismiss this recommendation?')) {
        return;
    }
    
    // Get CSRF token
    const csrftoken = getCookie('csrftoken');
    
    fetch(`/api/sync-jobs/recommendations/${recId}/dismiss/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrftoken
        },
        credentials: 'same-origin'
    })
    .then(response => response.json())
    .then(data => {
        if (data.id) {
            // Remove recommendation from UI
            const item = document.querySelector(`.recommendation-item[data-rec-id="${recId}"]`);
            if (item) {
                item.style.opacity = '0.5';
                item.innerHTML = '<div class="text-muted"><em>Dismissed</em></div>';
                setTimeout(() => {
                    item.remove();
                    updateRecommendationsCount();
                }, 500);
            }
            
            // Show success message
            showNotification('Recommendation dismissed', 'success');
        } else {
            showNotification('Failed to dismiss recommendation', 'error');
        }
    })
    .catch(error => {
        console.error('Error dismissing recommendation:', error);
        showNotification('Error dismissing recommendation', 'error');
    });
}

/**
 * Refresh recommendations
 */
function refreshRecommendations() {
    const container = document.getElementById('recommendationsContainer');
    if (container) {
        container.innerHTML = '<div class="text-center p-3"><div class="spinner-border text-primary" role="status"></div></div>';
    }
    
    // Get CSRF token
    const csrftoken = getCookie('csrftoken');
    
    // Trigger refresh
    fetch('/api/sync-jobs/recommendations/refresh/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrftoken
        },
        credentials: 'same-origin'
    })
    .then(response => response.json())
    .then(data => {
        // Reload recommendations
        loadRecommendations();
        showNotification(`Generated ${data.generated} new recommendations`, 'success');
    })
    .catch(error => {
        console.error('Error refreshing recommendations:', error);
        showNotification('Error refreshing recommendations', 'error');
        loadRecommendations(); // Still try to load existing
    });
}

/**
 * Load recommendations from API
 */
function loadRecommendations() {
    fetch('/api/sync-jobs/recommendations/')
        .then(response => response.json())
        .then(data => {
            initRecommendations(data.results || []);
            updateRecommendationsCount(data.count || 0);
        })
        .catch(error => {
            console.error('Error loading recommendations:', error);
            const container = document.getElementById('recommendationsContainer');
            if (container) {
                container.innerHTML = '<div class="alert alert-danger">Error loading recommendations</div>';
            }
        });
}

/**
 * Update recommendations count badge
 */
function updateRecommendationsCount(count) {
    const badge = document.getElementById('recommendationsCountBadge');
    if (badge) {
        if (count !== undefined) {
            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline' : 'none';
        } else {
            // Fetch count from API
            fetch('/api/sync-jobs/recommendations/stats/')
                .then(response => response.json())
                .then(data => {
                    badge.textContent = data.total || 0;
                    badge.style.display = (data.total || 0) > 0 ? 'inline' : 'none';
                })
                .catch(error => console.error('Error loading recommendation stats:', error));
        }
    }
}

/**
 * Utility: Escape HTML
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Utility: Get cookie value
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
 * Utility: Show notification
 */
function showNotification(message, type) {
    // Use existing notification system if available
    if (typeof showToast === 'function') {
        showToast(message, type);
    } else {
        // Fallback to alert
        alert(message);
    }
}

// Auto-refresh recommendations every 5 minutes
if (typeof setInterval !== 'undefined') {
    setInterval(loadRecommendations, 5 * 60 * 1000);
}
