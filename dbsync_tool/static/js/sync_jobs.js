/**
 * JavaScript for sync jobs interactive features
 */

document.addEventListener('DOMContentLoaded', function() {
    // Confirmation dialogs for destructive actions
    setupConfirmationDialogs();
    
    // AJAX for pause/resume/run now (if needed in future)
    setupAjaxActions();
    
    // Form validation enhancements
    setupFormValidation();
});

/**
 * Setup confirmation dialogs for delete, pause, resume actions
 */
function setupConfirmationDialogs() {
    // Delete confirmation is handled inline in templates with onclick
    // But we can enhance it here if needed
    
    // Pause/Resume confirmations
    const pauseButtons = document.querySelectorAll('a[href*="/pause/"]');
    pauseButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            if (!confirm('Are you sure you want to pause this job? Scheduled runs will be disabled.')) {
                e.preventDefault();
            }
        });
    });
    
    const resumeButtons = document.querySelectorAll('a[href*="/resume/"]');
    resumeButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            if (!confirm('Are you sure you want to resume this job? Scheduled runs will be enabled.')) {
                e.preventDefault();
            }
        });
    });
    
    const runButtons = document.querySelectorAll('a[href*="/run/"]');
    runButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            if (!confirm('Are you sure you want to run this job now?')) {
                e.preventDefault();
            }
        });
    });
}

/**
 * Setup AJAX actions for pause/resume/run (for future enhancement)
 */
function setupAjaxActions() {
    // This can be enhanced later to use AJAX instead of page reloads
    // For now, actions use standard form submissions
}

/**
 * Enhanced form validation
 */
function setupFormValidation() {
    // Job edit form validation
    const editForm = document.getElementById('edit-form');
    if (editForm) {
        editForm.addEventListener('submit', function(e) {
            const jobName = document.getElementById('job_name');
            if (jobName && !jobName.value.trim()) {
                e.preventDefault();
                alert('Job name is required.');
                jobName.focus();
                return false;
            }
        });
    }
    
    // Step 3 form validation (already handled in template, but can enhance here)
    const step3Form = document.getElementById('step3-form');
    if (step3Form) {
        // Additional validation if needed
    }
}

/**
 * Show loading state for buttons
 */
function showLoadingState(button, text = 'Processing...') {
    if (button) {
        button.disabled = true;
        button.dataset.originalText = button.textContent;
        button.textContent = text;
    }
}

/**
 * Hide loading state for buttons
 */
function hideLoadingState(button) {
    if (button && button.dataset.originalText) {
        button.disabled = false;
        button.textContent = button.dataset.originalText;
        delete button.dataset.originalText;
    }
}

/**
 * Update status badge dynamically (for future real-time updates)
 */
function updateStatusBadge(jobId, newStatus) {
    const badge = document.querySelector(`[data-job-id="${jobId}"] .status-badge`);
    if (badge) {
        badge.className = `badge bg-${getStatusColor(newStatus)}`;
        badge.textContent = newStatus;
    }
}

/**
 * Get status color class
 */
function getStatusColor(status) {
    const colorMap = {
        'pending': 'secondary',
        'running': 'primary',
        'completed': 'success',
        'failed': 'danger',
        'paused': 'warning'
    };
    return colorMap[status] || 'secondary';
}

/**
 * Auto-hide alerts after 5 seconds
 */
function autoHideAlerts() {
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.transition = 'opacity 0.5s';
            alert.style.opacity = '0';
            setTimeout(() => {
                if (alert.parentNode) {
                    alert.remove();
                }
            }, 500);
        }, 5000);
    });
}

// Auto-hide alerts on page load
autoHideAlerts();

