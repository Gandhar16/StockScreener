document.addEventListener("DOMContentLoaded", () => {
    // 1. Fetch simulation results from data.json
    fetch("data.json")
        .then(response => {
            if (!response.ok) {
                throw new Error("Failed to load backtest data.json");
            }
            return response.json();
        })
        .then(data => {
            populateDashboard(data);
        })
        .catch(error => {
            console.error("Error initializing dashboard data:", error);
            alert("Could not load simulation data. Make sure 'data.json' exists in the dashboard directory.");
        });
});

let globalTradeLogs = [];

function populateDashboard(data) {
    // Save trade logs globally for filtering/search
    globalTradeLogs = data.trade_logs || [];

    // --- 1. Populate Metric Cards ---
    document.getElementById("val-start").innerText = formatCurrency(data.initial_capital);
    document.getElementById("val-end").innerText = formatCurrency(data.final_capital);
    
    // Net profit
    const netProfit = data.final_capital - data.initial_capital;
    document.getElementById("val-absolute-return").innerText = `${netProfit >= 0 ? '+' : ''}${formatCurrency(netProfit)} Net Profit`;

    // Portfolio Return
    const returnVal = document.getElementById("val-return");
    returnVal.innerText = formatPercent(data.total_return);
    returnVal.className = data.total_return >= 0 ? "metric-value text-green" : "metric-value text-red";
    document.getElementById("val-bench-comp").innerText = `vs ${formatPercent(data.benchmark_return)} S&P 500`;

    // Max Drawdown
    const ddVal = document.getElementById("val-drawdown");
    ddVal.innerText = formatPercent(data.max_drawdown);
    ddVal.className = data.max_drawdown >= -0.15 ? "metric-value text-green" : (data.max_drawdown >= -0.25 ? "metric-value text-gold" : "metric-value text-red");
    document.getElementById("val-bench-drawdown").innerText = `vs ${formatPercent(data.benchmark_max_drawdown)} S&P 500`;

    // Win Rate calculation
    const totalTrades = globalTradeLogs.length;
    const winningTrades = globalTradeLogs.filter(t => t.profit_loss > 0).length;
    const winRate = totalTrades > 0 ? winningTrades / totalTrades : 0.0;
    
    const wrVal = document.getElementById("val-winrate");
    wrVal.innerText = formatPercent(winRate);
    wrVal.className = winRate >= 0.60 ? "metric-value text-green" : (winRate >= 0.40 ? "metric-value text-gold" : "metric-value text-red");
    document.getElementById("val-win-ratio").innerText = `${winningTrades} of ${totalTrades} Trades Winning`;

    // --- 2. Populate Trade Logs Table ---
    renderTradeLogs(globalTradeLogs);

    // Setup Filter/Search event listeners
    const searchInput = document.getElementById("log-search");
    const filterSelect = document.getElementById("log-filter");
    
    const handleFilterChange = () => {
        const query = searchInput.value.trim().toUpperCase();
        const outcomeFilter = filterSelect.value; // ALL, WIN, LOSS

        let filtered = globalTradeLogs;
        
        if (query) {
            filtered = filtered.filter(t => t.ticker.includes(query));
        }

        if (outcomeFilter !== "ALL") {
            filtered = filtered.filter(t => t.status === outcomeFilter);
        }

        renderTradeLogs(filtered);
    };

    searchInput.addEventListener("input", handleFilterChange);
    filterSelect.addEventListener("change", handleFilterChange);

    // --- 3. Render Chart.js Curves ---
    renderCharts(data.equity_curve);
}

