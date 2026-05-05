/**
 * Lightweight realtime updates for sync job list/detail pages.
 * UI-only enhancement: no sync logic changes.
 */
(function () {
    function fmtDate(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return "";
        const mon = d.toLocaleString(undefined, { month: "short" });
        const day = String(d.getDate()).padStart(2, "0");
        const hh = String(d.getHours()).padStart(2, "0");
        const mm = String(d.getMinutes()).padStart(2, "0");
        return `${mon} ${day}, ${hh}:${mm}`;
    }

    function statusStyle(status) {
        const s = (status || "").toLowerCase();
        if (s === "running") return { chip: "bg-blue-50 text-primary border-blue-200", dot: "bg-primary animate-pulse" };
        if (s === "completed") return { chip: "bg-emerald-50 text-emerald-600 border-emerald-200", dot: "bg-emerald-500" };
        if (s === "failed") return { chip: "bg-red-50 text-red-600 border-red-200", dot: "bg-red-500" };
        if (s === "paused") return { chip: "bg-amber-50 text-amber-600 border-amber-200", dot: "bg-amber-400" };
        return { chip: "bg-slate-50 text-slate-500 border-slate-200", dot: "bg-slate-400" };
    }

    function statusBadgeClass(status) {
        const s = (status || "").toLowerCase();
        if (s === "running") return "primary";
        if (s === "completed") return "success";
        if (s === "failed") return "danger";
        if (s === "paused") return "warning";
        return "secondary";
    }

    function formatNumber(n) {
        if (n === null || n === undefined) return "0";
        return Number(n).toLocaleString();
    }

    function pollJobsList() {
        const rows = Array.from(document.querySelectorAll("[data-job-row-id]"));
        if (!rows.length) return;
        const ids = rows.map((r) => r.getAttribute("data-job-row-id")).filter(Boolean);
        if (!ids.length) return;
        let inFlight = false;
        setInterval(function () {
            if (document.hidden || inFlight) return;
            inFlight = true;
            fetch(`/sync-jobs/status/snapshot/?ids=${encodeURIComponent(ids.join(","))}`, {
                method: "GET",
                headers: { "X-Requested-With": "XMLHttpRequest" },
                credentials: "same-origin",
            })
                .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
                .then((data) => {
                    const byId = new Map((data.jobs || []).map((j) => [j.id, j]));
                    rows.forEach((row) => {
                        const id = row.getAttribute("data-job-row-id");
                        const j = byId.get(id);
                        if (!j) return;
                        const st = statusStyle(j.status);
                        const chip = row.querySelector("[data-job-status-chip]");
                        if (chip) {
                            chip.className = `inline-flex items-center gap-2 px-4 py-1.5 rounded-full border ${st.chip}`;
                        }
                        const dot = row.querySelector("[data-job-status-dot]");
                        if (dot) dot.className = `w-2.5 h-2.5 rounded-full ${st.dot}`;
                        const txt = row.querySelector("[data-job-status-text]");
                        if (txt) txt.textContent = (j.status_display || j.status || "").toUpperCase();
                        const last = row.querySelector("[data-job-last-run]");
                        if (last) last.textContent = j.last_run_at ? fmtDate(j.last_run_at) : "Never Synced";
                        const next = row.querySelector("[data-job-next-run]");
                        if (next) next.textContent = j.next_run_at ? fmtDate(j.next_run_at) : "Manual Refresh Only";
                    });
                })
                .catch(() => {})
                .finally(() => {
                    inFlight = false;
                });
        }, 3000);
    }

    function pollJobDetail() {
        const root = document.querySelector("[data-job-detail-root]");
        if (!root) return;
        const jobId = root.getAttribute("data-job-id");
        if (!jobId) return;
        let inFlight = false;
        let lastStatus = "";
        let lastExecutionId = "";
        setInterval(function () {
            if (document.hidden || inFlight) return;
            inFlight = true;
            fetch(`/sync-jobs/${jobId}/status/snapshot/`, {
                method: "GET",
                headers: { "X-Requested-With": "XMLHttpRequest" },
                credentials: "same-origin",
            })
                .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
                .then((data) => {
                    const job = data.job || {};
                    const latest = data.latest_execution || {};
                    const st = statusStyle(job.status);
                    const chip = root.querySelector("[data-job-status-chip]");
                    if (chip) chip.className = `flex items-center gap-3 px-5 py-2.5 rounded-2xl border ${st.chip} shadow-sm`;
                    const dot = root.querySelector("[data-job-status-dot]");
                    if (dot) dot.className = `w-3 h-3 rounded-full ${st.dot}`;
                    const txt = root.querySelector("[data-job-status-text]");
                    if (txt) txt.textContent = (job.status_display || job.status || "").toUpperCase();
                    const last = root.querySelector("[data-job-last-success]");
                    if (last) last.textContent = job.last_run_at ? fmtDate(job.last_run_at) : "Never";

                    const latestCardStatus = root.querySelector("[data-latest-execution-status-chip]");
                    if (latestCardStatus) {
                        latestCardStatus.className = `px-3 py-0.5 bg-${statusBadgeClass(latest.status)} text-white text-[10px] font-black uppercase tracking-widest rounded-lg`;
                        latestCardStatus.textContent = latest.status_display || latest.status || "";
                    }
                    const latestCardDate = root.querySelector("[data-latest-execution-date]");
                    if (latestCardDate && latest.started_at) {
                        const d = new Date(latest.started_at);
                        latestCardDate.textContent = d.toLocaleDateString(undefined, { month: "short", day: "2-digit", year: "numeric" });
                    }
                    const latestLink = root.querySelector("[data-latest-execution-link]");
                    if (latestLink && latest.id) {
                        const current = latestLink.getAttribute("href") || "";
                        latestLink.setAttribute("href", current.replace(/\/executions\/[^/]+\//, `/executions/${latest.id}/`));
                    }

                    const rowDot = root.querySelector("[data-latest-row-status-dot]");
                    const rowTxt = root.querySelector("[data-latest-row-status-text]");
                    const rowWrap = root.querySelector("[data-latest-row-status-wrap]");
                    if (rowDot) rowDot.className = `w-2 h-2 rounded-full bg-${statusBadgeClass(latest.status)}`;
                    if (rowTxt) {
                        rowTxt.className = `text-xs font-black text-${statusBadgeClass(latest.status)} uppercase tracking-wider`;
                        rowTxt.textContent = latest.status_display || latest.status || "";
                    }
                    if (rowWrap && latest.status === "running") {
                        // keep subtle spinning indicator behavior in latest row
                        if (!rowWrap.querySelector(".material-symbols-outlined")) {
                            const spin = document.createElement("span");
                            spin.className = "material-symbols-outlined text-xs animate-spin-slow text-primary";
                            spin.textContent = "autorenew";
                            rowWrap.appendChild(spin);
                        }
                    }
                    const rowTables = root.querySelector("[data-latest-row-tables]");
                    if (rowTables) rowTables.textContent = `${latest.completed_tables || 0}/${latest.total_tables || 0}`;
                    const rowRows = root.querySelector("[data-latest-row-rows]");
                    if (rowRows) rowRows.textContent = formatNumber(latest.total_rows_synced || 0);

                    if (latest.id && lastExecutionId && latest.id !== lastExecutionId) {
                        // New execution started/appeared; render whole archive accurately.
                        window.location.reload();
                    }
                    lastExecutionId = latest.id || lastExecutionId;
                    lastStatus = job.status || lastStatus;
                })
                .catch(() => {})
                .finally(() => {
                    inFlight = false;
                });
        }, 3000);
    }

    document.addEventListener("DOMContentLoaded", function () {
        pollJobsList();
        pollJobDetail();
    });
})();

