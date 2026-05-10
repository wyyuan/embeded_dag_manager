let nodes = [];
let connections = [];
let selectedNode = null;
let selectedConnection = null;
let nodeTypes = [];

let currentZoom = 1;
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 2;
const ZOOM_STEP = 0.1;

let isPanning = false;
let panStartX = 0;
let panStartY = 0;
let panOffsetX = 5000;
let panOffsetY = 5000;

let leftSidebarWidth = 220;
let rightSidebarWidth = 320;
let isResizing = false;
let resizeTarget = null;
let resizeStartX = 0;
let resizeStartWidth = 0;

function loadNodeTypes() {
    return new Promise((resolve, reject) => {
        fetch('config/nodes.json')
            .then(response => response.json())
            .then(data => {
                nodeTypes = data.nodes;
                renderNodeTypes();
                resolve();
            })
            .catch(error => {
                console.error('Failed to load node types:', error);
                nodeTypes = [
                    { id: 'DataLoader', name: 'DataLoader', icon: '📥', description: '', inputs: [], outputs: [{name: 'data'}] },
                    { id: 'Processor', name: 'Processor', icon: '⚙️', description: '', inputs: [{name: 'input'}], outputs: [{name: 'output'}] },
                    { id: 'Transformer', name: 'Transformer', icon: '🔄', description: '', inputs: [{name: 'input'}], outputs: [{name: 'output'}] },
                    { id: 'Filter', name: 'Filter', icon: '🔍', description: '', inputs: [{name: 'input'}], outputs: [{name: 'output'}] },
                    { id: 'Aggregator', name: 'Aggregator', icon: '📊', description: '', inputs: [{name: 'input'}], outputs: [{name: 'output'}] },
                    { id: 'Exporter', name: 'Exporter', icon: '📤', description: '', inputs: [{name: 'data'}], outputs: [] },
                    { id: 'CustomNode', name: 'Custom', icon: '✨', description: '', inputs: [{name: 'input'}], outputs: [{name: 'output'}] }
                ];
                renderNodeTypes();
                resolve();
            });
    });
}

function renderNodeTypes() {
    const container = document.getElementById('node-types-container');
    if (!container) return;
    
    let html = '';
    for (let i = 0; i < nodeTypes.length; i++) {
        const nodeType = nodeTypes[i];
        html += `<div class="toolbox-item" onclick="createNode('${nodeType.id}', '${nodeType.name}', '${nodeType.icon}')">${nodeType.icon} ${nodeType.name}</div>`;
    }
    container.innerHTML = html;
}

function createNode(typeId, name, icon) {
    const nodeType = nodeTypes.find(t => t.id === typeId);
    if (!nodeType) return;
    
    const id = 'node-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
    const canvasRect = document.getElementById('canvas-container').getBoundingClientRect();
    
    const centerX = (canvasRect.width / 2 - panOffsetX) / currentZoom;
    const centerY = (canvasRect.height / 2 - panOffsetY) / currentZoom;
    
    const node = {
        id: id,
        type: typeId,
        name: name,
        icon: icon,
        description: nodeType.description || '',
        x: centerX - 85,
        y: centerY - 45,
        inputs: JSON.parse(JSON.stringify(nodeType.inputs)),
        outputs: JSON.parse(JSON.stringify(nodeType.outputs)),
        customParams: []
    };
    
    nodes.push(node);
    renderNode(node);
    selectNode(id);
    updateStats();
    autoSave();
}

function renderNode(node) {
    const existing = document.getElementById(node.id);
    if (existing) existing.remove();

    const div = document.createElement('div');
    div.id = node.id;
    div.className = 'node' + (selectedNode && selectedNode.id === node.id ? ' selected' : '');
    div.style.left = node.x + 'px';
    div.style.top = node.y + 'px';

    let inputsHtml = '';
    for (let i = 0; i < node.inputs.length; i++) {
        inputsHtml += `<div class="port port-input"><div class="port-circle" data-node="${node.id}" data-port="${node.inputs[i].name}" data-type="input"></div><div class="port-name">${node.inputs[i].name}</div></div>`;
    }

    let outputsHtml = '';
    for (let i = 0; i < node.outputs.length; i++) {
        outputsHtml += `<div class="port port-output"><div class="port-name">${node.outputs[i].name}</div><div class="port-circle" data-node="${node.id}" data-port="${node.outputs[i].name}" data-type="output"></div></div>`;
    }

    div.innerHTML = `<div class="node-header"><div class="node-title">${node.icon} ${node.name}</div><button class="node-delete" onclick="event.stopPropagation(); deleteNode('${node.id}')">×</button></div><div class="node-body"><div class="port-section"><div class="port-section-title">Inputs</div>${inputsHtml}</div><div class="port-section"><div class="port-section-title">Outputs</div>${outputsHtml}</div></div>`;

    document.getElementById('canvas').appendChild(div);

    div.addEventListener('mousedown', function(e) {
        if (!e.target.classList.contains('port-circle')) {
            selectNode(node.id);
            startDrag(e, node.id);
        }
    });
}

