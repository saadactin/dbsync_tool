/**
 * Dashboard JavaScript for progressive loading with skeleton screens
 * Instant page render + async data loading
 */

(function() {
    'use strict';

    let refreshInterval;
    let lastUpdateTimestamp = null;
    let isInitialLoad = true;
    let chartsInitialized = false;

    /**
     * Initial load - fetch ALL dashboard data and replace skeletons
     */
    function loadDashboardData() {
        console.log('Loading dashboard data...');

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
                    showError('Failed to load dashboard data');
                    return;
                }

                // Replace skeletons with real data
                replaceSkeletonsWithData(data);

                // Update KPI cards
                updateKPICards(data.stats);

                // Update recent activity table
                updateRecentActivity(data.recent_activity);

                // Update health check
                if (data.health_check_data) {
                    updateHealthCheck(data.health_check_data);
                }

                // Initialize charts (only once)
                if (!chartsInitialized && typeof ApexCharts !== 'undefined') {
                    initializeCharts(data);
                    chartsInitialized = true;
                }

                // Store timestamp
                lastUpdateTimestamp = data.timestamp;
                isInitialLoad = false;

                console.log('Dashboard loaded successfully at', new Date().toLocaleTimeString());
            })
            .catch(error => {
                console.error('Error loading dashboard:', error);
                showError('Network error loading dashboard');
            });
    }

    /**
     * Subsequent updates - just refresh data, don't recreate everything
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

                // Update health check
                if (data.health_check_data) {
                    updateHealthCheck(data.health_check_data);
                }

                // Update charts if they exist
                if (chartsInitialized && typeof ApexCharts !== 'undefined') {
                    updateChartData(data);
                }

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
     * Replace skeleton placeholders with real content structure
     */
    function replaceSkeletonsWithData(data) {
        // Remove skeleton classes from KPI cards
        const skeletonCards = document.querySelectorAll('.skeleton-stat-card');
        skeletonCards.forEach((card, index) => {
            card.classList.remove('skeleton-stat-card');
            const skeletonContent = card.querySelector('.skeleton-content');
            if (skeletonContent) {
                skeletonContent.remove();
            }

            // Add real content structure
            const labels = ['Total Relays', 'Success Rate', 'Executions (24H)', 'Rows Synced', 'Avg Latency', 'DB Clusters'];
            card.innerHTML = `
                <div class="metric-label" style="margin-bottom: 4px;">${labels[index]}</div>
                <div class="metric-value">—</div>
                <div class="mt-2 text-xs" style="color: #605E5C;">Loading...</div>
            `;

            // Fade in animation
            card.classList.add('fade-in');
        });

        // Remove skeleton from charts
        const skeletonCharts = document.querySelectorAll('.skeleton-chart');
        skeletonCharts.forEach(chart => {
            chart.classList.remove('skeleton-chart');
            chart.classList.add('fade-in');
        });

        // Remove skeleton from table
        const skeletonRows = document.querySelectorAll('.skeleton-table-row');
        skeletonRows.forEach(row => row.remove());

        // Remove skeleton from health check
        const healthContainer = document.getElementById('health-check-container');
        if (healthContainer && healthContainer.classList.contains('skeleton-health-card')) {
            healthContainer.classList.remove('skeleton-health-card');
            healthContainer.classList.add('fade-in');
        }
    }

    /**
     * Update KPI card values
     */
    function updateKPICards(stats) {
        const cards = document.querySelectorAll('.stat-card');

        if (cards.length >= 1) {
            updateCard(cards[0], stats.total_jobs || 0, `${stats.active_jobs || 0} Active`);
        }
        if (cards.length >= 2) {
            updateCard(cards[1], `${stats.success_rate || 0}%`, `${stats.executions_24h || 0} Executions`);
        }
        if (cards.length >= 3) {
            updateCard(cards[2], stats.executions_24h || 0, `7D: ${stats.executions_7d || 0}`);
        }
        if (cards.length >= 4) {
            updateCard(cards[3], formatNumber(stats.rows_synced_30d || 0), `24H: ${formatNumber(stats.rows_synced_24h || 0)}`);
        }
        if (cards.length >= 5) {
            const avgDuration = stats.avg_duration ? `${Math.round(stats.avg_duration)}s` : 'N/A';
            updateCard(cards[4], avgDuration, 'Completion Time');
        }
        if (cards.length >= 6) {
            updateCard(cards[5], stats.total_connections || 0, `API: ${stats.api_connections || 0}`);
        }
    }

    /**
     * Update a single KPI card
     */
    function updateCard(card, value, subtitle) {
        const valueEl = card.querySelector('.metric-value');
        const subtitleEl = card.querySelector('.mt-2.text-xs');

        if (valueEl && valueEl.textContent !== String(value)) {
            animateNumberChange(valueEl, value);
        }
        if (subtitleEl) {
            subtitleEl.textContent = subtitle;
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
        const tbody = document.getElementById('activity-tbody');
        if (!tbody) return;

        if (!activities || activities.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4" class="px-4 py-12 text-center">
                        <div class="flex flex-col items-center gap-3">
                            <span class="material-symbols-outlined text-4xl" style="color: #A19F9D;">inventory_2</span>
                            <p class="text-sm" style="color: #605E5C;">No recent activity detected</p>
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
                <tr class="transition-all cursor-pointer" style="border-bottom: 1px solid #EDEBE9; background: #FFFFFF;" onmouseover="this.style.background='#EFF6FC'" onmouseout="this.style.background='#FFFFFF'" onclick="window.location='${execLink}'">
                    <td class="px-4 py-3" style="min-height: 44px;">
                        <div class="flex items-center gap-3">
                            <div class="text-sm font-semibold" style="color: #323130;">${escapeHtml(exec.job_name)}</div>
                        </div>
                    </td>
                    <td class="px-4 py-3">
                        <div class="text-xs" style="color: #605E5C;">
                            ${exec.started_at_display}
                        </div>
                    </td>
                    <td class="px-4 py-3">
                        <div class="text-xs tabular-nums" style="color: #323130;">
                            ${formatNumber(exec.total_rows_synced)} rows
                        </div>
                    </td>
                    <td class="px-4 py-3 text-right">
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
            return `<span class="inline-flex items-center px-2 py-1 rounded-sm text-xs font-semibold" style="background: #DFF6DD; color: #107C10; border-radius: 2px;">Success</span>`;
        } else if (status === 'failed') {
            return `<span class="inline-flex items-center px-2 py-1 rounded-sm text-xs font-semibold" style="background: #FDE7E9; color: #A80000; border-radius: 2px;">Failed</span>`;
        } else if (status === 'running') {
            return `<span class="inline-flex items-center px-2 py-1 rounded-sm text-xs font-semibold" style="background: #EFF6FC; color: #0078D4; border-radius: 2px;">Running</span>`;
        }
        return `<span class="badge">${status}</span>`;
    }

    /**
     * Update health check display
     */
    function updateHealthCheck(healthData) {
        const lastCheckTime = document.getElementById('last-check-time');
        if (lastCheckTime && healthData.tested_at) {
            const testDate = new Date(healthData.tested_at);
            const now = new Date();
            const diffMinutes = Math.floor((now - testDate) / 60000);
            const timeAgo = diffMinutes < 60
                ? `${diffMinutes} minutes ago`
                : diffMinutes < 1440
                    ? `${Math.floor(diffMinutes / 60)} hours ago`
                    : `${Math.floor(diffMinutes / 1440)} days ago`;
            lastCheckTime.textContent = `Last check: ${timeAgo}`;
        }
    }

    /**
     * Initialize all charts with data (called once on initial load)
     */
    function initializeCharts(data) {
        // Charts are initialized by the inline script in the template
        // This function is a placeholder for any additional chart initialization
        console.log('Charts initialized with data');
    }

    /**
     * Update existing chart data (for subsequent refreshes)
     */
    function updateChartData(data) {
        // Update chart data without recreating charts
        // Implementation depends on chart update needs
    }

    /**
     * Show error message to user
     */
    function showError(message) {
        if (typeof showToast !== 'undefined') {
            showToast(message, 'danger');
        } else {
            console.error(message);
        }
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
     * Initialize dashboard refresh system
     */
    function initDashboardRefresh() {
        // Check if we have skeleton cards (loading mode)
        const hasSkeletons = document.querySelector('.skeleton-stat-card') !== null;

        if (hasSkeletons) {
            // IMMEDIATE load for skeleton mode
            loadDashboardData();
        } else if (document.querySelector('.stat-card') || document.getElementById('activity-tbody')) {
            // Data already rendered (fallback), just update after delay
            setTimeout(updateDashboardData, 2000);
            isInitialLoad = false;
            chartsInitialized = true;
        }

        // Set up periodic refresh (every 15 seconds)
        refreshInterval = setInterval(updateDashboardData, 15000);

        console.log('Dashboard progressive loading initialized');
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
