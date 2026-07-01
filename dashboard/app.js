// Active strategy: "swing" or "lt"
let activeStrategy = "swing";
let swingData = null;
let ltData = null;

function setStrategy(mode) {
    activeStrategy = mode;
    document.getElementById("btn-swing").style.opacity = mode === "swing" ? "1" : "0.45";
    document.getElementById("btn-lt").style.opacity    = mode === "lt"    ? "1" : "0.45";
    const src = mode === "lt" ? ltData : swingData;
    if (src) populateDashboard(src);
}

function loadAllData() {
    const ts = "?t=" + Date.now();
    const btn = document.getElementById("refresh-btn");
    const upd = document.getElementById("last-updated");
    if (btn) btn.textContent = "⟳ Loading…";

    const p1 = fetch("data.json" + ts)
        .then(r => { if (!r.ok) throw new Error("data.json missing"); return r.json(); })
        .then(data => { swingData = data; if (activeStrategy === "swing") populateDashboard(data); })
        .catch(err => console.error("Backtest data error:", err));

    const p1b = fetch("lt_data.json" + ts)
        .then(r => { if (!r.ok) throw new Error("lt_data.json missing"); return r.json(); })
        .then(data => { ltData = data; if (activeStrategy === "lt") populateDashboard(data); })
        .catch(err => console.warn("LT backtest data:", err.message));

    const p2 = fetch("equity_calls.json" + ts)
        .then(r => { if (!r.ok) throw new Error("no calls file"); return r.json(); })
        .then(calls => renderCalls(calls))
        .catch(err => console.warn("Equity calls:", err.message));

    const p3 = fetch("lt_portfolio.json" + ts)
        .then(r => { if (!r.ok) throw new Error("no lt portfolio"); return r.json(); })
        .then(data => renderLTPortfolio(data))
        .catch(err => console.warn("LT Portfolio:", err.message));

    const p4 = fetch("portfolio.json" + ts)
        .then(r => { if (!r.ok) throw new Error("no portfolio.json"); return r.json(); })
        .then(data => renderPortfolio(data))
        .catch(err => console.warn("Portfolio tracker:", err.message));

    const p5 = fetch("smart_money.json" + ts)
        .then(r => { if (!r.ok) throw new Error("no smart_money.json"); return r.json(); })
        .then(data => renderSmartMoney(data))
        .catch(err => console.warn("Smart money:", err.message));

    Promise.allSettled([p1, p1b, p2, p3, p4, p5]).then(() => {
        const now = new Date().toLocaleTimeString();
        if (upd) upd.textContent = "Updated " + now;
        if (btn) btn.textContent = "⟳ Refresh";
    });
}

document.addEventListener("DOMContentLoaded", () => {
    loadAllData();
    // Auto-refresh every 60 seconds
    setInterval(loadAllData, 60000);
});

let globalTradeLogs = [];

