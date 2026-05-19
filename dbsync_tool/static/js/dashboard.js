/**
 * Dashboard JavaScript for real-time AJAX updates
 * No more full page reloads - only updates the data that changes
 */

(function() {
    'use strict';

    let refreshInterval;
    let lastUpdateTimestamp = null;

    /**
     * Update dashboard data via AJAX without reloading the page
     */
    function updateDashboardData() {
        fetch('/sync-jobs/api/dashboard/')
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                if (!data.success) {
                    console.error('Dashboard API returned error:', data.error);
                    return;
                }

                // Update KPI cards
                updateKPICards(data.stats);

                // Update recent activity table
                updateRecentActivity(data.recent_activity);

                // Store timestamp
                lastUpdateTimestamp = data.timestamp;

                console.log('Dashboard updated successfully at', new Date().toLocaleTimeString());
            })
            .catch(error => {
                console.error('Error updating dashboard:', error);
                // Don't show error to user - just log it and try again next interval
            });
    }

    /**
     * Update KPI card values without changing the UI structure
     */
    function updateKPICards(stats) {
        // Find and update each metric by looking for the metric values
        const metricSelectors = {
            'total_jobs': '.stat-card .metric-value',
            'success_rate': '.stat-card .metric-value',
            'executions_24h': '.stat-card .metric-value',
            'rows_synced_30d': '.stat-card .metric-value',
            'avg_duration': '.stat-card .metric-value',
            'total_connections': '.stat-card .metric-value'
        };

        // Update Total Jobs (first card)
        const cards = document.querySelectorAll('.stat-card');
        if (cards.length >= 1 && stats.total_jobs !== undefined) {
            const valueEl = cards[0].querySelector('.metric-value');
            if (valueEl) animateNumberChange(valueEl, stats.total_jobs);
        }

        // Update Success Rate (second card)
        if (cards.length >= 2 && stats.success_rate !== undefined) {
            const valueEl = cards[1].querySelector('.metric-value');
            if (valueEl) animateNumberChange(valueEl, stats.success_rate.toFixed(1) + '%');
        }

        // Update Executions 24h (third card)
        if (cards.length >= 3 && stats.executions_24h !== undefined) {
            const valueEl = cards[2].querySelector('.metric-value');
            if (valueEl) animateNumberChange(valueEl, stats.executions_24h);
        }

        // Update Rows Synced 30d (fourth card)
        if (cards.length >= 4 && stats.rows_synced_30d !== undefined) {
            const valueEl = cards[3].querySelector('.metric-value');
            if (valueEl) animateNumberChange(valueEl, formatNumber(stats.rows_synced_30d));
        }

        // Update Avg Duration (fifth card)
        if (cards.length >= 5 && stats.avg_duration !== undefined) {
            const valueEl = cards[4].querySelector('.metric-value');
            if (valueEl) animateNumberChange(valueEl, Math.round(stats.avg_duration) + 's');
        }

        // Update Total Connections (sixth card)
        if (cards.length >= 6 && stats.total_connections !== undefined) {
            const valueEl = cards[5].querySelector('.metric-value');
            if (valueEl) animateNumberChange(valueEl, stats.total_connections);
        }
    }

    /**
     * Animate number changes with a brief highlight effect
     */
    function animateNumberChange(element, newValue) {
        const currentValue = element.textContent.trim();
        const newValueStr = String(newValue);

        if (currentValue !== newValueStr) {
            // Add highlight animation
            element.style.transition = 'color 0.3s ease';
            element.style.color = '#43e97b'; // Green highlight
            element.textContent = newValueStr;

            // Remove highlight after animation
            setTimeout(() => {
                element.style.color = '';
            }, 500);
        }
    }

    /**
     * Format large numbers with commas
     */
    function formatNumber(num) {
        if (num >= 1000000) {
            return (num / 1000000).toFixed(1) + 'M';
        } else if (num >= 1000) {
            return (num / 1000).toFixed(1) + 'K';
        }
        return num.toLocaleString();
    }

    /**
     * Update the recent activity table
     */
    function updateRecentActivity(activities) {
        const tbody = document.querySelector('#recent-activity-table tbody');
        if (!tbody) return;

        if (!activities || activities.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4" class="px-8 py-12 text-center">
                        <div class="flex flex-col items-center gap-4">
                            <p class="font-medium italic" style="color: #64748b;">No recent activity detected</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = activities.map(exec => {
            const statusBadge = getStatusBadgeHTML(exec.status);
            const jobLink = exec.job_id ? `/sync-jobs/${exec.job_id}/` : '#';
            const execLink = exec.job_id ? `/sync-jobs/${exec.job_id}/executions/${exec.id}/` : '#';

            return `
                <tr class="border-b hover:bg-gray-50 transition-colors duration-150">
                    <td class="px-6 py-4">
                        <a href="${jobLink}" class="font-semibold text-indigo-600 hover:text-indigo-800 hover:underline">
                            ${escapeHtml(exec.job_name)}
                        </a>
                    </td>
                    <td class="px-6 py-4 text-sm text-gray-600">
                        <a href="${execLink}" class="hover:text-indigo-600">
                            ${exec.started_at_display}
                        </a>
                    </td>
                    <td class="px-6 py-4 text-sm font-medium text-gray-700">
                        ${formatNumber(exec.total_rows_synced)} rows
                    </td>
                    <td class="px-6 py-4">
                        ${statusBadge}
                    </td>
                </tr>
            `;
        }).join('');
    }

    /**
     * Get HTML for status badge based on execution status
     */
    function getStatusBadgeHTML(status) {
        if (status === 'completed') {
            return `
                <div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-gradient-to-r from-green-50 to-emerald-50 text-green-700 border border-green-200 shadow-sm">
                    <div class="w-1.5 h-1.5 rounded-full bg-green-500"></div>
                    <span class="text-[10px] font-black uppercase tracking-widest">Success</span>
                </div>
            `;
        } else if (status === 'failed') {
            return `
                <div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-gradient-to-r from-red-50 to-rose-50 text-red-700 border border-red-200 shadow-sm">
                    <div class="w-1.5 h-1.5 rounded-full bg-red-500"></div>
                    <span class="text-[10px] font-black uppercase tracking-widest">Failed</span>
                </div>
            `;
        } else if (status === 'running') {
            return `
                <div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-gradient-to-r from-blue-50 to-indigo-50 text-blue-700 border border-blue-200 shadow-sm">
                    <div class="w-1.5 h-1.5 rounded-full bg-blue-500 relative">
                        <span class="absolute w-1.5 h-1.5 rounded-full bg-blue-500 animate-ping"></span>
                    </div>
                    <span class="text-[10px] font-black uppercase tracking-widest">Running</span>
                </div>
            `;
        }
        return `<span class="badge">${status}</span>`;
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
     * Initialize AJAX refresh system
     */
    function initDashboardRefresh() {
        // Only refresh if we're on the dashboard page
        if (document.querySelector('.stat-card') || document.getElementById('recent-activity-table')) {
            // Update immediately on load
            setTimeout(updateDashboardData, 2000);

            // Then update every 15 seconds (reduced from 30 seconds)
            refreshInterval = setInterval(updateDashboardData, 15000);

            console.log('Dashboard AJAX refresh initialized (every 15 seconds)');
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

