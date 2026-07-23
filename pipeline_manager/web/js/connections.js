let isDragging = false;
let dragNodeId = null;
let dragStartX = 0;
let dragStartY = 0;
let dragNodeStartX = 0;
let dragNodeStartY = 0;

let connectingFrom = null;
let connectingPortType = null;
let tempLine = null;

function startDrag(e, id) {
    isDragging = true;
    dragNodeId = id;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    const node = nodes.find(n => n.id === id);
    dragNodeStartX = node.x;
    dragNodeStartY = node.y;
}

document.addEventListener('mousemove', function(e) {
    if (isDragging && dragNodeId) {
        e.preventDefault();
        const dx = (e.clientX - dragStartX) / currentZoom;
        const dy = (e.clientY - dragStartY) / currentZoom;
        const node = nodes.find(n => n.id === dragNodeId);
        if (node) {
            node.x = dragNodeStartX + dx;
            node.y = dragNodeStartY + dy;
            const el = document.getElementById(dragNodeId);
            if (el) {
                el.style.left = node.x + 'px';
                el.style.top = node.y + 'px';
            }
            updateConnections();
        }
    }
    
    if (connectingFrom) {
        e.preventDefault();
        updateTempLine(e.clientX, e.clientY);
    }
    
    const canvasRect = document.getElementById('canvas-container').getBoundingClientRect();
    const x = (e.clientX - canvasRect.left - panOffsetX) / currentZoom;
    const y = (e.clientY - canvasRect.top - panOffsetY) / currentZoom;
    document.getElementById('pos').textContent = 'Position: ' + Math.round(x) + ', ' + Math.round(y);
});

document.addEventListener('mouseup', function(e) {
    if (isDragging) {
        isDragging = false;
        dragNodeId = null;
        autoSave();
    }
    
    if (connectingFrom) {
        const target = e.target;
        if (target.classList.contains('port-circle')) {
            const nodeId = target.getAttribute('data-node');
            const portName = target.getAttribute('data-port');
            const portType = target.getAttribute('data-type');
            
            if (portType !== connectingPortType) {
                if (portType === 'input') {
                    createConnection(connectingFrom.node, connectingFrom.port, nodeId, portName);
                } else {
                    createConnection(nodeId, portName, connectingFrom.node, connectingFrom.port);
                }
            }
        }
        
        removeTempLine();
        connectingFrom = null;
        connectingPortType = null;
    }
});

const canvasContainer = document.getElementById('canvas-container');

canvasContainer.addEventListener('mousedown', function(e) {
    if (e.button === 0 && !e.target.classList.contains('node') && !e.target.classList.contains('port-circle') && !e.target.classList.contains('port-name') && !e.target.classList.contains('node-delete') && !e.target.classList.contains('node-title') && !e.target.closest('.node') && !e.target.classList.contains('connection-line')) {
        if (selectedConnection !== null) {
            selectedConnection = null;
            updateConnections();
            showProperties();
        }
        isPanning = true;
        panStartX = e.clientX;
        panStartY = e.clientY;
        canvasContainer.classList.add('panning');
    }
});

canvasContainer.addEventListener('mouseup', function(e) {
    if (e.button === 0) {
        isPanning = false;
        canvasContainer.classList.remove('panning');
    }
});

canvasContainer.addEventListener('mousemove', function(e) {
    if (isPanning) {
        const dx = e.clientX - panStartX;
        const dy = e.clientY - panStartY;
        panOffsetX += dx;
        panOffsetY += dy;
        panStartX = e.clientX;
        panStartY = e.clientY;
        applyTransform();
    }
});

canvasContainer.addEventListener('wheel', function(e) {
    e.preventDefault();
    const rect = canvasContainer.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    
    const zoomFactor = e.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP;
    const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, currentZoom + zoomFactor));
    
    const worldX = (mouseX - panOffsetX) / currentZoom;
    const worldY = (mouseY - panOffsetY) / currentZoom;
    
    panOffsetX = mouseX - worldX * newZoom;
    panOffsetY = mouseY - worldY * newZoom;
    
    currentZoom = newZoom;
    applyTransform();
    document.getElementById('zoom-display').textContent = 'Zoom: ' + Math.round(currentZoom * 100) + '%';
});

function createConnection(fromNode, fromPort, toNode, toPort) {
    if (fromNode === toNode) return;
    
    const existing = connections.find(c => 
        (c.from.node === fromNode && c.from.port === fromPort && c.to.node === toNode && c.to.port === toPort) ||
        (c.from.node === toNode && c.from.port === toPort && c.to.node === fromNode && c.to.port === fromPort)
    );
    
    if (!existing) {
        connections.push({
            from: { node: fromNode, port: fromPort },
            to: { node: toNode, port: toPort },
            description: '',
            enabled: true
        });
        updateConnections();
        updateStats();
        renderConnectionsList();
        autoSave();
    }
}

function deleteConnection(index) {
    connections.splice(index, 1);
    selectedConnection = null;
    updateConnections();
    updateStats();
    renderConnectionsList();
    showProperties();
    document.getElementById('selection').textContent = 'No selection';
    autoSave();
}