function populateDashboard(data) {
    globalTradeLogs = data.trade_logs || [];

    // Update strategy label
    const lbl = document.getElementById("strategy-label");
    if (lbl) lbl.textContent = data.strategy ? `— ${data.strategy}` : "";

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
        const plSign  = log.profit_loss >= 0 ? "+" : "";

        const sig     = log.signal || "BUY";
        const sigClass = sig.startsWith("BUY") ? "action-buy"
                       : sig.startsWith("WATCH") ? "action-watch" : "action-sell";

        const exitReason = log.exit_reason || "TIME";
        const exitClass  = exitReason === "STOP" || exitReason === "FUND_DETERIORATION" || exitReason === "DE_SPIKE"
                         ? "badge loss" : "badge neutral";

        const stopVal = log.stop_loss ? formatCurrency(log.stop_loss) : "—";
        const pattern = log.pattern  || "—";

        row.innerHTML = `
            <td><strong>${log.ticker}</strong></td>
            <td><span class="${sigClass}">${sig}</span></td>
            <td style="font-size:11px;max-width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${pattern}">${pattern}</td>
            <td>${log.entry_date ? log.entry_date.slice(0,10) : "—"}</td>
            <td>${log.exit_date  ? log.exit_date.slice(0,10)  : "—"}</td>
            <td>${formatCurrency(log.entry_price)}</td>
            <td>${stopVal}</td>
            <td>${formatCurrency(log.exit_price)}</td>
            <td>${log.shares.toFixed(2)}</td>
            <td class="${plClass}"><strong>${plSign}${formatCurrency(log.profit_loss)}</strong></td>
            <td class="${plClass}"><strong>${plSign}${formatPercent(log.profit_loss_pct)}</strong></td>
            <td><span class="${exitClass}">${exitReason}</span></td>
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

// --- Global helpers ---
function convClass(c) {
    return ({
        "STRONG BUY":     "action-buy",
        "BUY":            "action-buy",
        "ACCUMULATE":     "action-watch",
        "WATCH":          "action-watch",
        "HIGH CONVICTION":"action-buy",
        "CONFIRMED":      "action-buy",
        "SETUP":          "action-watch",
    })[c] || "action-watch";
}

function fmtPct(v, decimals) {
    if (v == null) return "—";
    const d = decimals != null ? decimals : 2;
    return (v >= 0 ? "+" : "") + v.toFixed(d) + "%";
}

function fmtPrice(v) {
    return v != null ? v.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}) : "—";
}

// --- Sentiment badge helper ---
function sentimentBadge(c) {
    const label = c.sentiment_label || "NEUTRAL";
    const score = c.sentiment_score != null ? (c.sentiment_score > 0 ? "+" : "") + c.sentiment_score.toFixed(2) : "";
    const cls   = label === "BULLISH" ? "sentiment-bullish"
                : label === "BEARISH" ? "sentiment-bearish"
                : "sentiment-neutral";
    const headlines = (c.top_headlines || [])
        .slice(0, 3)
        .map(h => `${h.sentiment}: ${h.title}`)
        .join("\n");
    const tip = headlines
        ? `${label} (${score}, ${c.news_count||0} articles)\n\n${headlines}`
        : `${label} (no news found)`;
    return `<span class="badge ${cls}" title="${tip.replace(/"/g,'&quot;')}" style="cursor:default">${label}</span>`;
}

