/**
 * Dashboard JavaScript for real-time updates
 */

(function() {
    'use strict';
    
    // Auto-refresh dashboard statistics every 30 seconds
    let refreshInterval;
    
    function initDashboardRefresh() {
        // Only refresh if we're on the dashboard page
        if (document.querySelector('.dashboard-stats')) {
            refreshInterval = setInterval(function() {
                // Reload the page to get fresh data
                // In a production app, you might want to use AJAX instead
                location.reload();
            }, 30000); // 30 seconds
        }
    }
    
    // Initialize on page load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDashboardRefresh);
    } else {
        initDashboardRefresh();
    }
    
    // Clean up on page unload
    window.addEventListener('beforeunload', function() {
        if (refreshInterval) {
            clearInterval(refreshInterval);
        }
    });
    
    // Real-time execution status updates
    function updateExecutionStatus() {
        // Find all running execution badges
        const runningBadges = document.querySelectorAll('.badge.bg-primary');
        runningBadges.forEach(function(badge) {
            const executionId = badge.getAttribute('data-execution-id');
            if (executionId) {
                // Fetch status via AJAX
                fetch(`/sync-jobs/executions/${executionId}/status/`)
                    .then(response => response.json())
                    .then(data => {
                        if (data.status !== 'running') {
                            // Update badge
                            badge.className = 'badge bg-' + (data.status === 'completed' ? 'success' : 'danger');
                            badge.textContent = data.status_display;
                        }
                    })
                    .catch(error => console.error('Error updating execution status:', error));
            }
        });
    }
    
    // Update execution status every 5 seconds
    setInterval(updateExecutionStatus, 5000);
    
    // Toast notifications for job status changes
    function showToast(message, type) {
        const toast = document.createElement('div');
        toast.className = `alert alert-${type} alert-dismissible fade show`;
        toast.style.position = 'fixed';
        toast.style.top = '20px';
        toast.style.right = '20px';
        toast.style.zIndex = '9999';
        toast.style.minWidth = '300px';
        toast.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        document.body.appendChild(toast);
        
        // Auto-dismiss after 5 seconds
        setTimeout(function() {
            toast.remove();
        }, 5000);
    }
    
    // Expose showToast globally
    window.showToast = showToast;
})();

