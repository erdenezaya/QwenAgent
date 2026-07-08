const API_BASE = ""; // Relative to server root

// App State
let incidents = [];
let memories = [];
let ossLogs = [];
let pollingInterval = null;

// On Load
document.addEventListener("DOMContentLoaded", () => {
    // Initial fetch
    fetchData();
    // Start active polling for incident updates every 2 seconds
    pollingInterval = setInterval(fetchData, 2000);
});

async function fetchData() {
    try {
        await Promise.all([
            fetchIncidents(),
            fetchMemories(),
            fetchOSSLogs()
        ]);
        updateHITLPanel();
    } catch (err) {
        console.error("Error polling backend API:", err);
    }
}

// Set alert templates
function setTemplate(type) {
    const textarea = document.getElementById("alert-input");
    if (type === "tomcat") {
        textarea.value = "CRITICAL: High CPU load (97%) detected on web-prod-01. Service Tomcat (tomcat-web) is reporting threadpool execution limits and is completely unresponsive to health check calls.";
    } else if (type === "mysql") {
        textarea.value = "DB_ALERT: Connection failure on host db-prod-02. mysql-service daemon unresponsive on port 3306. Java applications throwing JDBCConnectionTimeoutException: connection count exceeded.";
    } else if (type === "disk") {
        textarea.value = "DISK_ALERT: Root partition full on srv-app-09. Storage volume reporting 99.2% disk usage. Log directory `/var/log` is filled with old debug system log archives.";
    }
}

// Trigger Alert
async function triggerAlert() {
    const alertText = document.getElementById("alert-input").value.trim();
    if (!alertText) {
        alert("Please enter alert details or choose a template first.");
        return;
    }
    
    const submitBtn = document.getElementById("submit-alert-btn");
    submitBtn.disabled = true;
    submitBtn.style.opacity = 0.7;
    submitBtn.innerText = "Dispatching to Qwen...";

    try {
        const response = await fetch(`${API_BASE}/api/alerts`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ alert_text: alertText })
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Failed to trigger alert");
        }
        
        document.getElementById("alert-input").value = "";
        fetchData();
    } catch (err) {
        alert(`Error triggering alert: ${err.message}`);
    } finally {
        submitBtn.disabled = false;
        submitBtn.style.opacity = 1;
        submitBtn.innerHTML = `
            <span>Dispatch Alert to Qwen OS</span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="btn-icon">
                <line x1="22" y1="2" x2="11" y2="13"/>
                <polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
        `;
    }
}

// Fetch Incidents
async function fetchIncidents() {
    const res = await fetch(`${API_BASE}/api/incidents`);
    incidents = await res.json();
    
    // Update active incident counts
    const activeCount = incidents.filter(i => !["resolved", "failed"].includes(i.status)).length;
    document.getElementById("active-count").innerText = activeCount;
    
    renderIncidents();
}

// Fetch Memories
async function fetchMemories() {
    const res = await fetch(`${API_BASE}/api/memories`);
    memories = await res.json();
    renderMemories();
}

// Fetch OSS Logs
async function fetchOSSLogs() {
    const res = await fetch(`${API_BASE}/api/oss/logs`);
    ossLogs = await res.json();
    renderOSSLogs();
}

// Update the Human-in-the-Loop approval console
function updateHITLPanel() {
    const hitlCard = document.getElementById("hitl-card");
    // Find the first incident that is pending approval
    const pendingIncident = incidents.find(i => i.status === "pending_approval");
    
    if (pendingIncident) {
        document.getElementById("hitl-id").innerText = pendingIncident.id;
        document.getElementById("hitl-host").innerText = pendingIncident.host || "Unknown";
        
        let toolName = "None";
        try {
            const logsData = JSON.parse(pendingIncident.execution_logs);
            toolName = logsData.planned_tool.name;
            // Add arguments to visualization
            toolName += `(${JSON.stringify(logsData.planned_tool.args)})`;
        } catch (e) {}
        
        document.getElementById("hitl-tool").innerText = toolName;
        document.getElementById("hitl-plan").innerText = pendingIncident.remediation_plan || "No plan described.";
        
        hitlCard.style.display = "block";
    } else {
        hitlCard.style.display = "none";
    }
}