// --- Equity Calls Rendering ---
function renderCalls(calls) {
    const section = document.getElementById("calls-section");
    if (!section) return;
    section.style.display = "block";

    const ts = document.getElementById("calls-generated-at");
    if (ts) ts.textContent = "Generated: " + (calls.generated_at || "");

    // convClass is now a global helper

    // Long-term
    const ltBody = document.getElementById("lt-calls-body");
    if (ltBody && calls.long_term_calls && calls.long_term_calls.length > 0) {
        ltBody.innerHTML = "";
        calls.long_term_calls.forEach(c => {
            const upside = c.upside_pct != null
                ? `<span class="${c.upside_pct >= 0 ? 'text-green' : 'text-red'}">${(c.upside_pct*100).toFixed(1)}%</span>`
                : "—";
            const fv  = c.fair_value ? `${c.fair_value.toLocaleString()}` : "—";
            const pe  = c.pe ? `${c.pe.toFixed(1)}x` : "—";
            const sent = sentimentBadge(c);
            const convNote = c.sentiment_flagged
                ? `<span class="sentiment-flagged" title="${c.sentiment_note||''}">⚠ ${c.conviction}</span>`
                : `<span class="${convClass(c.conviction)}">${c.conviction}</span>`;
            const row = document.createElement("tr");
            row.innerHTML = `
                <td><strong>${c.ticker}</strong></td>
                <td style="font-size:11px;max-width:140px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${c.name||""}</td>
                <td>${convNote}</td>
                <td>${c.current_price != null ? c.current_price.toLocaleString() : "—"}</td>
                <td>${fv}</td>
                <td>${upside}</td>
                <td>${c.fund_score || "—"}</td>
                <td>${pe}</td>
                <td>${sent}</td>
                <td style="font-size:11px">${c.entry_note||""}</td>
            `;
            ltBody.appendChild(row);
        });
    }

    // Swing
    const swBody = document.getElementById("swing-calls-body");
    if (swBody && calls.swing_calls && calls.swing_calls.length > 0) {
        swBody.innerHTML = "";
        calls.swing_calls.forEach(c => {
            const sigClass = c.signal === "BUY" ? "action-buy" : "action-watch";
            const vol  = c.vol_confirmed ? '<span class="badge win">Yes</span>' : '<span class="badge neutral">No</span>';
            const lvl  = c.at_level ? `<span class="badge neutral" style="font-size:10px">${c.at_level}</span>` : "—";
            const form = c.forming ? " <em style='color:#fbbf24;font-size:10px'>[F]</em>" : "";

            const fmtP = v => v != null ? v.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}) : "—";
            const t1pct = c.upside_pct  != null ? ` <small style="color:#6ee7b7">(+${(c.upside_pct*100).toFixed(1)}%)</small>` : "";
            const t2pct = c.upside_t2   != null ? ` <small style="color:#c084fc">(+${(c.upside_t2*100).toFixed(1)}%)</small>` : "";
            const t3pct = c.upside_t3   != null ? ` <small style="color:#a855f7">(+${(c.upside_t3*100).toFixed(1)}%)</small>` : "";

            const swSent = sentimentBadge(c);
            const swConv = c.sentiment_flagged
                ? `<span class="sentiment-flagged" title="${c.sentiment_note||''}">⚠ ${c.conviction}</span>`
                : `<span class="${convClass(c.conviction)}">${c.conviction}</span>`;
            const row = document.createElement("tr");
            row.innerHTML = `
                <td><strong>${c.ticker}</strong></td>
                <td>${swConv}</td>
                <td style="font-size:11px">${c.pattern||"—"}${form}</td>
                <td><span class="${sigClass}">${c.signal}</span></td>
                <td>${fmtP(c.entry_price)}</td>
                <td style="color:#f87171">${fmtP(c.stop_loss)}</td>
                <td style="color:#6ee7b7">${fmtP(c.t1)}${t1pct}</td>
                <td style="color:#c084fc">${fmtP(c.t2)}${t2pct}</td>
                <td style="color:#a855f7">${fmtP(c.t3)}${t3pct}</td>
                <td>${c.risk_reward ? c.risk_reward.toFixed(1)+"x" : "—"}</td>
                <td>${c.risk_pct ? c.risk_pct.toFixed(1)+"%" : "—"}</td>
                <td>${vol}</td>
                <td>${lvl}</td>
                <td>${swSent}</td>
                <td style="font-size:11px">${c.time_horizon||"—"}</td>
            `;
            swBody.appendChild(row);
        });
    }

    // Sell calls
    const slBody = document.getElementById("sell-calls-body");
    if (slBody && calls.sell_calls && calls.sell_calls.length > 0) {
        slBody.innerHTML = "";
        calls.sell_calls.forEach(c => {
            const sigClass = c.signal === "SELL" ? "action-sell" : "action-watch";
            const vol  = c.vol_confirmed ? '<span class="badge win">Yes</span>' : '<span class="badge neutral">No</span>';
            const lvl  = c.at_level ? `<span class="badge neutral" style="font-size:10px">${c.at_level}</span>` : "—";
            const form = c.forming ? " <em style='color:#fbbf24;font-size:10px'>[F]</em>" : "";

            const fmtP = v => v != null ? v.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}) : "—";
            const t1pct = c.downside_pct  != null ? ` <small style="color:#fca5a5">(-${(c.downside_pct*100).toFixed(1)}%)</small>` : "";
            const t2pct = c.downside_t2   != null ? ` <small style="color:#f87171">(-${(c.downside_t2*100).toFixed(1)}%)</small>` : "";
            const t3pct = c.downside_t3   != null ? ` <small style="color:#ef4444">(-${(c.downside_t3*100).toFixed(1)}%)</small>` : "";

            const slSent = sentimentBadge(c);
            const slConv = c.sentiment_flagged
                ? `<span class="sentiment-flagged" title="${c.sentiment_note||''}">⚠ ${c.conviction}</span>`
                : `<span class="${convClass(c.conviction)}">${c.conviction}</span>`;
            const row = document.createElement("tr");
            row.innerHTML = `
                <td><strong>${c.ticker}</strong></td>
                <td>${slConv}</td>
                <td style="font-size:11px">${c.pattern||"—"}${form}</td>
                <td><span class="${sigClass}">${c.signal}</span></td>
                <td>${fmtP(c.entry_price)}</td>
                <td style="color:#34d399">${fmtP(c.stop_loss)}</td>
                <td style="color:#fca5a5">${fmtP(c.t1)}${t1pct}</td>
                <td style="color:#f87171">${fmtP(c.t2)}${t2pct}</td>
                <td style="color:#ef4444">${fmtP(c.t3)}${t3pct}</td>
                <td>${c.risk_reward ? c.risk_reward.toFixed(1)+"x" : "—"}</td>
                <td>${c.risk_pct ? c.risk_pct.toFixed(1)+"%" : "—"}</td>
                <td>${vol}</td>
                <td>${lvl}</td>
                <td>${slSent}</td>
                <td style="font-size:11px">${c.time_horizon||"—"}</td>
            `;
            slBody.appendChild(row);
        });
    }
}

// --- Live Portfolio / Call Tracker Rendering ---
let portfolioChart = null;

