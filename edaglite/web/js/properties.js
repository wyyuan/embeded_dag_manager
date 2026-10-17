function showProperties() {
    const panel = document.getElementById('props-panel');
    if (!panel) return;
    
    if (selectedConnection !== null) {
        const conn = connections[selectedConnection];
        const fromNode = nodes.find(n => n.id === conn.from.node);
        const toNode = nodes.find(n => n.id === conn.to.node);
        
        panel.innerHTML = `
            <div class="config-section">
                <div class="config-title">Connection Info</div>
                <div class="form-group">
                    <label class="form-label">ID</label>
                    <input type="text" class="form-input" value="Connection ${selectedConnection + 1}" disabled>
                </div>
                <div class="form-group">
                    <label class="form-label">From</label>
                    <input type="text" class="form-input" value="${fromNode ? fromNode.name + ' (' + conn.from.port + ')' : 'Unknown'}" disabled>
                </div>
                <div class="form-group">
                    <label class="form-label">To</label>
                    <input type="text" class="form-input" value="${toNode ? toNode.name + ' (' + conn.to.port + ')' : 'Unknown'}" disabled>
                </div>
                <div class="form-group">
                    <label class="form-label">Description</label>
                    <input type="text" class="form-input" value="${conn.description || ''}" onchange="updateConnection('description', this.value)" placeholder="Connection description...">
                </div>
                <div class="form-group">
                    <label class="form-label">Enabled</label>
                    <input type="checkbox" ${conn.enabled !== false ? 'checked' : ''} onchange="updateConnection('enabled', this.checked)" style="width: auto; margin: 0;">
                </div>
            </div>
            <div class="config-section">
                <button class="btn btn-danger" style="width: 100%;" onclick="deleteConnection(${selectedConnection}); selectedConnection = null; showProperties();">Delete Connection</button>
            </div>
        `;
        return;
    }
    
    if (selectedNode) {
        let inputsHtml = '';
        for (let i = 0; i < selectedNode.inputs.length; i++) {
            inputsHtml += `<div class="form-group"><input type="text" class="form-input" value="${selectedNode.inputs[i].name}" disabled></div>`;
        }

        let outputsHtml = '';
        for (let i = 0; i < selectedNode.outputs.length; i++) {
            outputsHtml += `<div class="form-group"><input type="text" class="form-input" value="${selectedNode.outputs[i].name}" disabled></div>`;
        }

        let customParamsHtml = '';
        if (!selectedNode.customParams) {
            selectedNode.customParams = [];
        }
        
        for (let i = 0; i < selectedNode.customParams.length; i++) {
            const param = selectedNode.customParams[i];
            customParamsHtml += renderCustomParam(param, i);
        }

        if (!customParamsHtml) {
            customParamsHtml = '<div style="font-size: 11px; color: var(--text-muted, #888); padding: 4px 2px;">This node has no configurable parameters</div>';
        }

        panel.innerHTML = `
            <div class="config-section">
                <div class="config-title">Node Info</div>
                <div class="form-group">
                    <label class="form-label">Name</label>
                    <input type="text" class="form-input" value="${selectedNode.name}" onchange="updateNode('name', this.value)">
                </div>
                <div class="form-group">
                    <label class="form-label">Description</label>
                    <input type="text" class="form-input" value="${selectedNode.description || ''}" onchange="updateNode('description', this.value)" placeholder="Description...">
                </div>
            </div>
            <div class="config-section">
                <div class="config-title">Inputs</div>
                ${inputsHtml}
            </div>
            <div class="config-section">
                <div class="config-title">Outputs</div>
                ${outputsHtml}
            </div>
            <div class="config-section">
                <div class="config-title">Parameters</div>
                ${customParamsHtml}
            </div>
            <div class="config-section" style="display: flex; gap: 6px;">
                <button class="btn btn-success" style="flex: 1;" onclick="runSingleNode(${selectedNode.id})">▶️ Run</button>
                <button class="btn btn-secondary" style="flex: 1;" onclick="openNodeCache(${selectedNode.id}, '${selectedNode.cacheName || selectedNode.type}')">📂 Cache</button>
                <button class="btn btn-danger" style="flex: 1;" onclick="deleteNode(${selectedNode.id})">🗑️ Delete</button>
            </div>
        `;
        return;
    }

    panel.innerHTML = '<div class="empty-state"><div class="empty-state-icon">👆</div><div>Select a node or connection</div></div>';
}

