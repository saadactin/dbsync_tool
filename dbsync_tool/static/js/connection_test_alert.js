/**
 * Format connection test API JSON for alert() or inline status messages.
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
        if (data && typeof data.latency_ms === 'number') {
            parts.push('Round-trip: ' + data.latency_ms + ' ms');
        }
        var detailLines = formatDetailsLines(data && data.details);
        if (detailLines.length) {
            parts.push(detailLines.join('\n'));
        }
        return parts.join('\n\n');
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

    global.formatConnectionTestAlertPayload = formatConnectionTestAlertPayload;
    global.formatConnectionTestMessageHtml = formatConnectionTestMessageHtml;
    global.parseConnectionTestResponse = parseConnectionTestResponse;
})(typeof window !== 'undefined' ? window : this);