function statusBadge(status) {
    const map = {
        "BUY":  "background:rgba(96,165,250,0.15);color:#60a5fa;border:1px solid rgba(96,165,250,0.35)",
        "HOLD": "background:rgba(52,211,153,0.15);color:#34d399;border:1px solid rgba(52,211,153,0.35)",
        "SELL": "background:rgba(248,113,113,0.15);color:#f87171;border:1px solid rgba(248,113,113,0.35)",
    };
    const style = map[status] || map["HOLD"];
    return `<span style="padding:2px 9px;border-radius:10px;font-size:10px;font-weight:700;${style}">${status}</span>`;
}

function renderPortfolio(data) {
    const section = document.getElementById("portfolio-section");
    if (!section) return;
    section.style.display = "block";

    const ts = document.getElementById("portfolio-generated-at");
    if (ts) ts.textContent = "Updated: " + (data.generated_at || "");

    const s = data.summary || {};

    // ── Summary cards ────────────────────────────────────────────────────────
    const cards = document.getElementById("portfolio-summary-cards");
    if (cards) {
        const avgColor = (s.avg_pnl_pct || 0) >= 0 ? "#34d399" : "#f87171";
        cards.innerHTML = `
            <div class="portfolio-card">
                <div class="portfolio-card-val">${s.total_active || 0}</div>
                <div class="portfolio-card-lbl">Active Calls</div>
            </div>
            <div class="portfolio-card">
                <div class="portfolio-card-val" style="color:${avgColor}">${fmtPct(s.avg_pnl_pct)}</div>
                <div class="portfolio-card-lbl">Avg P&amp;L (Active)</div>
            </div>
            <div class="portfolio-card">
                <div class="portfolio-card-val" style="color:#34d399">${s.closed_wins || 0}</div>
                <div class="portfolio-card-lbl">Closed Wins</div>
            </div>
            <div class="portfolio-card">
                <div class="portfolio-card-val" style="color:#f87171">${s.closed_losses || 0}</div>
                <div class="portfolio-card-lbl">Closed Losses</div>
            </div>
            <div class="portfolio-card">
                <div class="portfolio-card-val" style="color:#fbbf24">${s.stopped_out || 0}</div>
                <div class="portfolio-card-lbl">Stopped Out</div>
            </div>
            ${s.best_call ? `<div class="portfolio-card">
                <div class="portfolio-card-val" style="color:#34d399">${s.best_call.ticker} ${fmtPct(s.best_call.pnl_pct)}</div>
                <div class="portfolio-card-lbl">Best Active</div>
            </div>` : ""}
            ${s.worst_call ? `<div class="portfolio-card">
                <div class="portfolio-card-val" style="color:#f87171">${s.worst_call.ticker} ${fmtPct(s.worst_call.pnl_pct)}</div>
                <div class="portfolio-card-lbl">Worst Active</div>
            </div>` : ""}
        `;
    }

    // ── Equity P&L Curve ─────────────────────────────────────────────────────
    const curves     = data.equity_curves   || {};
    const combined   = data.portfolio_curve || [];

    if (combined.length > 0 || Object.keys(curves).length > 0) {
        const canvas = document.getElementById("portfolio-pnl-chart");
        if (canvas) {
            if (portfolioChart) { portfolioChart.destroy(); portfolioChart = null; }

            const palette = [
                "#60a5fa","#34d399","#a78bfa","#fbbf24","#f87171",
                "#38bdf8","#4ade80","#c084fc","#fb923c","#f472b6",
            ];
            const datasets = [];

            // Individual call curves (thin, semi-transparent)
            let ci = 0;
            for (const [ticker, curve] of Object.entries(curves)) {
                if (!curve || curve.length === 0) continue;
                datasets.push({
                    label: ticker,
                    data:  curve.map(p => ({ x: p.date, y: p.pnl_pct })),
                    borderColor: palette[ci % palette.length],
                    backgroundColor: "transparent",
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.3,
                });
                ci++;
            }

            // Combined portfolio curve (bold white)
            if (combined.length > 0) {
                datasets.push({
                    label: "Portfolio Avg",
                    data:  combined.map(p => ({ x: p.date, y: p.pnl_pct })),
                    borderColor: "#ffffff",
                    backgroundColor: "rgba(255,255,255,0.06)",
                    borderWidth: 2.5,
                    pointRadius: 0,
                    fill: true,
                    tension: 0.3,
                    order: 0,
                });
            }

            portfolioChart = new Chart(canvas, {
                type: "line",
                data: { datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: "index", intersect: false },
                    scales: {
                        x: {
                            type: "time",
                            time: { unit: "day", displayFormats: { day: "MMM d" } },
                            grid: { color: "rgba(255,255,255,0.05)" },
                            ticks: { color: "#6b7280", maxTicksLimit: 10 },
                        },
                        y: {
                            grid: { color: "rgba(255,255,255,0.05)" },
                            ticks: {
                                color: "#6b7280",
                                callback: v => (v >= 0 ? "+" : "") + v.toFixed(1) + "%",
                            },
                        },
                    },
                    plugins: {
                        legend: {
                            labels: { color: "#9ca3af", font: { size: 11 }, boxWidth: 14 },
                        },
                        tooltip: {
                            callbacks: {
                                label: ctx => `${ctx.dataset.label}: ${fmtPct(ctx.parsed.y)}`,
                            },
                        },
                    },
                },
            });
        }
    }

    // ── Active calls table ────────────────────────────────────────────────────
    const activeBody = document.getElementById("portfolio-active-body");
    if (activeBody) {
        const rows = data.active || [];
        if (rows.length > 0) {
            activeBody.innerHTML = "";
            rows.forEach(c => {
                const pnlPct   = c.pnl_pct != null ? c.pnl_pct * 100 : null;
                const pnlAbs   = c.pnl_abs != null ? c.pnl_abs : null;
                const pColor   = (pnlPct || 0) >= 0 ? "#34d399" : "#f87171";
                const pnlDisp  = pnlPct != null
                    ? `<span style="color:${pColor};font-weight:700">${fmtPct(pnlPct)}</span>` : "—";
                const pnlAbsD  = pnlAbs != null
                    ? `<span style="color:${pColor}">${pnlAbs >= 0 ? "+" : ""}$${Math.abs(pnlAbs).toFixed(0)}</span>` : "—";
                const row = document.createElement("tr");
                row.innerHTML = `
                    <td><strong>${c.ticker}</strong></td>
                    <td style="font-size:11px">${c.call_type || "—"}</td>
                    <td><span class="${convClass(c.conviction)}" style="font-size:11px">${c.conviction || "—"}</span></td>
                    <td style="font-size:11px">${(c.call_date||"").slice(0,10)}</td>
                    <td>${fmtPrice(c.entry_price)}</td>
                    <td style="font-weight:600">${fmtPrice(c.current_price)}</td>
                    <td>${pnlDisp}</td>
                    <td>${pnlAbsD}</td>
                    <td style="color:#f87171;font-size:11px">${c.stop_loss ? fmtPrice(c.stop_loss) : "—"}</td>
                    <td style="color:#6ee7b7;font-size:11px">${c.t1 ? fmtPrice(c.t1) : "—"}</td>
                    <td>${sentimentBadge(c)}</td>
                    <td>${statusBadge(c.status)}</td>
                    <td style="font-size:11px;max-width:200px;color:#d1d5db">${c.recommendation || "—"}</td>
                `;
                activeBody.appendChild(row);
            });
        } else {
            activeBody.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--text-muted)">No active calls. Run <code>python generate_calls.py</code></td></tr>';
        }
    }

    // ── Closed calls table ────────────────────────────────────────────────────
    const closedBody = document.getElementById("portfolio-closed-body");
    if (closedBody) {
        const rows = data.closed || [];
        if (rows.length > 0) {
            closedBody.innerHTML = "";
            rows.forEach(c => {
                const pnlPct  = c.pnl_pct != null ? c.pnl_pct * 100 : null;
                const pnlAbs  = c.pnl_abs != null ? c.pnl_abs : null;
                const pColor  = (pnlPct || 0) >= 0 ? "#34d399" : "#f87171";
                const pnlDisp = pnlPct != null
                    ? `<span style="color:${pColor};font-weight:700">${fmtPct(pnlPct)}</span>` : "—";
                const pnlAbsD = pnlAbs != null
                    ? `<span style="color:${pColor}">${pnlAbs >= 0 ? "+" : ""}$${Math.abs(pnlAbs).toFixed(0)}</span>` : "—";
                const row = document.createElement("tr");
                row.innerHTML = `
                    <td><strong>${c.ticker}</strong></td>
                    <td style="font-size:11px">${c.call_type || "—"}</td>
                    <td style="font-size:11px">${(c.call_date||"").slice(0,10)}</td>
                    <td>${fmtPrice(c.entry_price)}</td>
                    <td>${fmtPrice(c.exit_price)}</td>
                    <td>${pnlDisp}</td>
                    <td>${pnlAbsD}</td>
                    <td>${statusBadge(c.status)}</td>
                    <td style="font-size:11px;color:#9ca3af">${(c.notes||"").slice(0,80)}</td>
                `;
                closedBody.appendChild(row);
            });
        } else {
            closedBody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted)">No closed calls yet</td></tr>';
        }
    }
}