function renderTradeLogs(logs) {
    const tableBody = document.getElementById("trade-log-body");
    tableBody.innerHTML = "";

    if (logs.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-muted);">No matching trades found.</td></tr>`;
        return;
    }

    logs.forEach(log => {
        const row = document.createElement("tr");

        const plClass = log.profit_loss >= 0 ? "text-green" : "text-red";
        const plSign = log.profit_loss >= 0 ? "+" : "";

        row.innerHTML = `
            <td><strong>${log.ticker}</strong></td>
            <td><span class="action-buy">BUY</span></td>
            <td>${log.entry_date}</td>
            <td>${log.exit_date}</td>
            <td>${formatCurrency(log.entry_price)}</td>
            <td>${formatCurrency(log.exit_price)}</td>
            <td>${log.shares.toFixed(2)}</td>
            <td class="${plClass}"><strong>${plSign}${formatCurrency(log.profit_loss)}</strong></td>
            <td class="${plClass}"><strong>${plSign}${formatPercent(log.profit_loss_pct)}</strong></td>
            <td><span class="badge ${log.status.toLowerCase()}">${log.status}</span></td>
        `;

        tableBody.appendChild(row);
    });
}

function renderCharts(equityCurve) {
    const dates = equityCurve.map(r => r.date);
    const portValues = equityCurve.map(r => r.portfolio_value);
    const benchValues = equityCurve.map(r => r.benchmark_value);

    const portDrawdowns = equityCurve.map(r => r.portfolio_drawdown * 100);
    const benchDrawdowns = equityCurve.map(r => r.benchmark_drawdown * 100);

    // --- Equity Chart ---
    const ctxEquity = document.getElementById("equityChart").getContext("2d");
    
    // Gradient for portfolio line
    const gradPortfolio = ctxEquity.createLinearGradient(0, 0, 0, 300);
    gradPortfolio.addColorStop(0, "rgba(139, 92, 246, 0.4)");
    gradPortfolio.addColorStop(1, "rgba(139, 92, 246, 0.0)");

    new Chart(ctxEquity, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [
                {
                    label: 'Portfolio (StockCalls)',
                    data: portValues,
                    borderColor: '#8b5cf6',
                    borderWidth: 2.5,
                    backgroundColor: gradPortfolio,
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0,
                    pointHoverRadius: 6
                },
                {
                    label: 'Benchmark (S&P 500)',
                    data: benchValues,
                    borderColor: 'rgba(156, 163, 175, 0.5)',
                    borderWidth: 1.5,
                    borderDash: [5, 5],
                    fill: false,
                    tension: 0.2,
                    pointRadius: 0,
                    pointHoverRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: '#f3f4f6', font: { family: 'Inter', weight: '500' } }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            return ` ${context.dataset.label}: ${formatCurrency(context.raw)}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: '#9ca3af', font: { family: 'Inter', size: 10 } }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: {
                        color: '#9ca3af',
                        font: { family: 'Inter', size: 10 },
                        callback: function(value) { return '$' + value.toLocaleString(); }
                    }
                }
            }
        }
    });

    // --- Drawdown Chart ---
    const ctxDrawdown = document.getElementById("drawdownChart").getContext("2d");
    
    new Chart(ctxDrawdown, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [
                {
                    label: 'Portfolio Drawdown',
                    data: portDrawdowns,
                    borderColor: '#ef4444',
                    borderWidth: 1.5,
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0
                },
                {
                    label: 'Benchmark Drawdown',
                    data: benchDrawdowns,
                    borderColor: 'rgba(156, 163, 175, 0.3)',
                    borderWidth: 1,
                    backgroundColor: 'rgba(156, 163, 175, 0.03)',
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: '#f3f4f6', font: { family: 'Inter', weight: '500' } }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            return ` ${context.dataset.label}: ${context.raw.toFixed(2)}%`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: '#9ca3af', font: { family: 'Inter', size: 10 } }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: {
                        color: '#9ca3af',
                        font: { family: 'Inter', size: 10 },
                        callback: function(value) { return value + '%'; }
                    }
                }
            }
        }
    });
}

// --- Helper Formatting Functions ---
function formatCurrency(val) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2
    }).format(val);
}

function formatPercent(val) {
    // Handles decimal percent e.g. 0.1096 -> 10.96%
    return `${(val * 100).toFixed(2)}%`;
}
