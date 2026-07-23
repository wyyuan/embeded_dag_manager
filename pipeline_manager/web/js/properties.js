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

        const addParamBtn = '<button class="btn btn-secondary" style="width: 100%; font-size: 11px; padding: 6px;" onclick="showAddParamDialog()">+ Add Custom Parameter</button>';

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
                <div class="config-title">Custom Parameters</div>
                ${customParamsHtml}
                ${addParamBtn}
            </div>
            <div class="config-section" style="display: flex; gap: 6px;">
                <button class="btn btn-success" style="flex: 1;" onclick="runSingleNode(${selectedNode.id})">▶️ Run</button>
                <button class="btn btn-secondary" style="flex: 1;" onclick="openNodeCache(${selectedNode.id}, '${selectedNode.name}')">📂 Cache</button>
                <button class="btn btn-danger" style="flex: 1;" onclick="deleteNode(${selectedNode.id})">🗑️ Delete</button>
            </div>
        `;
        return;
    }

    panel.innerHTML = '<div class="empty-state"><div class="empty-state-icon">👆</div><div>Select a node or connection</div></div>';
}

function renderCustomParam(param, index) {
    let valueInput = '';
    
    switch (param.type) {
        case 'number':
            valueInput = `<input type="number" class="form-input" value="${param.value || 0}" onchange="updateCustomParam(${index}, 'value', parseFloat(this.value))" step="any">`;
            break;
        case 'string':
            valueInput = `<input type="text" class="form-input" value="${param.value || ''}" onchange="updateCustomParam(${index}, 'value', this.value)">`;
            break;
        case 'select':
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
    
    return `
        <div class="form-group" style="border: 1px solid var(--border-color); padding: 8px; border-radius: 4px; margin-bottom: 8px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <input type="text" class="form-input" value="${param.name}" onchange="updateCustomParam(${index}, 'name', this.value)" style="width: calc(100% - 60px); font-weight: 600;" placeholder="Param name">
                <button class="btn btn-danger" style="padding: 4px 8px; font-size: 10px;" onclick="removeCustomParam(${index})">×</button>
            </div>
            <div style="display: flex; gap: 6px; align-items: center;">
                <select class="form-input" onchange="updateCustomParamType(${index}, this.value)" style="width: 80px;">
                    <option value="string" ${param.type === 'string' ? 'selected' : ''}>String</option>
                    <option value="number" ${param.type === 'number' ? 'selected' : ''}>Number</option>
                    <option value="select" ${param.type === 'select' ? 'selected' : ''}>Select</option>
                </select>
                ${valueInput}
            </div>
            ${param.type === 'select' ? `
                <div style="margin-top: 6px;">
                    <input type="text" class="form-input" value="${(param.options || []).join(', ')}" onchange="updateCustomParamOptions(${index}, this.value)" placeholder="Options (comma separated)" style="font-size: 11px;">
                </div>
            ` : ''}
        </div>
    `;
}

function showAddParamDialog() {
    if (!selectedNode) return;
    
    if (!selectedNode.customParams) {
        selectedNode.customParams = [];
    }
    
    selectedNode.customParams.push({
        name: 'param_' + (selectedNode.customParams.length + 1),
        type: 'string',
        value: '',
        options: []
    });
    
    showProperties();
    autoSave();
}

function updateCustomParam(index, field, value) {
    if (!selectedNode || !selectedNode.customParams) return;
    
    selectedNode.customParams[index][field] = value;
    autoSave();
}

function updateCustomParamType(index, newType) {
    if (!selectedNode || !selectedNode.customParams) return;
    
    const param = selectedNode.customParams[index];
    param.type = newType;
    
    switch (newType) {
        case 'number':
            param.value = 0;
            delete param.options;
            break;
        case 'string':
            param.value = '';
            delete param.options;
            break;
        case 'select':
            param.value = '';
            param.options = ['option1', 'option2'];
            break;
    }
    
    showProperties();
    autoSave();
}

function updateCustomParamOptions(index, optionsStr) {
    if (!selectedNode || !selectedNode.customParams) return;
    
    const options = optionsStr.split(',').map(o => o.trim()).filter(o => o.length > 0);
    selectedNode.customParams[index].options = options;
    
    if (options.length > 0 && !options.includes(selectedNode.customParams[index].value)) {
        selectedNode.customParams[index].value = options[0];
    }
    
    showProperties();
    autoSave();
}

function removeCustomParam(index) {
    if (!selectedNode || !selectedNode.customParams) return;
    
    selectedNode.customParams.splice(index, 1);
    showProperties();
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
                if (!nodes[i].customParams) {
                    nodes[i].customParams = [];
                }
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