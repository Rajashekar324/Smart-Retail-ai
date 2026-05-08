const PIPELINE_API_BASE = '/pipeline';
let autoRefresh = false;
let autoRefreshIntervalId = null;
let pipelineMode = localStorage.getItem('pipelineMode') || 'dynamic';

function formatNumber(value) {
    return value == null ? '0' : value.toLocaleString ? value.toLocaleString() : String(value);
}

function formatCurrency(value) {
    return value == null ? '₹0' : '₹' + formatNumber(value.toFixed ? value.toFixed(2) : value);
}

function getLayerCount(layerData) {
    if (typeof layerData === 'number') return layerData;
    if (layerData && layerData.total_records) return layerData.total_records;
    return 0;
}

function addLog(message) {
    const logs = document.getElementById('logsContent');
    if (!logs) return;

    const entry = document.createElement('div');
    entry.style.padding = '12px 14px';
    entry.style.marginBottom = '10px';
    entry.style.borderRadius = '14px';
    entry.style.background = 'rgba(255,255,255,0.9)';
    entry.style.color = '#222';
    entry.style.boxShadow = '0 2px 16px rgba(0,0,0,0.08)';
    entry.textContent = `${new Date().toLocaleTimeString()}: ${message}`;

    logs.prepend(entry);
}

function switchPipelineMode(mode) {
    if (mode !== 'dynamic' && mode !== 'static') return;
    pipelineMode = mode;
    localStorage.setItem('pipelineMode', mode);
    const btn = document.getElementById('pipelineModeBtn');
    const indicator = document.getElementById('currentModeIndicator');
    if (btn) {
        btn.innerHTML = mode === 'dynamic' ? '<i class="fas fa-exchange-alt"></i> Switch to CSV (Static)' : '<i class="fas fa-exchange-alt"></i> Switch to Live Database';
    }
    if (indicator) {
        indicator.textContent = mode === 'dynamic' ? '🔄 Live Database' : '📄 CSV File';
        indicator.style.color = mode === 'dynamic' ? '#667eea' : '#9b59b6';
    }
    addLog(`Switched to ${mode} mode.`);
    refreshData();
}

async function refreshData() {
    try {
        const response = await fetch(`${PIPELINE_API_BASE}/analytics?mode=${pipelineMode}`);
        if (!response.ok) {
            const error = await response.text();
            throw new Error(error || 'Unable to load analytics data');
        }

        const payload = await response.json();
        const summary = payload.summary || {};
        const layerCounts = payload.layer_counts || {};
        const quality = payload.quality || {};

        document.getElementById('rawCount').textContent = `${formatNumber(getLayerCount(layerCounts.raw))} records`;
        document.getElementById('stagingCount').textContent = `${formatNumber(getLayerCount(layerCounts.staging))} records`;
        document.getElementById('curatedCount').textContent = `${formatNumber(getLayerCount(layerCounts.curated))} records`;

        document.getElementById('metricRevenue').textContent = formatCurrency(summary.total_revenue || 0);
        document.getElementById('metricOrders').textContent = formatNumber(summary.total_orders || 0);
        document.getElementById('metricAOV').textContent = formatCurrency(summary.avg_order_value || 0);
        document.getElementById('metricCustomers').textContent = formatNumber(Math.max(Math.round((summary.total_orders || 0) * 0.4), 0));
        document.getElementById('metricVIP').textContent = formatNumber(Math.max(Math.round((summary.total_revenue || 0) / 10000), 0));
        document.getElementById('metricAnomalies').textContent = formatNumber((payload.anomalies || []).length);

        document.getElementById('qualityScore').textContent = `${quality.overall_score || 0}%`;
        document.getElementById('totalChecks').textContent = formatNumber(quality.total_checks || 0);
        document.getElementById('passedChecks').textContent = formatNumber(quality.passed_checks || 0);
        document.getElementById('failedChecks').textContent = formatNumber(quality.failed_checks || 0);

        if (summary.period_end) {
            document.getElementById('lastRun').textContent = `Last run: ${summary.period_end}`;
        }

        addLog('Dashboard refreshed successfully.');
    } catch (error) {
        console.error('Refresh failed:', error);
        addLog(`Refresh failed: ${error.message}`);
    }
}

function showTab(tabId, btn) {
    document.querySelectorAll('[id$="Tab"]').forEach((tab) => {
        tab.style.display = 'none';
    });

    const targetTab = document.getElementById(tabId);
    if (targetTab) {
        targetTab.style.display = 'block';
    }

    document.querySelectorAll('.tab-btn').forEach((button) => {
        button.classList.remove('active');
    });

    if (btn) {
        btn.classList.add('active');
    }
}

async function runPipeline() {
    const btn = document.getElementById('btnRun');
    const progress = document.getElementById('progressArea');
    const bar = document.getElementById('progressBar');
    const text = document.getElementById('progressText');
    const status = document.getElementById('pipelineStatus');

    if (!btn || !progress || !bar || !text || !status) {
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-sync-alt fa-spin"></i> Processing...';
    progress.style.display = 'block';
    status.textContent = 'Running';
    text.style.display = 'block';
    text.textContent = 'Extracting pipeline metrics...';

    try {
        bar.style.width = '30%';
        await new Promise((resolve) => setTimeout(resolve, 300));
        bar.style.width = '60%';
        text.textContent = 'Applying transformations...';

        const response = await fetch('/api/admin/pipeline/run', { method: 'POST' });
        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || 'Pipeline execution failed');
        }

        bar.style.width = '100%';
        text.textContent = `✅ Complete: ${formatNumber(result.records_processed || 0)} records`;
        status.textContent = 'Ready';

        addLog(`Pipeline completed: ${formatNumber(result.records_processed || 0)} records processed`);
        await refreshData();
    } catch (error) {
        bar.style.width = '100%';
        bar.style.background = '#dc3545';
        text.textContent = `❌ Failed: ${error.message}`;
        status.textContent = 'Failed';
        addLog(`Error: ${error.message}`);
    } finally {
        setTimeout(() => {
            progress.style.display = 'none';
            bar.style.width = '0%';
            bar.style.background = 'linear-gradient(90deg, #667eea, #764ba2, #f093fb, #f5576c, #4facfe)';
        }, 1800);
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-play"></i> ⚡ Run Full Pipeline';
    }
}

