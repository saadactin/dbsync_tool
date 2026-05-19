/**
 * Real-time status updates using Server-Sent Events (SSE)
 *
 * Usage:
 *
 * Dashboard:
 *   const statusUpdater = new DashboardStatusUpdater();
 *   statusUpdater.start();
 *
 * Execution Detail:
 *   const statusUpdater = new ExecutionStatusUpdater(executionId);
 *   statusUpdater.start();
 */

class SSEClient {
    constructor(url, onMessage, onError) {
        this.url = url;
        this.onMessage = onMessage;
        this.onError = onError || ((e) => console.error('SSE Error:', e));
        this.eventSource = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 2000;
    }

    start() {
        if (this.eventSource) {
            console.warn('SSE already started');
            return;
        }

        console.log('Starting SSE connection:', this.url);
        this.eventSource = new EventSource(this.url);

        this.eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.reconnectAttempts = 0; // Reset on successful message
                this.onMessage(data);

                // Auto-close on completion
                if (data.type === 'close' || data.type === 'completed') {
                    console.log('SSE stream closed by server');
                    this.stop();
                }
            } catch (e) {
                console.error('Failed to parse SSE message:', e);
            }
        };

        this.eventSource.onerror = (event) => {
            console.error('SSE connection error');
            this.onError(event);

            // Auto-reconnect with exponential backoff
            if (this.reconnectAttempts < this.maxReconnectAttempts) {
                this.reconnectAttempts++;
                const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
                console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

                setTimeout(() => {
                    if (this.eventSource) {
                        this.stop();
                        this.start();
                    }
                }, delay);
            } else {
                console.error('Max reconnect attempts reached, giving up');
                this.stop();
            }
        };

        this.eventSource.onopen = () => {
            console.log('SSE connection established');
        };
    }

    stop() {
        if (this.eventSource) {
            console.log('Stopping SSE connection');
            this.eventSource.close();
            this.eventSource = null;
        }
    }

    isConnected() {
        return this.eventSource && this.eventSource.readyState === EventSource.OPEN;
    }
}


class DashboardStatusUpdater {
    constructor() {
        this.sseClient = null;
    }

    start() {
        const url = '/sync-jobs/sse/dashboard/';

        this.sseClient = new SSEClient(
            url,
            (data) => this.handleUpdate(data),
            (error) => this.handleError(error)
        );

        this.sseClient.start();
    }

    stop() {
        if (this.sseClient) {
            this.sseClient.stop();
            this.sseClient = null;
        }
    }

    handleUpdate(data) {
        if (data.type === 'initial' || data.type === 'update') {
            this.updateDashboard(data.jobs);
        } else if (data.type === 'error') {
            console.error('Dashboard SSE error:', data.message);
            this.showNotification('Connection error: ' + data.message, 'error');
        }
    }

    handleError(error) {
        console.error('Dashboard SSE connection error:', error);
    }

    updateDashboard(jobs) {
        // Update each job card on the dashboard
        jobs.forEach(job => {
            this.updateJobCard(job);
        });

        // Show notification for newly completed jobs
        jobs.forEach(job => {
            if (job.execution_status === 'completed') {
                const lastNotified = localStorage.getItem(`job_${job.id}_last_notified`);
                const currentExec = job.execution_id;

                if (lastNotified !== String(currentExec)) {
                    this.showNotification(`Job "${job.name}" completed successfully`, 'success');
                    localStorage.setItem(`job_${job.id}_last_notified`, currentExec);
                }
            } else if (job.execution_status === 'failed') {
                const lastNotified = localStorage.getItem(`job_${job.id}_last_notified`);
                const currentExec = job.execution_id;

                if (lastNotified !== String(currentExec)) {
                    this.showNotification(`Job "${job.name}" failed`, 'error');
                    localStorage.setItem(`job_${job.id}_last_notified`, currentExec);
                }
            }
        });
    }

    updateJobCard(job) {
        // Find job card by job ID
        const card = document.querySelector(`[data-job-id="${job.id}"]`);
        if (!card) return;

        // Update status badge
        const statusBadge = card.querySelector('.job-status-badge');
        if (statusBadge) {
            statusBadge.textContent = job.status;
            statusBadge.className = `job-status-badge status-${job.status}`;
        }

        // Update last run time
        const lastRunElement = card.querySelector('.job-last-run');
        if (lastRunElement && job.last_run) {
            const date = new Date(job.last_run);
            lastRunElement.textContent = this.formatRelativeTime(date);
        }

        // Update duration
        const durationElement = card.querySelector('.job-duration');
        if (durationElement && job.duration) {
            durationElement.textContent = this.formatDuration(job.duration);
        }

        // Update rows synced
        const rowsElement = card.querySelector('.job-rows-synced');
        if (rowsElement) {
            rowsElement.textContent = this.formatNumber(job.rows_synced);
        }

        // Add running indicator
        if (job.execution_status === 'running') {
            card.classList.add('job-running');
        } else {
            card.classList.remove('job-running');
        }
    }