function selectNode(id) {
    selectedConnection = null;
    selectedNode = nodes.find(n => n.id === id);
    
    const allNodes = document.querySelectorAll('.node');
    for (let i = 0; i < allNodes.length; i++) {
        allNodes[i].classList.remove('selected');
    }
    
    const selectedEl = document.getElementById(id);
    if (selectedEl) {
        selectedEl.classList.add('selected');
    }
    
    showProperties();
    
    if (selectedConnection !== null) {
        document.getElementById('selection').textContent = 'Selected: Connection ' + (selectedConnection + 1);
    } else if (selectedNode) {
        document.getElementById('selection').textContent = 'Selected: ' + selectedNode.name;
    } else {
        document.getElementById('selection').textContent = 'No selection';
    }
}

function deleteNode(id) {
    connections = connections.filter(c => c.from.node !== id && c.to.node !== id);
    nodes = nodes.filter(n => n.id !== id);
    
    const el = document.getElementById(id);
    if (el) el.remove();
    
    if (selectedNode && selectedNode.id === id) {
        selectedNode = null;
    }
    
    updateConnections();
    updateStats();
    showProperties();
    renderConnectionsList();
    document.getElementById('selection').textContent = 'No selection';
    autoSave();
}

function updateStats() {
    document.getElementById('node-count').textContent = nodes.length;
    document.getElementById('conn-count').textContent = connections.length;
}

function applyTransform() {
    const wrapper = document.getElementById('canvas-wrapper');
    wrapper.style.transform = `translate(${panOffsetX}px, ${panOffsetY}px) scale(${currentZoom})`;
}

function isNightTime() {
    const hour = new Date().getHours();
    return hour >= 19 || hour < 7;
}

function setTheme(isDark) {
    const themeToggle = document.querySelector('.theme-toggle');
    if (isDark) {
        document.body.classList.add('theme-dark');
        document.body.classList.remove('theme-light');
        themeToggle.textContent = '🌙';
        themeToggle.title = 'Switch to Light Mode';
    } else {
        document.body.classList.remove('theme-dark');
        document.body.classList.add('theme-light');
        themeToggle.textContent = '☀️';
        themeToggle.title = 'Switch to Dark Mode';
    }
    updateConnections();
}

function toggleTheme() {
    const isDark = document.body.classList.contains('theme-dark');
    setTheme(!isDark);
}

function initResizeHandlers() {
    const leftHandle = document.getElementById('resize-handle-left');
    const rightHandle = document.getElementById('resize-handle-right');
    
    leftHandle.addEventListener('mousedown', function(e) {
        isResizing = true;
        resizeTarget = 'left';
        resizeStartX = e.clientX;
        resizeStartWidth = leftSidebarWidth;
        leftHandle.classList.add('active');
        document.body.style.cursor = 'ew-resize';
        e.preventDefault();
    });
    
    rightHandle.addEventListener('mousedown', function(e) {
        isResizing = true;
        resizeTarget = 'right';
        resizeStartX = e.clientX;
        resizeStartWidth = rightSidebarWidth;
        rightHandle.classList.add('active');
        document.body.style.cursor = 'ew-resize';
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', function(e) {
        if (!isResizing) return;
        
        const delta = e.clientX - resizeStartX;
        
        if (resizeTarget === 'left') {
            const newWidth = Math.max(150, Math.min(400, resizeStartWidth + delta));
            leftSidebarWidth = newWidth;
            document.getElementById('sidebar-left').style.width = newWidth + 'px';
        } else {
            const newWidth = Math.max(200, Math.min(500, resizeStartWidth - delta));
            rightSidebarWidth = newWidth;
            document.getElementById('sidebar-right').style.width = newWidth + 'px';
        }
        
        updateCanvasPosition();
    });
    
    document.addEventListener('mouseup', function() {
        if (isResizing) {
            isResizing = false;
            document.getElementById('resize-handle-left').classList.remove('active');
            document.getElementById('resize-handle-right').classList.remove('active');
            document.body.style.cursor = '';
            updateCanvasPosition();
        }
    });
}

function updateCanvasPosition() {
    const canvas = document.getElementById('canvas-container');
    const outputPanel = document.getElementById('output-panel');
    const outputResizeHandle = document.getElementById('output-resize-handle');
    
    canvas.style.left = leftSidebarWidth + 'px';
    canvas.style.right = rightSidebarWidth + 'px';
    outputPanel.style.left = leftSidebarWidth + 'px';
    outputPanel.style.right = rightSidebarWidth + 'px';
    outputResizeHandle.style.left = leftSidebarWidth + 'px';
    outputResizeHandle.style.right = rightSidebarWidth + 'px';
}