function updateConnections() {
    const svg = document.getElementById('svg-canvas');
    svg.innerHTML = '';

    for (let i = 0; i < connections.length; i++) {
        const conn = connections[i];
        const fromNodeData = nodes.find(n => n.id === conn.from.node);
        const toNodeData = nodes.find(n => n.id === conn.to.node);

        if (fromNodeData && toNodeData) {
            const fromEl = document.querySelector(`[data-node="${conn.from.node}"][data-port="${conn.from.port}"][data-type="output"]`);
            const toEl = document.querySelector(`[data-node="${conn.to.node}"][data-port="${conn.to.port}"][data-type="input"]`);
            
            if (fromEl && toEl) {
                const fromRect = fromEl.getBoundingClientRect();
                const toRect = toEl.getBoundingClientRect();
                const canvasRect = document.getElementById('canvas-container').getBoundingClientRect();
                
                const x1 = (fromRect.left + fromRect.width / 2 - canvasRect.left - panOffsetX) / currentZoom;
                const y1 = (fromRect.top + fromRect.height / 2 - canvasRect.top - panOffsetY) / currentZoom;
                const x2 = (toRect.left + toRect.width / 2 - canvasRect.left - panOffsetX) / currentZoom;
                const y2 = (toRect.top + toRect.height / 2 - canvasRect.top - panOffsetY) / currentZoom;

                const offset = Math.min(Math.abs(x2 - x1) / 3, 60);
                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', `M ${x1} ${y1} C ${x1 + offset} ${y1}, ${x2 - offset} ${y2}, ${x2} ${y2}`);
                path.setAttribute('class', 'connection-line' + (selectedConnection === i ? ' selected' : ''));
                path.setAttribute('data-index', i);
                path.style.cursor = 'pointer';
                path.addEventListener('click', function(e) {
                    e.stopPropagation();
                    selectedConnection = parseInt(this.getAttribute('data-index'));
                    selectedNode = null;
                    updateConnections();
                    showProperties();
                    document.getElementById('selection').textContent = 'Selected: Connection ' + (selectedConnection + 1);
                });
                svg.appendChild(path);
            }
        }
    }
}

function renderConnectionsList() {
    const list = document.getElementById('conn-list');
    if (!list) return;
    
    if (connections.length === 0) {
        list.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🔗</div><div>No connections</div></div>';
        return;
    }
    
    let html = '';
    for (let i = 0; i < connections.length; i++) {
        const conn = connections[i];
        const fromNode = nodes.find(n => n.id === conn.from.node);
        const toNode = nodes.find(n => n.id === conn.to.node);
        html += `<div class="conn-item">${fromNode ? fromNode.name : 'Unknown'} → ${toNode ? toNode.name : 'Unknown'} <button class="conn-delete" onclick="deleteConnection(${i})">×</button></div>`;
    }
    list.innerHTML = html;
}

function startConnection(e) {
    e.stopPropagation();
    const port = e.target;
    connectingFrom = {
        node: port.getAttribute('data-node'),
        port: port.getAttribute('data-port')
    };
    connectingPortType = port.getAttribute('data-type');
    
    const canvasRect = document.getElementById('canvas-container').getBoundingClientRect();
    const portRect = port.getBoundingClientRect();
    
    const x = (portRect.left + portRect.width/2 - canvasRect.left - panOffsetX) / currentZoom;
    const y = (portRect.top + portRect.height/2 - canvasRect.top - panOffsetY) / currentZoom;
    
    tempLine = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    tempLine.setAttribute('class', 'connection-line temp');
    tempLine.setAttribute('d', `M ${x} ${y} L ${x} ${y}`);
    document.getElementById('svg-canvas').appendChild(tempLine);
}

function updateTempLine(clientX, clientY) {
    if (!tempLine || !connectingFrom) return;
    
    const port = document.querySelector(`[data-node="${connectingFrom.node}"][data-port="${connectingFrom.port}"]`);
    if (!port) return;
    
    const canvasRect = document.getElementById('canvas-container').getBoundingClientRect();
    const portRect = port.getBoundingClientRect();
    
    const startX = (portRect.left + portRect.width / 2 - canvasRect.left - panOffsetX) / currentZoom;
    const startY = (portRect.top + portRect.height / 2 - canvasRect.top - panOffsetY) / currentZoom;
    const endX = (clientX - canvasRect.left - panOffsetX) / currentZoom;
    const endY = (clientY - canvasRect.top - panOffsetY) / currentZoom;
    
    tempLine.setAttribute('d', `M ${startX} ${startY} L ${endX} ${endY}`);
}

function removeTempLine() {
    if (tempLine) {
        tempLine.remove();
        tempLine = null;
    }
}

document.addEventListener('DOMContentLoaded', function() {
    document.addEventListener('mousedown', function(e) {
        if (e.target.classList.contains('port-circle')) {
            e.preventDefault();
            e.stopPropagation();
            startConnection(e);
        }
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Delete' && selectedNode) {
            deleteNode(selectedNode.id);
        } else if (e.key === 'Delete' && selectedConnection !== null) {
            deleteConnection(selectedConnection);
            selectedConnection = null;
        }
    });
});