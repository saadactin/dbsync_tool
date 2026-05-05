/**
 * Format and render connection test responses for inline UI and modal popups.
 * Expects: success, message, optional latency_ms, optional details (object).
 */
(function (global) {
    'use strict';

    function formatDetailsLines(details) {
        if (!details || typeof details !== 'object') {
            return [];
        }
        var lines = [];
        var order = ['name', 'db_type', 'api_type', 'host', 'port', 'database_name', 'api_domain', 'sap_base_url', 'organization'];
        var seen = {};
        order.forEach(function (key) {
            if (details[key] !== undefined && details[key] !== null && String(details[key]).length) {
                lines.push(key.replace(/_/g, ' ') + ': ' + details[key]);
                seen[key] = true;
            }
        });
        Object.keys(details).forEach(function (key) {
            if (seen[key]) {
                return;
            }
            var v = details[key];
            if (v !== undefined && v !== null && typeof v !== 'object') {
                lines.push(key.replace(/_/g, ' ') + ': ' + v);
            }
        });
        return lines;
    }

    function formatConnectionTestAlertPayload(data) {
        var parts = [];
        var headline = (data && data.message) ? String(data.message) : (data && data.success ? 'Connection successful.' : 'Connection test failed.');
        parts.push(headline);
        if (data && !data.success) {
            parts.push('Why it failed: ' + inferFailureReason(data));
        }
        if (data && typeof data.latency_ms === 'number') {
            parts.push('Round-trip: ' + data.latency_ms + ' ms');
        }
        var detailLines = formatDetailsLines(data && data.details);
        if (detailLines.length) {
            parts.push(detailLines.join('\n'));
        }
        return parts.join('\n\n');
    }

    function inferFailureReason(data) {
        var message = (data && data.message ? String(data.message) : '').toLowerCase();
        var details = (data && data.details) || {};
        var host = details.host ? String(details.host) : '';
        var port = details.port ? String(details.port) : '';

        if (message.indexOf('getaddrinfo failed') !== -1 || message.indexOf('name or service not known') !== -1 || message.indexOf('could not translate host name') !== -1) {
            return 'Host name could not be resolved. Verify host/DNS and avoid non-standard ports for Atlas SRV.';
        }
        if (message.indexOf('timed out') !== -1 || message.indexOf('timeout') !== -1) {
            return 'Connection timed out. Network path, firewall, allowlist, or port may be blocked.';
        }
        if (message.indexOf('authentication failed') !== -1 || message.indexOf('auth failed') !== -1 || message.indexOf('invalid credentials') !== -1) {
            return 'Authentication failed. Check username/password and auth database.';
        }
        if (message.indexOf('ssl') !== -1 || message.indexOf('tls') !== -1 || message.indexOf('certificate') !== -1) {
            return 'TLS/SSL handshake failed. Check certificate and driver TLS settings.';
        }
        if (message.indexOf('connection refused') !== -1 || message.indexOf('actively refused') !== -1) {
            return 'Target server refused the connection. Host/port may be wrong or service is down.';
        }
        if (message.indexOf('mongodb') !== -1 && host && port === '5000') {
            return 'MongoDB Atlas should not use port 5000. Use host only with port 27017.';
        }
        return 'Server rejected or could not establish the connection. Check host, port, credentials, and network allowlist.';
    }

    /**
     * Parse response as JSON; returns { ok, data, errorMessage }.
     */
    function parseConnectionTestResponse(response, bodyText) {
        var text = bodyText != null ? bodyText : '';
        try {
            var data = JSON.parse(text);
            return { ok: true, data: data, errorMessage: null };
        } catch (e) {
            return {
                ok: false,
                data: null,
                errorMessage: 'Invalid response from server.',
            };
        }
    }

    /** Escape and convert newlines to <br> for safe insertion into alert-like HTML blocks. */
    function formatConnectionTestMessageHtml(data) {
        var text = formatConnectionTestAlertPayload(data);
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML.replace(/\n/g, '<br>');
    }

    function ensureModalStyles() {
        if (document.getElementById('connection-test-modal-style')) {
            return;
        }
        var style = document.createElement('style');
        style.id = 'connection-test-modal-style';
        style.textContent = [
            '.ctm-backdrop{position:fixed;inset:0;background:rgba(15,23,42,.55);display:flex;align-items:center;justify-content:center;z-index:9999;padding:16px;}',
            '.ctm-modal{width:min(760px,95vw);max-height:85vh;overflow:hidden;background:#fff;border-radius:16px;border:1px solid #e2e8f0;box-shadow:0 20px 50px rgba(2,6,23,.35);display:flex;flex-direction:column;}',
            '.ctm-head{padding:14px 18px;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;justify-content:space-between;gap:12px;}',
            '.ctm-title{font-size:18px;font-weight:800;color:#0f172a;}',
            '.ctm-close{border:none;background:#f1f5f9;color:#334155;border-radius:10px;padding:6px 10px;font-size:12px;font-weight:700;cursor:pointer;}',
            '.ctm-body{padding:16px 18px;overflow:auto;color:#0f172a;}',
            '.ctm-chip{display:inline-block;padding:4px 10px;border-radius:999px;font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;margin-bottom:10px;}',
            '.ctm-chip.ok{background:#dcfce7;color:#166534;}',
            '.ctm-chip.err{background:#fee2e2;color:#991b1b;}',
            '.ctm-label{font-size:12px;font-weight:800;color:#334155;text-transform:uppercase;letter-spacing:.05em;margin:10px 0 4px;}',
            '.ctm-panel{background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:10px 12px;white-space:pre-wrap;word-break:break-word;font-size:13px;line-height:1.45;}',
            '.ctm-actions{padding:12px 18px;border-top:1px solid #e2e8f0;display:flex;justify-content:flex-end;gap:10px;}',
            '.ctm-btn{border:none;border-radius:10px;padding:8px 12px;font-size:12px;font-weight:800;cursor:pointer;}',
            '.ctm-btn.copy{background:#0f172a;color:#fff;}',
            '.ctm-btn.ok{background:#2563eb;color:#fff;}'
        ].join('');
        document.head.appendChild(style);
    }

    function showConnectionTestModal(data, options) {
        ensureModalStyles();
        var opts = options || {};
        var payloadText = formatConnectionTestAlertPayload(data);
        var reason = (data && !data.success) ? inferFailureReason(data) : '';
        var detailsText = formatDetailsLines(data && data.details).join('\n');
        var existing = document.getElementById('connection-test-modal-backdrop');
        if (existing) {
            existing.remove();
        }

        var backdrop = document.createElement('div');
        backdrop.id = 'connection-test-modal-backdrop';
        backdrop.className = 'ctm-backdrop';
        var title = opts.title || 'Connection Test Result';
        var ok = !!(data && data.success);
        backdrop.innerHTML =
            '<div class="ctm-modal" role="dialog" aria-modal="true" aria-label="' + title.replace(/"/g, '&quot;') + '">' +
                '<div class="ctm-head">' +
                    '<div class="ctm-title">' + title + '</div>' +
                    '<button type="button" class="ctm-close" data-close="1">Close</button>' +
                '</div>' +
                '<div class="ctm-body">' +
                    '<span class="ctm-chip ' + (ok ? 'ok' : 'err') + '">' + (ok ? 'Success' : 'Failed') + '</span>' +
                    '<div class="ctm-label">Message</div>' +
                    '<div class="ctm-panel">' + ((data && data.message) ? String(data.message) : (ok ? 'Connection successful.' : 'Connection failed.')) + '</div>' +
                    (reason ? ('<div class="ctm-label">Why it failed</div><div class="ctm-panel">' + reason + '</div>') : '') +
                    (typeof (data && data.latency_ms) === 'number' ? ('<div class="ctm-label">Round-trip</div><div class="ctm-panel">' + data.latency_ms + ' ms</div>') : '') +
                    (detailsText ? ('<div class="ctm-label">Details</div><div class="ctm-panel">' + detailsText + '</div>') : '') +
                '</div>' +
                '<div class="ctm-actions">' +
                    '<button type="button" class="ctm-btn copy" data-copy="1">Copy Details</button>' +
                    '<button type="button" class="ctm-btn ok" data-close="1">OK</button>' +
                '</div>' +
            '</div>';
        document.body.appendChild(backdrop);

        function closeModal() {
            backdrop.remove();
            if (typeof opts.onClose === 'function') {
                try {
                    opts.onClose(data);
                } catch (e) {
                    // no-op: modal close callbacks should never break UI flow
                }
            }
        }
        backdrop.addEventListener('click', function (e) {
            if (e.target === backdrop || e.target.getAttribute('data-close') === '1') {
                closeModal();
            }
            if (e.target.getAttribute('data-copy') === '1') {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(payloadText).then(function () {
                        e.target.textContent = 'Copied';
                        setTimeout(function () { e.target.textContent = 'Copy Details'; }, 1500);
                    }).catch(function () {
                        e.target.textContent = 'Copy failed';
                        setTimeout(function () { e.target.textContent = 'Copy Details'; }, 1500);
                    });
                }
            }
        });
    }

    global.formatConnectionTestAlertPayload = formatConnectionTestAlertPayload;
    global.formatConnectionTestMessageHtml = formatConnectionTestMessageHtml;
    global.parseConnectionTestResponse = parseConnectionTestResponse;
    global.showConnectionTestModal = showConnectionTestModal;
    global.inferConnectionFailureReason = inferFailureReason;
})(typeof window !== 'undefined' ? window : this);