function savePipeline() {
    const data = {
        nodes: nodes,
        connections: connections,
        savedAt: new Date().toISOString()
    };
    
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'pipeline.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function loadPipeline() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = function(e) {
        const file = e.target.files[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = function(event) {
                try {
                    const data = JSON.parse(event.target.result);
                    nodes = data.nodes || [];
                    connections = data.connections || [];
                    
                    const allNodes = document.querySelectorAll('.node');
                    for (let i = 0; i < allNodes.length; i++) {
                        allNodes[i].remove();
                    }
                    
                    for (let i = 0; i < nodes.length; i++) {
                        renderNode(nodes[i]);
                    }
                    
                    updateConnections();
                    updateStats();
                    renderConnectionsList();
                    autoSave();
                } catch (e) {
                    alert('Failed to load pipeline: ' + e.message);
                }
            };
            reader.readAsText(file);
        }
    };
    input.click();
}

function clearCanvas() {
    if (confirm('Clear all?')) {
        nodes = [];
        connections = [];
        selectedNode = null;
        selectedConnection = null;
        const allNodes = document.querySelectorAll('.node');
        for (let i = 0; i < allNodes.length; i++) {
            allNodes[i].remove();
        }
        document.getElementById('svg-canvas').innerHTML = '';
        document.getElementById('selection').textContent = 'No selection';
        updateStats();
        renderConnectionsList();
        showProperties();
        autoSave();
    }
}

function layoutNodes() {
    if (nodes.length === 0) return;
    
    const cols = 4;
    const spacingX = 250;
    const spacingY = 200;
    const startX = 100;
    const startY = 100;
    
    for (let i = 0; i < nodes.length; i++) {
        const col = i % cols;
        const row = Math.floor(i / cols);
        nodes[i].x = startX + col * spacingX;
        nodes[i].y = startY + row * spacingY;
        renderNode(nodes[i]);
    }
    
    updateConnections();
    
    const centerX = startX + (cols - 1) * spacingX / 2 + 85;
    const centerY = startY + Math.floor((nodes.length - 1) / cols) * spacingY / 2 + 45;
    
    const canvasContainer = document.getElementById('canvas-container');
    const canvasWidth = canvasContainer.offsetWidth;
    const canvasHeight = canvasContainer.offsetHeight;
    
    panOffsetX = canvasWidth / 2 - centerX * currentZoom;
    panOffsetY = canvasHeight / 2 - centerY * currentZoom;
    
    applyTransform();
    autoSave();
}

function addLog(message, type = 'info') {
    const outputContent = document.getElementById('output-content');
    const timestamp = new Date().toLocaleTimeString('zh-CN');
    const typeClass = `log-${type}`;
    
    const logLine = document.createElement('div');
    logLine.className = typeClass;
    logLine.innerHTML = `<span class="log-timestamp">[${timestamp}]</span> ${message}`;
    
    outputContent.appendChild(logLine);
    outputContent.scrollTop = outputContent.scrollHeight;
}

function addLogRaw(message) {
    // 添加原始输出，与终端完全一致，不添加额外时间戳
    const outputContent = document.getElementById('output-content');
    
    if (!outputContent) {
        return;
    }
    
    const logLine = document.createElement('div');
    logLine.className = 'log-raw';
    
    // 根据日志内容设置颜色
    if (message.includes('[ERROR]') || message.includes('Error:')) {
        logLine.className += ' log-error';
    } else if (message.includes('[DONE]')) {
        logLine.className += ' log-success';
    } else if (message.includes('[WARN]')) {
        logLine.className += ' log-warning';
    } else if (message.includes('[EXEC]')) {
        logLine.className += ' log-exec';
    } else if (message.includes('[INFO]')) {
        logLine.className += ' log-info';
    }
    
    logLine.textContent = message;
    
    outputContent.appendChild(logLine);
    outputContent.scrollTop = outputContent.scrollHeight;
}

function clearLog() {
    const outputContent = document.getElementById('output-content');
    outputContent.innerHTML = '';
    addLog('Log cleared', 'info');
}

let isOutputCollapsed = false;
const DEFAULT_OUTPUT_HEIGHT = 150;
const MIN_OUTPUT_HEIGHT = 50;

function toggleOutput() {
    const panel = document.getElementById('output-panel');
    const handle = document.getElementById('output-resize-handle');
    const btnCollapse = document.getElementById('btn-collapse');
    
    isOutputCollapsed = !isOutputCollapsed;
    
    if (isOutputCollapsed) {
        panel.classList.add('collapsed');
        btnCollapse.textContent = '▲';
    } else {
        panel.classList.remove('collapsed');
        btnCollapse.textContent = '▼';
    }
    
    updateResizeHandlePosition();
}

