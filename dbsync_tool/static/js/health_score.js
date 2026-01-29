/**
 * Health Score Visualization
 * Displays sync health score as circular gauge with trend
 */

function initHealthScoreChart(score, components, trendData, trendDirection) {
    // Determine color based on score
    let color;
    if (score >= 76) {
        color = '#28a745'; // Green
    } else if (score >= 51) {
        color = '#ffc107'; // Yellow
    } else {
        color = '#dc3545'; // Red
    }
    
    // Create doughnut chart
    const ctx = document.getElementById('healthScoreChart');
    if (!ctx) return;
    
    const chart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            datasets: [{
                data: [score, 100 - score],
                backgroundColor: [color, '#e9ecef'],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '75%',
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    enabled: false
                }
            }
        },
        plugins: [{
            id: 'centerText',
            beforeDraw: function(chart) {
                const ctx = chart.ctx;
                const centerX = chart.chartArea.left + (chart.chartArea.right - chart.chartArea.left) / 2;
                const centerY = chart.chartArea.top + (chart.chartArea.bottom - chart.chartArea.top) / 2;
                
                ctx.save();
                ctx.font = 'bold 48px Arial';
                ctx.fillStyle = color;
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(score, centerX, centerY);
                ctx.restore();
            }
        }]
    });
    
    // Update trend badge
    const trendBadge = document.getElementById('healthScoreTrend');
    if (trendBadge) {
        let badgeClass = 'bg-secondary';
        let badgeText = 'Stable';
        
        if (trendDirection === 'improving') {
            badgeClass = 'bg-success';
            badgeText = '↑ Improving';
        } else if (trendDirection === 'degrading') {
            badgeClass = 'bg-danger';
            badgeText = '↓ Degrading';
        }
        
        trendBadge.className = `badge ${badgeClass}`;
        trendBadge.textContent = badgeText;
    }
    
    // Create trend sparkline
    if (trendData && trendData.length > 0) {
        const trendCtx = document.getElementById('healthScoreTrendChart');
        if (trendCtx) {
            const trendChart = new Chart(trendCtx, {
                type: 'line',
                data: {
                    labels: trendData.map(d => {
                        const date = new Date(d.date);
                        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                    }),
                    datasets: [{
                        data: trendData.map(d => d.score),
                        borderColor: color,
                        backgroundColor: color + '20',
                        borderWidth: 2,
                        fill: true,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    return 'Score: ' + context.parsed.y;
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100,
                            display: false
                        },
                        x: {
                            display: false
                        }
                    }
                }
            });
        }
    }
}