// Params are defined by the node's Python (register_node/type annotations); here the user
// only fills in values. Param name and type are read-only, with no UI to add, delete,
// rename, or retype them.
function renderCustomParam(param, index) {
    let valueInput = '';

    switch (param.type) {
        case 'number': {
            const numValue = (param.value === undefined || param.value === null || param.value === '')
                ? 0 : param.value;
            valueInput = `<input type="number" class="form-input" value="${numValue}" onchange="updateCustomParam(${index}, 'value', parseFloat(this.value))" step="any">`;
            break;
        }
        case 'select': {
            // Compatible with select params saved in legacy workspaces: only allow choosing among existing options
            let options = '';
            if (param.options && Array.isArray(param.options)) {
                for (let i = 0; i < param.options.length; i++) {
                    const selected = param.value === param.options[i] ? 'selected' : '';
                    options += `<option value="${param.options[i]}" ${selected}>${param.options[i]}</option>`;
                }
            }
            valueInput = `<select class="form-input" onchange="updateCustomParam(${index}, 'value', this.value)">${options}</select>`;
            break;
        }
        default:
            valueInput = `<input type="text" class="form-input" value="${param.value === undefined || param.value === null ? '' : param.value}" onchange="updateCustomParam(${index}, 'value', this.value)">`;
    }

    const descHtml = param.description
        ? `<div style="font-size: 10px; color: var(--text-muted, #999); margin: 2px 0 4px;">${param.description}</div>`
        : '';

    return `
        <div class="form-group" style="margin-bottom: 8px;">
            <label class="form-label" style="font-weight: 600;">${param.name}</label>
            ${descHtml}
            ${valueInput}
        </div>
    `;
}

function updateCustomParam(index, field, value) {
    if (!selectedNode || !selectedNode.customParams) return;

    // Only the value may be updated; name and type follow the node definition
    if (field !== 'value') return;

    selectedNode.customParams[index][field] = value;
    autoSave();
}

function updateConnection(prop, value) {
    if (selectedConnection !== null) {
        connections[selectedConnection][prop] = value;
        autoSave();
    }
}

function updateNode(prop, value) {
    if (selectedNode) {
        selectedNode[prop] = value;
        const el = document.getElementById(selectedNode.id);
        if (el && prop === 'name') {
            el.querySelector('.node-title').textContent = selectedNode.icon + ' ' + selectedNode.name;
        }
        autoSave();
    }
}

function updatePort(type, idx, field, value) {
    if (selectedNode) {
        const oldPortName = selectedNode[type][idx][field];
        
        selectedNode[type][idx][field] = value;
        
        if (field === 'name' && oldPortName !== value) {
            connections.forEach(conn => {
                const nodeKey = type === 'inputs' ? 'to' : 'from';
                const portKey = type === 'inputs' ? 'port' : 'port';
                
                if (conn[nodeKey].node === selectedNode.id && conn[nodeKey].port === oldPortName) {
                    conn[nodeKey].port = value;
                }
            });
        }
        
        renderNode(selectedNode);
        updateConnections();
        autoSave();
    }
}

function addPort(type) {
    if (selectedNode) {
        const count = selectedNode[type].length;
        selectedNode[type].push({ name: type === 'inputs' ? 'input_' + (count + 1) : 'output_' + (count + 1) });
        renderNode(selectedNode);
        showProperties();
        autoSave();
    }
}

function removePort(type, idx) {
    if (selectedNode) {
        selectedNode[type].splice(idx, 1);
        renderNode(selectedNode);
        updateConnections();
        showProperties();
        autoSave();
    }
}

function autoSave() {
    const data = { 
        nodes: nodes, 
        connections: connections, 
        savedAt: new Date().toISOString() 
    };
    localStorage.setItem('pipeline-editor-data', JSON.stringify(data));
}

function loadFromStorage() {
    const saved = localStorage.getItem('pipeline-editor-data');
    if (saved) {
        try {
            const data = JSON.parse(saved);
            nodes = data.nodes || [];
            connections = data.connections || [];
            syncNodeIdCounter();
            
            for (let i = 0; i < nodes.length; i++) {
                if (nodes[i].locked === undefined) {
                    const nodeType = nodeTypes.find(t => t.id === nodes[i].type);
                    nodes[i].locked = nodeType ? (nodeType.locked || false) : false;
                }
                syncNodeCustomParams(nodes[i]);
                renderNode(nodes[i]);
            }

            if (nodes.length > 0) {
                const minX = Math.min(...nodes.map(n => n.x));
                const maxX = Math.max(...nodes.map(n => n.x + 170));
                const minY = Math.min(...nodes.map(n => n.y));
                const maxY = Math.max(...nodes.map(n => n.y + 120));
                
                const canvasRect = document.getElementById('canvas-container').getBoundingClientRect();
                const centerX = (minX + maxX) / 2;
                const centerY = (minY + maxY) / 2;
                
                panOffsetX = canvasRect.width / 2 - centerX * currentZoom;
                panOffsetY = canvasRect.height / 2 - centerY * currentZoom;
                
                applyTransform();
            }
            
            setTimeout(() => {
                updateConnections();
            }, 0);
            
            updateStats();
            renderConnectionsList();
        } catch (e) {
            console.error('Failed to load from storage:', e);
        }
    }
}