function updateResizeHandlePosition() {
    const panel = document.getElementById('output-panel');
    const handle = document.getElementById('output-resize-handle');
    const canvasContainer = document.getElementById('canvas-container');
    
    if (isOutputCollapsed) {
        handle.style.bottom = (26 + 36) + 'px';
        canvasContainer.style.bottom = (26 + 36) + 'px';
    } else {
        const totalHeight = 26 + panel.offsetHeight;
        handle.style.bottom = totalHeight + 'px';
        canvasContainer.style.bottom = totalHeight + 'px';
    }
}

let isResizingOutput = false;
let outputResizeStartY = 0;
let outputResizeStartHeight = 0;

function initOutputResize() {
    const handle = document.getElementById('output-resize-handle');
    const panel = document.getElementById('output-panel');
    
    handle.addEventListener('mousedown', function(e) {
        // 如果是收缩状态，不允许拖动
        if (isOutputCollapsed) {
            return;
        }
        
        isResizingOutput = true;
        handle.classList.add('dragging');
        outputResizeStartY = e.clientY;
        outputResizeStartHeight = panel.offsetHeight;
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', function(e) {
        if (!isResizingOutput) return;
        
        const deltaY = outputResizeStartY - e.clientY;
        let newHeight = outputResizeStartHeight + deltaY;
        
        newHeight = Math.max(MIN_OUTPUT_HEIGHT, newHeight);
        newHeight = Math.min(400, newHeight);
        
        panel.style.height = newHeight + 'px';
        updateResizeHandlePosition();
    });
    
    document.addEventListener('mouseup', function() {
        if (isResizingOutput) {
            isResizingOutput = false;
            handle.classList.remove('dragging');
        }
    });
    
    const outputHeader = document.getElementById('output-header');
    outputHeader.addEventListener('dblclick', function() {
        const btnCollapse = document.getElementById('btn-collapse');
        if (isOutputCollapsed) {
            panel.style.height = DEFAULT_OUTPUT_HEIGHT + 'px';
            isOutputCollapsed = false;
            panel.classList.remove('collapsed');
            btnCollapse.textContent = '▼';
        } else {
            isOutputCollapsed = true;
            panel.classList.add('collapsed');
            btnCollapse.textContent = '▲';
        }
        updateResizeHandlePosition();
    });
}

function runPipeline() {
    const statusBar = document.getElementById('status-bar');
    const statusDot = statusBar.querySelector('.status-dot');
    
    const data = {
        nodes: nodes,
        connections: connections,
        savedAt: new Date().toISOString()
    };
    
    statusDot.style.background = '#ed8936';
    statusBar.querySelector('.status-item:first-child span:last-child').textContent = 'Running...';
    
    addLogRaw('Starting pipeline...');
    
    if (window.eel) {
        eel.run_pipeline(data)(
            function success(result) {
                console.log('Received result:', result);
                
                if (result.success) {
                    statusDot.style.background = '#48bb78';
                    statusBar.querySelector('.status-item:first-child span:last-child').textContent = 'Completed';
                    
                    addLogRaw('Pipeline completed successfully!');
                    
                    if (result.output) {
                        const lines = result.output.split('\n');
                        for (const line of lines) {
                            if (line.trim()) {
                                addLogRaw(line);
                            }
                        }
                    }
                } else {
                    statusDot.style.background = '#f56565';
                    statusBar.querySelector('.status-item:first-child span:last-child').textContent = 'Error';
                    addLogRaw('Error: ' + (result.error || 'Unknown error'));
                }
                
                setTimeout(() => {
                    statusDot.style.background = '#48bb78';
                    statusBar.querySelector('.status-item:first-child span:last-child').textContent = 'Ready';
                }, 3000);
            },
            function error(error) {
                console.error('Eel call failed:', error);
                addLogRaw('Eel call failed: ' + error);
                statusDot.style.background = '#f56565';
                statusBar.querySelector('.status-item:first-child span:last-child').textContent = 'Error';
            }
        );
    } else {
        addLogRaw('eel not available - running in standalone mode');
        statusDot.style.background = '#48bb78';
        statusBar.querySelector('.status-item:first-child span:last-child').textContent = 'Ready';
    }
}

document.addEventListener('DOMContentLoaded', function() {
    setTheme(isNightTime());
    loadNodeTypes().then(() => {
        loadFromStorage();
    });
    
    applyTransform();
    updateStats();
    initResizeHandlers();
    initOutputResize();
    updateCanvasPosition();
});