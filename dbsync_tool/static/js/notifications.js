/**
 * Toast notification system for user feedback
 */

// Notification types
const NOTIFICATION_TYPES = {
    SUCCESS: 'success',
    ERROR: 'error',
    WARNING: 'warning',
    INFO: 'info'
};

// Notification container
let notificationContainer = null;

/**
 * Initialize notification system
 */
function initNotifications() {
    if (!notificationContainer) {
        notificationContainer = document.createElement('div');
        notificationContainer.id = 'notification-container';
        notificationContainer.className = 'position-fixed top-0 end-0 p-3';
        notificationContainer.style.zIndex = '9999';
        document.body.appendChild(notificationContainer);
    }
}

/**
 * Show a notification
 * 
 * @param {string} message - Notification message
 * @param {string} type - Notification type (success, error, warning, info)
 * @param {number} duration - Auto-dismiss duration in milliseconds (0 = no auto-dismiss)
 */
function showNotification(message, type = 'info', duration = 5000) {
    initNotifications();
    
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `alert alert-${getAlertClass(type)} alert-dismissible fade show`;
    notification.style.minWidth = '300px';
    notification.style.marginBottom = '10px';
    notification.style.boxShadow = '0 4px 6px rgba(0, 0, 0, 0.1)';
    
    // Add icon
    const icon = getIcon(type);
    
    notification.innerHTML = `
        ${icon}
        <span>${escapeHtml(message)}</span>
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    
    // Add to container
    notificationContainer.appendChild(notification);
    
    // Auto-dismiss
    if (duration > 0) {
        setTimeout(() => {
            if (notification.parentNode) {
                notification.classList.remove('show');
                setTimeout(() => {
                    if (notification.parentNode) {
                        notification.remove();
                    }
                }, 150); // Wait for fade animation
            }
        }, duration);
    }
    
    return notification;
}

/**
 * Get Bootstrap alert class for notification type
 */
function getAlertClass(type) {
    const classMap = {
        'success': 'success',
        'error': 'danger',
        'warning': 'warning',
        'info': 'info'
    };
    return classMap[type] || 'info';
}

/**
 * Get icon for notification type
 */
function getIcon(type) {
    const iconMap = {
        'success': '<i class="bi bi-check-circle-fill me-2"></i>',
        'error': '<i class="bi bi-x-circle-fill me-2"></i>',
        'warning': '<i class="bi bi-exclamation-triangle-fill me-2"></i>',
        'info': '<i class="bi bi-info-circle-fill me-2"></i>'
    };
    return iconMap[type] || '';
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
 * Show success notification
 */
function showSuccess(message, duration = 5000) {
    return showNotification(message, NOTIFICATION_TYPES.SUCCESS, duration);
}

/**
 * Show error notification
 */
function showError(message, duration = 7000) {
    return showNotification(message, NOTIFICATION_TYPES.ERROR, duration);
}

/**
 * Show warning notification
 */
function showWarning(message, duration = 6000) {
    return showNotification(message, NOTIFICATION_TYPES.WARNING, duration);
}

/**
 * Show info notification
 */
function showInfo(message, duration = 5000) {
    return showNotification(message, NOTIFICATION_TYPES.INFO, duration);
}

// Initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNotifications);
} else {
    initNotifications();
}

