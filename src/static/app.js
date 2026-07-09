const API_BASE = ""; // Relative to server root

// App State
let incidents = [];
let memories = [];
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
            fetchKPI()
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
        submitBtn.innerText = "Dispatch Alert to Qwen OS";
    }
}

// Active event streams map
let activeStreams = {};

function startSseStream(incidentId) {
    if (activeStreams[incidentId]) return;
    
    console.log(`Starting SSE Stream for incident ${incidentId}`);
    const source = new EventSource(`${API_BASE}/api/incidents/${incidentId}/stream`);
    activeStreams[incidentId] = source;
    
    source.addEventListener("agent", (event) => {
        try {
            const data = JSON.parse(event.data);
            console.log("SSE Event Received:", data);
            
            if (data.event === "stream_end") {
                console.log(`SSE Stream ended for ${incidentId}`);
                source.close();
                delete activeStreams[incidentId];
            }
            
            // Re-fetch all data to update the UI cards instantly!
            fetchData();
            
        } catch (e) {
            console.error("Failed to parse SSE event data:", e);
        }
    });
    
    source.onerror = () => {
        source.close();
        delete activeStreams[incidentId];
    };
}

// Fetch Incidents
async function fetchIncidents() {
    const res = await fetch(`${API_BASE}/api/incidents`);
    incidents = await res.json();
    
    // Find the latest active incident (first one in descending order)
    const latestActive = incidents.find(i => !["resolved", "failed"].includes(i.status));
    
    // Close other streams that are no longer the latest active incident
    Object.keys(activeStreams).forEach(id => {
        if (!latestActive || latestActive.id !== id) {
            console.log(`Closing stream for incident ${id}`);
            activeStreams[id].close();
            delete activeStreams[id];
        }
    });
    
    // Start streaming ONLY for the latest active incident
    if (latestActive) {
        startSseStream(latestActive.id);
    }
    
    renderFlowchartAndLogs();
}

// Fetch Memories
async function fetchMemories() {
    const res = await fetch(`${API_BASE}/api/memories`);
    memories = await res.json();
    renderMemories();
}

// Fetch KPI Metrics
async function fetchKPI() {
    try {
        const res = await fetch(`${API_BASE}/api/kpi`);
        if (!res.ok) return;
        const data = await res.json();
        
        // Update all KPI tags
        const elements = ["kpi-total", "kpi-success", "kpi-auto", "kpi-time"];
        elements.forEach(id => {
            const el = document.getElementById(id);
            if (!el) return;
            if (id === "kpi-total") el.innerText = data.total_alerts;
            else if (id === "kpi-success") el.innerText = data.success_rate + "%";
            else if (id === "kpi-auto") el.innerText = data.auto_remediation_rate + "%";
            else if (id === "kpi-time") el.innerText = data.avg_resolution_time.toFixed(1) + "s";
        });
    } catch (e) {
        console.error("Failed to fetch KPIs:", e);
    }
}