// --- Long-Term Portfolio Rendering ---
function renderLTPortfolio(data) {
    const section = document.getElementById("lt-portfolio-section");
    if (!section) return;
    section.style.display = "block";

    const meta     = data.meta     || {};
    const holdings = data.holdings || {};

    const totalInvested   = meta.total_invested   || 0;
    const portfolioValue  = meta.portfolio_value  || 0;
    const gainPct         = meta.total_gain_pct   || 0;
    const cash            = meta.cash             || 0;

    // Summary cards
    const elInvested = document.getElementById("lt-total-invested");
    const elValue    = document.getElementById("lt-portfolio-value");
    const elGain     = document.getElementById("lt-gain-pct");
    const elCash     = document.getElementById("lt-cash");

    if (elInvested) elInvested.textContent = formatCurrency(totalInvested);
    if (elValue)    elValue.textContent    = formatCurrency(portfolioValue);
    if (elGain) {
        elGain.textContent  = (gainPct >= 0 ? "+" : "") + (gainPct * 100).toFixed(2) + "%";
        elGain.className    = "lt-card-value " + (gainPct >= 0 ? "text-green" : "text-red");
    }
    if (elCash) elCash.textContent = formatCurrency(cash);

    // Holdings table
    const tbody = document.getElementById("lt-holdings-body");
    if (!tbody) return;
    tbody.innerHTML = "";

    const tickers = Object.keys(holdings);
    if (tickers.length === 0) {
        tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;color:var(--text-muted)">
            No holdings yet. Run <code>python long_term_portfolio.py --add TICKER</code></td></tr>`;
        return;
    }

    tickers.forEach(ticker => {
        const h = holdings[ticker];

        const nTranches   = h.n_tranches  || (h.tranches ? h.tranches.length : 0);
        const avgCost     = h.avg_cost     || 0;
        const currPrice   = h.current_price || avgCost;
        const gainP       = h.gain_pct     || 0;
        const fairVal     = h.fair_value;
        const toFv        = h.to_fv_pct;
        const score       = h.fund_score   || 0;
        const status      = h.thesis_status || "HOLD";
        const action      = h.action_hint  || "";
        const name        = (h.name || ticker).substring(0, 22);

        // Status badge color
        let badgeClass = "action-buy";
        let badgeStyle = "";
        if (status === "WATCH") {
            badgeClass = "action-watch";
        } else if (status === "TRIM") {
            badgeClass = "";
            badgeStyle = 'style="background:rgba(251,146,60,0.18);color:#fb923c;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600"';
        } else if (status === "EXIT") {
            badgeClass = "action-sell";
        }

        const gainClass  = gainP >= 0 ? "text-green" : "text-red";
        const gainStr    = (gainP >= 0 ? "+" : "") + (gainP * 100).toFixed(1) + "%";
        const toFvStr    = toFv != null
            ? `<span class="${toFv >= 0 ? 'text-green' : 'text-red'}">${(toFv >= 0 ? "+" : "")}${(toFv * 100).toFixed(1)}%</span>`
            : "—";
        const fvStr      = fairVal ? "$" + fairVal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) : "—";
        const scoreColor = score >= 70 ? "#34d399" : score >= 60 ? "#fbbf24" : "#f87171";

        let statusBadge;
        if (badgeClass) {
            statusBadge = `<span class="${badgeClass}">${status}</span>`;
        } else {
            statusBadge = `<span ${badgeStyle}>${status}</span>`;
        }

        const row = document.createElement("tr");
        row.innerHTML = `
            <td><strong>${ticker}</strong></td>
            <td style="font-size:11px;max-width:130px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${name}</td>
            <td style="text-align:center">${nTranches}/3</td>
            <td>$${avgCost.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</td>
            <td>$${currPrice.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}</td>
            <td class="${gainClass}"><strong>${gainStr}</strong></td>
            <td>${fvStr}</td>
            <td>${toFvStr}</td>
            <td style="color:${scoreColor};font-weight:600">${score.toFixed(1)}</td>
            <td>${statusBadge}</td>
            <td style="font-size:11px;color:#9ca3af">${action}</td>
        `;
        tbody.appendChild(row);
    });
}

// --- Smart Money Rendering ---
function renderSmartMoney(data) {
    const section = document.getElementById("smart-money-section");
    if (!section) return;
    section.style.display = "block";

    const ts = document.getElementById("sm-generated-at");
    if (ts) ts.textContent = "Generated: " + (data.generated_at || "—");

    const grid = document.getElementById("sm-ticker-grid");
    if (!grid) return;
    grid.innerHTML = "";

    const tickers = data.tickers || {};
    if (Object.keys(tickers).length === 0) {
        grid.innerHTML = '<p style="color:var(--text-muted);text-align:center">No data. Run <code>python smart_money.py</code></p>';
        return;
    }

    const overallColor = {
        "BULLISH": "#34d399", "BEARISH": "#f87171",
        "MIXED": "#fbbf24",   "NEUTRAL": "#6b7280"
    };
    const signalIcon = {
        "BUYING": "↑", "SELLING": "↓", "MIXED": "~", "NEUTRAL": "–", "NONE": "–",
        "INCREASING": "↑", "DECREASING": "↓", "STABLE": "~", "UNKNOWN": "–",
        "BULLISH": "↑", "BEARISH": "↓",
    };
    const signalColor = {
        "BUYING": "#34d399", "SELLING": "#f87171", "MIXED": "#fbbf24", "NEUTRAL": "#6b7280", "NONE": "#6b7280",
        "INCREASING": "#34d399", "DECREASING": "#f87171", "STABLE": "#9ca3af", "UNKNOWN": "#6b7280",
        "BULLISH": "#34d399", "BEARISH": "#f87171",
    };

    function pill(signal, label) {
        const c = signalColor[signal] || "#6b7280";
        const i = signalIcon[signal] || "–";
        return `<span style="color:${c};font-weight:700;font-size:12px">${i} ${label || signal}</span>`;
    }

    Object.entries(tickers).forEach(([ticker, d]) => {
        const overall = d.overall || "NEUTRAL";
        const ins     = d.insiders    || {};
        const cong    = d.congress    || {};
        const hf      = d.hedge_funds || {};
        const news    = d.news        || {};

        const borderCol = overallColor[overall] || "#374151";

        // Build insider recent trades tooltip
        const insRows = (ins.recent || []).slice(0, 4).map(r =>
            `${r.date} ${r.direction} ${r.name} (${r.role || "—"}) ${r.shares ? r.shares.toLocaleString() + " sh" : ""}`
        ).join("\n");

        // Build congress trades rows
        const congRows = (cong.recent || []).slice(0, 4).map(r =>
            `${r.date} ${r.direction} ${r.member} [${r.chamber}] ${r.amount}`
        ).join("\n");

        // Top hedge fund holders
        const hfRows = (hf.top_holders || []).slice(0, 4).map(h =>
            `${h.name}: ${h.pct_held}% held  (${h.change_pct >= 0 ? "+" : ""}${h.change_pct}% chg)`
        ).join("\n");

        // News headlines
        const newsHtml = (news.top_headlines || []).slice(0, 3).map(h => {
            const title = typeof h === "string" ? h : (h.title || "");
            const sent  = typeof h === "object" ? (h.sentiment || "") : "";
            const col   = sent === "positive" ? "#34d399" : sent === "negative" ? "#f87171" : "#9ca3af";
            return `<div style="font-size:10px;color:${col};line-height:1.4;margin-bottom:3px">• ${title.slice(0,80)}</div>`;
        }).join("");

        const card = document.createElement("div");
        card.style.cssText = `
            background:rgba(17,24,39,0.8);
            border:1px solid ${borderCol}44;
            border-left:3px solid ${borderCol};
            border-radius:10px;
            padding:16px;
            display:flex;
            flex-direction:column;
            gap:10px;
        `;

        card.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between">
                <div style="display:flex;align-items:center;gap:10px">
                    <strong style="font-size:1rem;color:#f3f4f6">${ticker}</strong>
                    <span style="color:${borderCol};font-size:11px;font-weight:700;background:${borderCol}18;padding:2px 8px;border-radius:10px">${overall}</span>
                </div>
                <span style="font-size:10px;color:#4b5563">${(news.news_count||0)} articles</span>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
                <div style="background:rgba(0,0,0,0.3);border-radius:8px;padding:10px" title="${insRows.replace(/"/g,"&quot;")}">
                    <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Insiders</div>
                    ${pill(ins.signal)}
                    <div style="font-size:10px;color:#9ca3af;margin-top:4px">
                        ${ins.buy_count||0} buy · ${ins.sell_count||0} sell (${(data.lookback_days||90)}d)
                    </div>
                </div>
                <div style="background:rgba(0,0,0,0.3);border-radius:8px;padding:10px" title="${congRows.replace(/"/g,"&quot;")}">
                    <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Congress</div>
                    ${pill(cong.signal)}
                    <div style="font-size:10px;color:#9ca3af;margin-top:4px">
                        ${cong.buy_count||0} buy · ${cong.sell_count||0} sell (${(data.lookback_days||90)}d)
                    </div>
                </div>
                <div style="background:rgba(0,0,0,0.3);border-radius:8px;padding:10px" title="${hfRows.replace(/"/g,"&quot;")}">
                    <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Hedge Funds</div>
                    ${pill(hf.net_signal)}
                    <div style="font-size:10px;color:#9ca3af;margin-top:4px">
                        ${(hf.top_holders||[]).length} holders tracked
                    </div>
                </div>
            </div>

            ${newsHtml ? `
            <div style="border-top:1px solid rgba(255,255,255,0.06);padding-top:8px">
                <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px">
                    News · <span style="color:${signalColor[news.sentiment_label]||'#6b7280'}">${news.sentiment_label||"NEUTRAL"}</span>
                </div>
                ${newsHtml}
            </div>` : ""}

            ${(ins.recent || []).length > 0 ? `
            <details style="border-top:1px solid rgba(255,255,255,0.06);padding-top:8px">
                <summary style="font-size:10px;color:#6b7280;cursor:pointer;text-transform:uppercase;letter-spacing:.05em">
                    Insider Transactions (${(ins.recent||[]).length})
                </summary>
                <div style="margin-top:8px;display:flex;flex-direction:column;gap:4px">
                ${(ins.recent||[]).map(r => `
                    <div style="display:flex;justify-content:space-between;font-size:11px;color:#9ca3af">
                        <span style="color:${r.direction==='BUY'?'#34d399':'#f87171'};font-weight:600">${r.direction}</span>
                        <span style="flex:1;margin:0 8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.name} <span style="color:#4b5563">${r.role}</span></span>
                        <span>${r.shares ? r.shares.toLocaleString() + " sh" : ""}</span>
                        <span style="margin-left:8px;color:#6b7280">${r.date}</span>
                    </div>`).join("")}
                </div>
            </details>` : ""}

            ${(cong.recent || []).length > 0 ? `
            <details style="border-top:1px solid rgba(255,255,255,0.06);padding-top:8px">
                <summary style="font-size:10px;color:#6b7280;cursor:pointer;text-transform:uppercase;letter-spacing:.05em">
                    Congressional Trades (${(cong.recent||[]).length})
                </summary>
                <div style="margin-top:8px;display:flex;flex-direction:column;gap:4px">
                ${(cong.recent||[]).map(r => `
                    <div style="display:flex;justify-content:space-between;font-size:11px;color:#9ca3af;gap:6px">
                        <span style="color:${r.direction==='BUY'?'#34d399':'#f87171'};font-weight:600">${r.direction}</span>
                        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.member}</span>
                        <span style="color:#6b7280">[${r.chamber}]</span>
                        <span style="color:#fbbf24">${r.amount}</span>
                        <span style="color:#6b7280">${r.date}</span>
                    </div>`).join("")}
                </div>
            </details>` : ""}

            ${(hf.top_holders || []).length > 0 ? `
            <details style="border-top:1px solid rgba(255,255,255,0.06);padding-top:8px">
                <summary style="font-size:10px;color:#6b7280;cursor:pointer;text-transform:uppercase;letter-spacing:.05em">
                    Top Institutional Holders
                </summary>
                <div style="margin-top:8px;display:flex;flex-direction:column;gap:4px">
                ${(hf.top_holders||[]).map(h => `
                    <div style="display:flex;justify-content:space-between;font-size:11px;color:#9ca3af;gap:6px">
                        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${h.name}</span>
                        <span>${h.pct_held}%</span>
                        <span style="color:${h.change_pct>=0?'#34d399':'#f87171'};font-weight:600">${h.change_pct>=0?'+':''}${h.change_pct}%</span>
                        <span style="color:#6b7280">${h.date_reported}</span>
                    </div>`).join("")}
                </div>
            </details>` : ""}
        `;

        grid.appendChild(card);
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