    formatRelativeTime(date) {
        const now = new Date();
        const diff = Math.floor((now - date) / 1000); // seconds

        if (diff < 60) return 'Just now';
        if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
        return `${Math.floor(diff / 86400)}d ago`;
    }

    formatDuration(seconds) {
        if (seconds < 60) return `${Math.round(seconds)}s`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
        return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
    }

    formatNumber(num) {
        return new Intl.NumberFormat().format(num);
    }

    showNotification(message, type = 'info') {
        // Create toast notification
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 20px;
            background: ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6'};
            color: white;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 9999;
            animation: slideIn 0.3s ease-out;
        `;

        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(() => toast.remove(), 300);
        }, 5000);
    }
}


class ExecutionStatusUpdater {
    constructor(executionId) {
        this.executionId = executionId;
        this.sseClient = null;
    }

    start() {
        const url = `/sync-jobs/sse/execution/${this.executionId}/`;

        this.sseClient = new SSEClient(
            url,
            (data) => this.handleUpdate(data),
            (error) => this.handleError(error)
        );

        this.sseClient.start();
    }

    stop() {
        if (this.sseClient) {
            this.sseClient.stop();
            this.sseClient = null;
        }
    }

    handleUpdate(data) {
        if (data.type === 'initial' || data.type === 'update') {
            this.updateExecutionDetail(data.execution);
        } else if (data.type === 'completed') {
            this.updateExecutionDetail(data.execution);
            this.showCompletionNotification(data.execution);
            this.stop(); // Stop polling after completion
        } else if (data.type === 'error') {
            console.error('Execution SSE error:', data.message);
        }
    }

    handleError(error) {
        console.error('Execution SSE connection error:', error);
    }

    updateExecutionDetail(execution) {
        // Update status badge
        const statusBadge = document.querySelector('.execution-status-badge');
        if (statusBadge) {
            statusBadge.textContent = execution.status;
            statusBadge.className = `execution-status-badge status-${execution.status}`;
        }

        // Update progress metrics
        const rowsFetched = document.querySelector('.execution-rows-fetched');
        if (rowsFetched) {
            rowsFetched.textContent = this.formatNumber(execution.rows_fetched);
        }

        const rowsInserted = document.querySelector('.execution-rows-inserted');
        if (rowsInserted) {
            rowsInserted.textContent = this.formatNumber(execution.rows_inserted);
        }

        const duration = document.querySelector('.execution-duration');
        if (duration && execution.duration_seconds) {
            duration.textContent = this.formatDuration(execution.duration_seconds);
        }

        // Update table-level status
        if (execution.table_status) {
            execution.table_status.forEach(table => {
                this.updateTableRow(table);
            });
        }

        // Update error message if any
        if (execution.error_message) {
            const errorContainer = document.querySelector('.execution-error-message');
            if (errorContainer) {
                errorContainer.textContent = execution.error_message;
                errorContainer.style.display = 'block';
            }
        }
    }

    updateTableRow(table) {
        const row = document.querySelector(`[data-table-name="${table.table_name}"]`);
        if (!row) return;

        // Update status
        const statusCell = row.querySelector('.table-status');
        if (statusCell) {
            statusCell.textContent = table.status;
            statusCell.className = `table-status status-${table.status}`;
        }

        // Update rows
        const fetchedCell = row.querySelector('.table-rows-fetched');
        if (fetchedCell) {
            fetchedCell.textContent = this.formatNumber(table.rows_fetched);
        }

        const insertedCell = row.querySelector('.table-rows-inserted');
        if (insertedCell) {
            insertedCell.textContent = this.formatNumber(table.rows_inserted);
        }

        // Update error if any
        if (table.error_message) {
            const errorCell = row.querySelector('.table-error');
            if (errorCell) {
                errorCell.textContent = table.error_message;
                errorCell.style.display = 'block';
            }
        }
    }

    formatNumber(num) {
        return new Intl.NumberFormat().format(num);
    }

    formatDuration(seconds) {
        if (seconds < 60) return `${Math.round(seconds)}s`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
        return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
    }

    showCompletionNotification(execution) {
        const message = execution.status === 'completed'
            ? `Execution completed: ${this.formatNumber(execution.rows_inserted)} rows synced`
            : `Execution failed: ${execution.error_message}`;

        const type = execution.status === 'completed' ? 'success' : 'error';

        // Use browser notification if permitted
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(`Sync Job: ${execution.job_name}`, {
                body: message,
                icon: '/static/images/icon.png'
            });
        }

        // Also show toast
        this.showToast(message, type);
    }

    showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 20px;
            background: ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6'};
            color: white;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 9999;
        `;

        document.body.appendChild(toast);

        setTimeout(() => toast.remove(), 5000);
    }
}


// Request browser notification permission on page load
if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
}