// Renders flowchart node states and console logs
function renderFlowchartAndLogs() {
    // 1. Reset all nodes & connectors
    const nodes = ["triage", "diagnose", "plan", "execute", "verify"];
    const conns = ["conn-1", "conn-2", "conn-3", "conn-4"];
    
    nodes.forEach(id => {
        const el = document.getElementById(`node-${id}`);
        if (el) el.className = `flow-node node-${id}`;
        
        const detail = document.getElementById(`detail-${id}`);
        if (detail) detail.innerText = "Idle";
    });
    
    conns.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.className = "flow-connector";
    });
    
    const logsContainer = document.getElementById("terminal-body");
    logsContainer.innerHTML = '<span class="terminal-placeholder">System waiting for incoming SLS webhook alert signals...</span>';

    // 2. Map active incident to flowchart nodes
    const activeIncident = incidents.find(i => !["resolved", "failed"].includes(i.status)) || incidents[0];
    if (!activeIncident) return;
    
    const status = activeIncident.status;
    
    // Update Node details
    const dt = document.getElementById("detail-triage");
    if (dt) dt.innerText = activeIncident.severity ? `Host: ${activeIncident.host}` : "Pending Ingestion";
    
    const dd = document.getElementById("detail-diagnose");
    if (dd) dd.innerText = activeIncident.root_cause ? `RCA: ${activeIncident.root_cause}` : "Idle";
    
    const dp = document.getElementById("detail-plan");
    if (dp) dp.innerText = activeIncident.remediation_plan ? `Plan: ${activeIncident.remediation_plan}` : "Idle";
    
    const de = document.getElementById("detail-execute");
    if (de) de.innerText = activeIncident.status === "executing" ? "Running tool..." : activeIncident.approved_by ? `Approved by ${activeIncident.approved_by}` : "Idle";

    const dv = document.getElementById("detail-verify");
    if (dv) dv.innerText = activeIncident.status === "verify" ? "Verifying ports..." : "Idle";

    // Set Node State Classes
    if (status === "triage") {
        setNodeState("triage", "active");
    } else if (status === "triage_completed" || status === "diagnose") {
        setNodeState("triage", "completed");
        setConnState("conn-1", "active");
        setNodeState("diagnose", "active");
    } else if (status === "plan") {
        setNodeState("triage", "completed");
        setNodeState("diagnose", "completed");
        setConnState("conn-1", "active");
        setConnState("conn-2", "active");
        setNodeState("plan", "active");
    } else if (status === "pending_approval" || status === "executing") {
        setNodeState("triage", "completed");
        setNodeState("diagnose", "completed");
        setNodeState("plan", "completed");
        setConnState("conn-1", "active");
        setConnState("conn-2", "active");
        setConnState("conn-3", "active");
        setNodeState("execute", "active");
    } else if (status === "verify") {
        setNodeState("triage", "completed");
        setNodeState("diagnose", "completed");
        setNodeState("plan", "completed");
        setNodeState("execute", "completed");
        setConnState("conn-1", "active");
        setConnState("conn-2", "active");
        setConnState("conn-3", "active");
        setConnState("conn-4", "active");
        setNodeState("verify", "active");
    } else if (status === "resolved") {
        setNodeState("triage", "completed");
        setNodeState("diagnose", "completed");
        setNodeState("plan", "completed");
        setNodeState("execute", "completed");
        setNodeState("verify", "completed");
        setConnState("conn-1", "active");
        setConnState("conn-2", "active");
        setConnState("conn-3", "active");
        setConnState("conn-4", "active");
        
        const dv_resolved = document.getElementById("detail-verify");
        if (dv_resolved) dv_resolved.innerText = "Nominal Health Check";
    } else if (status === "failed") {
        setNodeState("triage", "completed");
        setNodeState("diagnose", "completed");
        setNodeState("plan", "completed");
        setNodeState("execute", "failed");
        setNodeState("verify", "failed");
    }

    // 3. Render console output logs
    if (activeIncident.execution_logs) {
        try {
            const logs = JSON.parse(activeIncident.execution_logs);
            logsContainer.innerHTML = "";
            logs.forEach(log => {
                const div = document.createElement("div");
                div.className = "log-entry";
                if (log.includes("transition")) div.className = "log-entry state";
                else if (log.includes("tool") || log.includes("remediation") || log.includes("executor")) div.className = "log-entry tool";
                else if (log.includes("safety") || log.includes("Risk")) div.className = "log-entry safety";
                
                div.innerText = log;
                logsContainer.appendChild(div);
            });
            // Auto scroll console to bottom
            logsContainer.scrollTop = logsContainer.scrollHeight;
        } catch (e) {
            console.error("Failed to parse logs:", e);
        }
    }
}

function setNodeState(nodeId, state) {
    const el = document.getElementById(`node-${nodeId}`);
    if (el) el.className = `flow-node node-${nodeId} ${state}`;
}

function setConnState(connId, state) {
    const el = document.getElementById(connId);
    if (el) el.className = `flow-connector ${state}`;
}

// Render memories to Left Sidebar panel
function renderMemories() {
    const container = document.getElementById("memory-list");
    if (!container) return;
    
    if (memories.length === 0) {
        container.innerHTML = '<div class="empty-state">No historical fixes loaded.</div>';
        return;
    }
    
    container.innerHTML = "";
    memories.forEach(m => {
        const div = document.createElement("div");
        div.className = "memory-item";
        div.innerHTML = `
            <span class="memory-title">Anomaly Log: ${m.alert_type}</span>
            <span class="memory-desc">Action: ${m.action_taken} (${m.run_count} runs)</span>
            <span class="memory-meta">Executed: ${m.last_executed}</span>
        `;
        container.appendChild(div);
    });
}

// Update the Human-in-the-Loop approval console
function updateHITLPanel() {
    const hitlCard = document.getElementById("hitl-card");
    const pendingIncident = incidents.find(i => i.status === "pending_approval");
    
    if (pendingIncident) {
        document.getElementById("hitl-host").innerText = pendingIncident.host || "Unknown";
        document.getElementById("hitl-tool").innerText = pendingIncident.remediation_plan || "None";
        document.getElementById("hitl-plan").innerText = `Proposed remediation command requires authorized approval. Risk level: ${pendingIncident.risk_level || "0.7"}`;
        
        hitlCard.style.display = "block";
    } else {
        hitlCard.style.display = "none";
    }
}

// Approve Action
async function approveRemediation() {
    const pendingIncident = incidents.find(i => i.status === "pending_approval");
    if (!pendingIncident) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/incidents/${pendingIncident.id}/approve`, {
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

// Reject Action
async function rejectRemediation() {
    const pendingIncident = incidents.find(i => i.status === "pending_approval");
    if (!pendingIncident) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/incidents/${pendingIncident.id}/reject`, {
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