// Approve Remediation Action
async function approveRemediation() {
    const id = document.getElementById("hitl-id").innerText;
    try {
        const response = await fetch(`${API_BASE}/api/incidents/${id}/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approver: "Operator-HQ" })
        });
        if (response.ok) {
            fetchData();
        } else {
            alert("Failed to submit approval.");
        }
    } catch (e) {
        console.error(e);
    }
}

// Reject Remediation Action
async function rejectRemediation() {
    const id = document.getElementById("hitl-id").innerText;
    try {
        const response = await fetch(`${API_BASE}/api/incidents/${id}/reject`, {
            method: "POST"
        });
        if (response.ok) {
            fetchData();
        } else {
            alert("Failed to submit rejection.");
        }
    } catch (e) {
        console.error(e);
    }
}

// Render incident stream
function renderIncidents() {
    const container = document.getElementById("incident-container");
    
    if (incidents.length === 0) {
        container.innerHTML = `
            <div class="empty-state-large">
                <svg class="empty-illustration" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <rect x="2" y="2" width="20" height="20" rx="2" ry="2"/>
                    <path d="M12 18h.01"/>
                    <path d="M8 8h8"/>
                    <path d="M8 12h8"/>
                </svg>
                <h3>No Incidents Triggered</h3>
                <p>System is nominal. Use the left panel to inject a system alert and watch Qwen coordinate remediation.</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = incidents.map(inc => {
        // Build agent step logs dynamically
        let stepsHtml = "";
        
        // 1. Triage step
        if (inc.status !== "received") {
            stepsHtml += `
                <div class="agent-step">
                    <div class="step-label label-triage">
                        <span>Agent 1</span> Qwen-Plus : Alert Triage & Entity Extraction
                    </div>
                    <div class="step-content">
                        <p>${inc.triage_reasoning || "Triage reasoning pending..."}</p>
                        ${inc.host ? `
                            <div class="meta-pills" style="margin-top: 0.4rem;">
                                <span class="pill"><strong>Service:</strong> ${inc.service}</span>
                                <span class="pill"><strong>Host:</strong> ${inc.host}</span>
                                <span class="pill"><strong>Severity:</strong> <span style="color: ${getSeverityColor(inc.severity)}">${inc.severity.toUpperCase()}</span></span>
                            </div>
                        ` : ""}
                    </div>
                </div>
            `;
        }
        
        // 2. Remediation Planning
        if (!["received", "triage_completed"].includes(inc.status)) {
            let toolCallInfo = "";
            try {
                const logsData = JSON.parse(inc.execution_logs);
                toolCallInfo = `
                    <div class="meta-pills" style="margin-top: 0.4rem;">
                        <span class="pill"><strong>Suggested Action:</strong> ${logsData.planned_tool.name}</span>
                        <span class="pill"><strong>Requires Approval:</strong> ${inc.requires_approval ? "YES" : "NO"}</span>
                    </div>
                `;
            } catch (e) {}
            
            stepsHtml += `
                <div class="agent-step">
                    <div class="step-label label-remediation">
                        <span>Agent 2</span> Qwen-Max : Remediation Planner & Memory Recall
                    </div>
                    <div class="step-content">
                        <p>${inc.remediation_plan || "Remediation plan formulation pending..."}</p>
                        ${toolCallInfo}
                    </div>
                </div>
            `;
        }
        
        // 3. Execution Log
        if (["executing", "executing_completed", "resolved", "failed"].includes(inc.status)) {
            let logDetails = "Loading terminal output...";
            try {
                const logsData = JSON.parse(inc.execution_logs);
                if (logsData.runs && logsData.runs.length > 0) {
                    const run = logsData.runs[0];
                    logDetails = `Executed: ${run.tool} (${JSON.stringify(run.args)})\n` +
                                 `Status: ${run.success ? "SUCCESS" : "FAILED"}\n\n` +
                                 `Terminal Console logs:\n${run.details}`;
                }
            } catch (e) {
                logDetails = `Error reading execution log: ${e.message}`;
            }
            
            stepsHtml += `
                <div class="agent-step">
                    <div class="step-label label-execution">
                        <span>Tool</span> Local Environment System Shell Executor
                    </div>
                    <div class="step-content">
                        <p>Executing recommended tool chain on remote server...</p>
                        <div class="step-details-console">${logDetails}</div>
                    </div>
                </div>
            `;
        }
        
        // 4. Verification Check
        if (["resolved", "failed"].includes(inc.status)) {
            stepsHtml += `
                <div class="agent-step">
                    <div class="step-label label-verify">
                        <span>Agent 3</span> Qwen-Plus : Health Verification & Diagnostics
                    </div>
                    <div class="step-content">
                        <p>${inc.verification_results || "Verifying service status..."}</p>
                    </div>
                </div>
            `;
        }
        
        return `
            <div class="incident-ticket">
                <div class="ticket-header">
                    <span class="ticket-title">Ticket ID: <span class="monospace font-bold">#${inc.id}</span></span>
                    <span class="ticket-status ${getStatusClass(inc.status)}">${inc.status.replace("_", " ")}</span>
                </div>
                <div class="ticket-body">
                    <div class="alert-raw-box monospace">${inc.raw_alert}</div>
                    ${stepsHtml}
                </div>
            </div>
        `;
    }).join("");
}

function getStatusClass(status) {
    if (status === "received") return "status-received";
    if (status === "triage_completed" || status === "triage") return "status-triage";
    if (status === "pending_approval") return "status-pending";
    if (status === "executing") return "status-executing";
    if (status === "resolved") return "status-resolved";
    return "status-failed";
}

function getSeverityColor(sev) {
    if (!sev) return "var(--text-secondary)";
    sev = sev.toLowerCase();
    if (sev === "low") return "var(--color-green)";
    if (sev === "medium") return "#eab308";
    if (sev === "high") return "var(--color-orange)";
    return "var(--color-red)";
}

// Render memory list
function renderMemories() {
    const container = document.getElementById("memory-list");
    if (memories.length === 0) {
        container.innerHTML = `<div class="empty-state">No historical memory entries.</div>`;
        return;
    }
    
    container.innerHTML = memories.map(mem => `
        <div class="memory-item">
            <div class="memory-meta">
                <span class="memory-tag">svc:${mem.service}</span>
                <span class="memory-stat">${mem.run_count} runs • ${mem.last_executed.split(" ")[0]}</span>
            </div>
            <div class="section-desc" style="margin-bottom: 0.25rem;">
                Alert Trigger: "<em>${mem.alert_type}</em>"
            </div>
            <div class="memory-action">
                ${mem.action_taken}
            </div>
            <div style="margin-top: 0.25rem; display: flex; justify-content: flex-end;">
                ${mem.success === 1 ? `<span class="success-badge">SUCCESS VERIFIED</span>` : `<span class="fail-badge">FAILED RECORD</span>`}
            </div>
        </div>
    `).join("");
}

// Render OSS archives list
function renderOSSLogs() {
    const container = document.getElementById("oss-log-list");
    if (ossLogs.length === 0) {
        container.innerHTML = `<div class="empty-state">No files uploaded. Archive logs to OSS.</div>`;
        return;
    }
    
    container.innerHTML = ossLogs.map(log => {
        let key = "";
        let sizeText = "";
        let dateText = "";
        
        if (typeof log === "string") {
            key = log;
            sizeText = "JSON Log File";
            dateText = "local_oss_archive";
        } else {
            key = log.key;
            sizeText = `${(log.size / 1024).toFixed(2)} KB`;
            dateText = log.last_modified;
        }
        
        return `
            <div class="oss-item">
                <svg class="oss-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="17 8 12 3 7 8"/>
                    <line x1="12" y1="3" x2="12" y2="15"/>
                </svg>
                <div class="oss-info">
                    <span class="oss-key" title="${key}">${key}</span>
                    <div class="oss-meta">
                        <span>${sizeText}</span>
                        <span>${dateText}</span>
                    </div>
                </div>
            </div>
        `;
    }).join("");
}
