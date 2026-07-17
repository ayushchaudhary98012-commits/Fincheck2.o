// FinCheck - Financial Dashboard Charts Module

document.addEventListener('DOMContentLoaded', () => {
    initResultGauge();
    initAdminCharts();
});

// --- Semi-Circular Score Gauge Chart ---
function initResultGauge() {
    const canvas = document.getElementById('gauge-chart');
    if (!canvas) return;
    
    const score = parseInt(canvas.getAttribute('data-score')) || 0;
    
    // Choose color based on score
    let color = '#ef4444'; // Red
    if (score >= 40 && score < 70) {
        color = '#f59e0b'; // Amber
    } else if (score >= 70) {
        color = '#10b981'; // Emerald Green
    }
    
    // Configure half doughnut gauge
    new Chart(canvas, {
        type: 'doughnut',
        data: {
            datasets: [{
                data: [score, 100 - score],
                backgroundColor: [color, 'var(--bg-tertiary)'],
                borderWidth: 0
            }]
        },
        options: {
            rotation: 270,
            circumference: 180,
            cutout: '80%',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { enabled: false }
            }
        }
    });
}

// --- Admin Analytics Charts ---
function initAdminCharts() {
    const approvalCanvas = document.getElementById('approval-pie-chart');
    const monthlyCanvas = document.getElementById('monthly-bar-chart');
    const riskCanvas = document.getElementById('risk-doughnut-chart');
    
    if (!approvalCanvas && !monthlyCanvas && !riskCanvas) return;
    
    // Fetch stats from backend API
    fetch('/api/admin/stats')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                renderApprovalChart(approvalCanvas, data.stats.status_counts);
                renderMonthlyChart(monthlyCanvas, data.stats.monthly_counts);
                renderRiskChart(riskCanvas, data.stats.risk_counts);
            } else {
                console.error("Failed to load charts statistics:", data.message);
            }
        })
        .catch(err => {
            console.error("Error fetching admin stats:", err);
        });
}

function renderApprovalChart(canvas, counts) {
    if (!canvas) return;
    
    const labels = ['Approved', 'Moderate', 'Rejected', 'Pending'];
    const values = [
        counts['Approved'] || 0,
        counts['Moderate'] || 0,
        counts['Rejected'] || 0,
        counts['Pending'] || 0
    ];
    
    new Chart(canvas, {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: ['#10b981', '#f59e0b', '#ef4444', '#94a3b8'],
                borderColor: 'var(--bg-secondary)',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: 'var(--text-primary)', font: { family: 'Outfit' } }
                }
            }
        }
    });
}

function renderMonthlyChart(canvas, monthlyCounts) {
    if (!canvas) return;
    
    // monthlyCounts is expected to be list of dicts: [{'month': '2026-05', 'count': 5}, ...]
    const labels = monthlyCounts.map(item => item.month);
    const values = monthlyCounts.map(item => item.count);
    
    new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Applications',
                data: values,
                backgroundColor: 'rgba(37, 99, 235, 0.7)',
                borderColor: '#2563eb',
                borderWidth: 1,
                borderRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: 'var(--text-secondary)', font: { family: 'Outfit' } }
                },
                y: {
                    grid: { color: 'var(--glass-border)' },
                    ticks: { 
                        color: 'var(--text-secondary)', 
                        font: { family: 'Outfit' },
                        precision: 0
                    }
                }
            }
        }
    });
}

function renderRiskChart(canvas, counts) {
    if (!canvas) return;
    
    const labels = ['Low Risk', 'Medium Risk', 'High Risk'];
    const values = [
        counts['Low'] || 0,
        counts['Medium'] || 0,
        counts['High'] || 0
    ];
    
    new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: ['#10b981', '#f59e0b', '#ef4444'],
                borderColor: 'var(--bg-secondary)',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '70%',
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: 'var(--text-primary)', font: { family: 'Outfit' } }
                }
            }
        }
    });
}
