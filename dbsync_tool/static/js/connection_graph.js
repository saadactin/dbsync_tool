/**
 * Connection Relationship Graph Visualization
 * Uses D3.js force-directed graph to visualize data flow between connections
 */

// Database type colors
const DB_TYPE_COLORS = {
    'postgres': '#3366cc',      // Blue
    'mysql': '#ff9900',         // Orange
    'sqlserver': '#00cc66',     // Green
    'clickhouse': '#9966cc'     // Purple
};

// Health status colors
const HEALTH_COLORS = {
    'healthy': '#28a745',        // Green
    'warning': '#ffc107',        // Yellow
    'critical': '#dc3545'        // Red
};

let graphData = null;
let simulation = null;
let svg = null;
let g = null;
let zoom = null;

/**
 * Initialize the connection graph
 */
function initConnectionGraph() {
    // Get graph container
    const container = document.getElementById('connectionGraphContainer');
    if (!container) {
        console.error('Connection graph container not found');
        return;
    }

    // Load graph data via AJAX
    fetch('/api/jobs/connections/graph/', {
        method: 'GET',
        headers: {
            'X-CSRFToken': getCsrfToken(),
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        credentials: 'same-origin'
    })
    .then(response => {
        if (!response.ok) {
            return response.text().then(text => {
                console.error('API Error Response:', text);
                throw new Error(`HTTP ${response.status}: ${text}`);
            });
        }
        return response.json();
    })
    .then(data => {
        console.log('Graph data loaded:', data);
        graphData = data;
        renderGraph(container, data);
    })
    .catch(error => {
        console.error('Error loading connection graph:', error);
        const errorMsg = error.message || 'Unknown error';
        container.innerHTML = `
            <div class="alert alert-danger">
                <strong>Failed to load connection graph</strong><br/>
                <small>Error: ${errorMsg}</small><br/>
                <button class="btn btn-sm btn-primary mt-2" onclick="initConnectionGraph()">Retry</button>
            </div>
        `;
    });
}

/**
 * Render the D3.js force-directed graph
 */
function renderGraph(container, data) {
    // Clear container
    container.innerHTML = '';

    if (!data || !data.nodes || data.nodes.length === 0) {
        container.innerHTML = `
            <div class="alert alert-info text-center p-5">
                <h6>No Connections Found</h6>
                <p class="mb-0">Create database connections and sync jobs to see the relationship graph.</p>
                <a href="/connections/" class="btn btn-sm btn-primary mt-2">Create Connection</a>
            </div>
        `;
        return;
    }

    // Set up dimensions
    const width = container.clientWidth || 800;
    const height = Math.max(600, container.clientHeight || 600);

    // Create SVG
    svg = d3.select(container)
        .append('svg')
        .attr('width', width)
        .attr('height', height);

    // Create container group for zoom
    g = svg.append('g');

    // Set up zoom behavior
    zoom = d3.zoom()
        .scaleExtent([0.1, 4])
        .on('zoom', (event) => {
            g.attr('transform', event.transform);
        });

    svg.call(zoom);

    // Create arrow markers for edges
    svg.append('defs')
        .selectAll('marker')
        .data(['end'])
        .enter()
        .append('marker')
        .attr('id', 'arrowhead')
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 25)
        .attr('refY', 0)
        .attr('markerWidth', 6)
        .attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-5L10,0L0,5')
        .attr('fill', '#999');

    // Create tooltip
    const tooltip = d3.select('body')
        .append('div')
        .attr('class', 'graph-tooltip')
        .style('opacity', 0)
        .style('position', 'absolute')
        .style('background', 'rgba(0, 0, 0, 0.8)')
        .style('color', 'white')
        .style('padding', '8px')
        .style('border-radius', '4px')
        .style('pointer-events', 'none')
        .style('z-index', '1000')
        .style('font-size', '12px');

    // Create edges (lines)
    const edgesGroup = g.append('g').attr('class', 'edges');
    let edges = null;
    
    if (data.edges && data.edges.length > 0) {
        edges = edgesGroup.selectAll('line')
            .data(data.edges)
            .enter()
            .append('line')
            .attr('stroke-width', d => Math.max(1, Math.min(5, d.job_count)))
            .attr('stroke', d => HEALTH_COLORS[d.status] || '#999')
            .attr('marker-end', 'url(#arrowhead)')
            .attr('opacity', 0.6)
            .on('mouseover', function(event, d) {
                tooltip.transition()
                    .duration(200)
                    .style('opacity', 0.9);
                const jobNames = d.jobs.map(j => j.name).join(', ');
                tooltip.html(`
                    <strong>${d.job_count} Job(s)</strong><br/>
                    Success Rate: ${d.success_rate}%<br/>
                    Status: ${d.status}<br/>
                    Jobs: ${jobNames}
                `)
                .style('left', (event.pageX + 10) + 'px')
                .style('top', (event.pageY - 10) + 'px');
            })
            .on('mouseout', function() {
                tooltip.transition()
                    .duration(200)
                    .style('opacity', 0);
            });
    }

    // Create nodes (circles)
    const nodes = g.append('g')
        .attr('class', 'nodes')
        .selectAll('circle')
        .data(data.nodes)
        .enter()
        .append('circle')
        .attr('r', d => Math.max(20, Math.min(40, 20 + d.job_count * 2)))
        .attr('fill', d => DB_TYPE_COLORS[d.type] || '#999')
        .attr('stroke', '#fff')
        .attr('stroke-width', 2)
        .call(d3.drag()
            .on('start', dragStarted)
            .on('drag', dragged)
            .on('end', dragEnded))
        .on('mouseover', function(event, d) {
            tooltip.transition()
                .duration(200)
                .style('opacity', 0.9);
            tooltip.html(`
                <strong>${d.name}</strong><br/>
                Type: ${d.type}<br/>
                Jobs: ${d.job_count}<br/>
                Status: ${d.is_active ? 'Active' : 'Inactive'}
            `)
            .style('left', (event.pageX + 10) + 'px')
            .style('top', (event.pageY - 10) + 'px');
            
            d3.select(this)
                .attr('stroke-width', 4)
                .attr('opacity', 0.9);
        })
        .on('mouseout', function() {
            tooltip.transition()
                .duration(200)
                .style('opacity', 0);
            
            d3.select(this)
                .attr('stroke-width', 2)
                .attr('opacity', 1);
        })
        .on('click', function(event, d) {
            // Show connected jobs in a modal or alert
            const connectedJobs = data.edges
                .filter(e => e.source === d.id || e.target === d.id)
                .flatMap(e => e.jobs)
                .map(j => j.name);
            
            if (connectedJobs.length > 0) {
                alert(`Connected Jobs:\n${connectedJobs.join('\n')}`);
            } else {
                alert('No jobs connected to this connection');
            }
        });

    // Create labels
    const labels = g.append('g')
        .attr('class', 'labels')
        .selectAll('text')
        .data(data.nodes)
        .enter()
        .append('text')
        .text(d => d.name)
        .attr('font-size', '12px')
        .attr('dx', 25)
        .attr('dy', 5)
        .attr('fill', '#333')
        .attr('pointer-events', 'none');

    // Set up force simulation
    simulation = d3.forceSimulation(data.nodes);
    
    if (data.edges && data.edges.length > 0) {
        simulation.force('link', d3.forceLink(data.edges)
            .id(d => d.id)
            .distance(100)
            .strength(0.5));
    }
    
    simulation
        .force('charge', d3.forceManyBody()
            .strength(-300))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide()
            .radius(d => Math.max(25, Math.min(45, 25 + d.job_count * 2))));

    // Update positions on tick
    simulation.on('tick', () => {
        if (edges) {
            edges
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);
        }

        nodes
            .attr('cx', d => d.x)
            .attr('cy', d => d.y);

        labels
            .attr('x', d => d.x)
            .attr('y', d => d.y);
    });
}

/**
 * Drag event handlers
 */
function dragStarted(event, d) {
    if (!event.active) simulation.alphaTarget(0.3).restart();
    d.fx = d.x;
    d.fy = d.y;
}

function dragged(event, d) {
    d.fx = event.x;
    d.fy = event.y;
}

function dragEnded(event, d) {
    if (!event.active) simulation.alphaTarget(0);
    d.fx = null;
    d.fy = null;
}

/**
 * Reset zoom and pan
 */
function resetGraphView() {
    if (svg && zoom) {
        svg.transition()
            .duration(750)
            .call(zoom.transform, d3.zoomIdentity);
    }
}

/**
 * Get CSRF token from cookies
 */
function getCsrfToken() {
    const name = 'csrftoken';
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}