async function loadTable(layer, table) {
    const tableEl = document.getElementById(`${layer}Table`);
    if (!tableEl) {
        return;
    }

    const layerMap = {
        curated: 'gold',
        staging: 'silver',
        raw: 'bronze',
    };
    const apiLayer = layerMap[layer] || 'gold';
    const url = `${PIPELINE_API_BASE}/${apiLayer}?table=${encodeURIComponent(table)}&mode=${pipelineMode}`;

    tableEl.innerHTML = '<thead><tr><th>Loading data...</th></tr></thead><tbody></tbody>';

    try {
        const response = await fetch(url);
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(errorText || 'Unable to load table data');
        }

        const payload = await response.json();
        const records = payload.records || payload.table || payload.data || payload.records || [];
        renderTable(tableEl, records);
    } catch (error) {
        console.error('Table load failed:', error);
        tableEl.innerHTML = `<thead><tr><th>Error loading table</th></tr></thead><tbody><tr><td>${error.message}</td></tr></tbody>`;
    }
}

function renderTable(tableEl, rows) {
    if (!Array.isArray(rows) || rows.length === 0) {
        tableEl.innerHTML = '<thead><tr><th style="padding: 12px; background: #f5f5f5; border-bottom: 2px solid #e0e0e0; text-align: left;">No records found</th></tr></thead><tbody></tbody>';
        return;
    }

    const columns = Object.keys(rows[0]);
    const thead = '<thead><tr>' + columns.map((column) => `<th style="padding: 12px; background: #f5f5f5; border-bottom: 2px solid #e0e0e0; text-align: left; font-weight: 600; white-space: nowrap;">${column}</th>`).join('') + '</tr></thead>';

    const tbodyRows = rows.map((row) => {
        const cells = columns.map((key) => {
            const value = row[key];
            let text;
            if (value === null || value === undefined) {
                text = '';
            } else if (typeof value === 'object') {
                text = JSON.stringify(value);
            } else {
                text = String(value);
            }
            return `<td style="padding: 12px; border-bottom: 1px solid #eee;">${text}</td>`;
        });
        return `<tr>${cells.join('')}</tr>`;
    });

    tableEl.innerHTML = `${thead}<tbody>${tbodyRows.join('')}</tbody>`;
}

function downloadCsv(filename, rows) {
    if (!Array.isArray(rows) || rows.length === 0) {
        addLog('No records to export.');
        return;
    }

    const columns = Object.keys(rows[0]);
    const header = columns.join(',');
    const body = rows.map((row) => columns.map((col) => {
        const value = row[col] == null ? '' : String(row[col]).replace(/"/g, '""');
        return `"${value}"`;
    }).join(',')).join('\n');

    const csvContent = `${header}\n${body}`;
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

async function exportData() {
    try {
        const response = await fetch(`${PIPELINE_API_BASE}/bronze?table=orders`);
        if (!response.ok) {
            throw new Error('Unable to export pipeline data');
        }

        const payload = await response.json();
        const rows = payload.records || payload.table || payload.data || [];
        downloadCsv('pipeline_bronze_export.csv', rows);
        addLog('Exported pipeline bronze data to CSV.');
    } catch (error) {
        console.error('Export failed:', error);
        addLog(`Export failed: ${error.message}`);
    }
}

function toggleAuto() {
    autoRefresh = !autoRefresh;
    const status = document.getElementById('autoStatus');
    const button = document.querySelector('button[onclick="toggleAuto()"]');

    if (autoRefresh) {
        status.textContent = 'ON';
        addLog('Auto-refresh enabled.');
        autoRefreshIntervalId = window.setInterval(refreshData, 60000);
        button.style.opacity = '0.95';
    } else {
        status.textContent = 'OFF';
        addLog('Auto-refresh disabled.');
        if (autoRefreshIntervalId) {
            window.clearInterval(autoRefreshIntervalId);
            autoRefreshIntervalId = null;
        }
        button.style.opacity = '1';
    }
}

window.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('pipelineModeBtn');
    const indicator = document.getElementById('currentModeIndicator');
    if (btn) {
        btn.innerHTML = pipelineMode === 'dynamic' ? '<i class="fas fa-exchange-alt"></i> Switch to CSV (Static)' : '<i class="fas fa-exchange-alt"></i> Switch to Live Database';
    }
    if (indicator) {
        indicator.textContent = pipelineMode === 'dynamic' ? '🔄 Live Database' : '📄 CSV File';
        indicator.style.color = pipelineMode === 'dynamic' ? '#667eea' : '#9b59b6';
    }
    refreshData();
    showTab('curatedTab', document.getElementById('btnGold'));
    loadTable('curated', 'sales_daily');
});
