import eel
import os
import sys
import json
import io
import shutil
import tempfile

from .pipeline import Pipeline, Context

# Global workspace directory set from command line
workspace_dir = None

# Max number of parent directory levels to traverse upward when searching for
# nodes.json (prevents accidentally matching high-level locations such as the user home)
_MAX_NODES_JSON_LEVELS = 8


def _find_nodes_json(start_dir):
    """Search for nodes.json along the ``workspace -> parent directory chain``,
    returning the absolute path of the first hit.

    The first stop is the workspace directory itself, so the old layout of
    "one nodes.json per workspace" keeps working (nearest first, backward
    compatible); when the workspace has none, the search continues up level by
    level to a project-level directory, letting multiple workspaces share the
    same node type palette definition. Returns None when the drive root is
    reached or the level limit is exceeded without a hit.
    """
    if not start_dir:
        return None
    cur = os.path.abspath(start_dir)
    for _ in range(_MAX_NODES_JSON_LEVELS + 1):
        candidate = os.path.join(cur, 'nodes.json')
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:  # reached the drive root
            break
        cur = parent
    return None


# Pure UI fields the overlay is allowed to provide (matched by node type name;
# ports and params always come from the Python registered class)
_OVERLAY_UI_KEYS = ("name", "icon", "group", "description")
_DEFAULT_ICON = "🧩"


def _load_overlay(workspace):
    """Load the optional nodes.json UI overlay, returning {node type name: UI config}.

    nodes.json is no longer the source of truth for ports/params; it may only
    provide UI metadata such as display name, icon, group and description; any
    extra inputs/outputs/params written into it are ignored. Returns an empty
    dict when the file does not exist or fails to parse (in which case all
    palette fields come from the Python registered classes).
    """
    path = _find_nodes_json(workspace)
    if not path:
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to load nodes.json overlay ({path}): {e}")
        return {}
    overlay = {}
    for item in data.get('nodes', []):
        nid = item.get('id')
        if nid:
            overlay[nid] = {k: item[k] for k in _OVERLAY_UI_KEYS if k in item}
    return overlay


def _build_node_types(workspace, use_overlay=True):
    """Build editor node palette data by reflecting ``Pipeline.NODE_REGISTRY``.

    The Python registered class is the single source of truth: the ports, params
    and description shown on the palette all come from the instantiated node
    object (both class-level declarations and dynamic additions in ``__init__``
    are reflected correctly); the display field priority is nodes.json overlay >
    ``register_node(...)`` metadata > defaults (class name / 🧩 / first line of
    the docstring). When ``use_overlay=False`` nodes.json is ignored entirely and
    all palette info comes from the registered classes -- in that case nodes.json
    does not need to exist at all.

    Instantiation uses a one-off Context with a temporary working directory, to
    avoid creating a cache directory under the real workspace just for opening
    the editor; a single node that fails to instantiate is skipped with a warning
    and does not affect the display of the remaining types.

    Returns:
        ``{"nodes": [ {id,name,icon,group,description,cache_name,
        inputs,outputs,params}, ... ]}``, in the same order as node registration;
        nodes is an empty list when there are no registered types.
    """
    overlay = _load_overlay(workspace) if use_overlay else {}
    result = {"nodes": []}

    if not Pipeline.NODE_REGISTRY:
        return result

    tmp_dir = tempfile.mkdtemp(prefix='node_palette_')
    try:
        probe_ctx = Context(tmp_dir)
        for type_name, node_cls in Pipeline.NODE_REGISTRY.items():
            try:
                inst = node_cls(probe_ctx)
            except Exception as e:
                print(f"[WARN] Skip node type '{type_name}' in palette "
                      f"(instantiation failed): {type(e).__name__}: {e}")
                continue

            doc_desc = ""
            if node_cls.__doc__:
                doc_desc = node_cls.__doc__.strip().splitlines()[0].strip()
            # Class-level metadata provided by register_node(name/icon/group/description=...)
            meta = getattr(node_cls, '_node_meta', {})
            default_desc = inst.description or meta.get("description") or doc_desc
            ui = overlay.get(type_name, {})

            result["nodes"].append({
                "id": type_name,
                "name": ui.get("name") or meta.get("name") or inst.name,
                "icon": ui.get("icon") or meta.get("icon") or _DEFAULT_ICON,
                "group": ui.get("group") or meta.get("group") or "",
                "description": ui.get("description") or default_desc,
                # Disk cache directory naming identifier cache/{frontend id}_{cache_name},
                # defaults to the class name; decoupled from the display name, the
                # frontend "open cache folder" must pass this value back
                "cache_name": inst.name,
                "inputs": [{"name": p.name, "description": p.description}
                           for p in inst.inputs],
                "outputs": [{"name": p.name, "description": p.description}
                            for p in inst.outputs],
                # type follows the nodes.json contract (int/float/string);
                # when the frontend creates a node it generates both the UI type
                # and the backend param_type from this
                "params": [{"name": p.name,
                            "description": p.description,
                            "type": p.param_type,
                            "value": p.value}
                           for p in inst.params],
            })
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    extra = [k for k in overlay if k not in Pipeline.NODE_REGISTRY]
    if extra:
        print(f"[WARN] nodes.json overlay contains unregistered node types, ignored: {extra}")
    return result


def _export_overlay_scaffold(target_path, workspace):
    """Export a pure UI overlay nodes.json from the current registry (ignoring any existing overlay).

    The exported content contains only id/name/icon/group/description -- ports and
    params always come from the Python registered classes, so the scaffold does
    not include them. Returns the number of exported node types.
    Whether to skip an already-existing target file is decided by the caller; this
    function does not guard against overwriting.
    """
    data = _build_node_types(workspace, use_overlay=False)
    scaffold = {"nodes": []}
    for n in data["nodes"]:
        item = {"id": n["id"], "name": n["name"], "icon": n["icon"]}
        if n.get("group"):
            item["group"] = n["group"]
        if n.get("description"):
            item["description"] = n["description"]
        scaffold["nodes"].append(item)

    target_path = os.path.abspath(target_path)
    parent = os.path.dirname(target_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target_path, 'w', encoding='utf-8') as f:
        json.dump(scaffold, f, ensure_ascii=False, indent=2)
    return len(scaffold["nodes"])


def run_viewer(host='localhost', port=8080, open_browser=False, workspace=None,
               use_overlay=True, generate_nodes_json=None):
    """Initialize and start the pipeline viewer web UI.

    Args:
        use_overlay: whether to load the nodes.json UI overlay; when False the
            palette metadata comes entirely from the Python registered classes
            (for projects that do not use nodes.json at all).
        generate_nodes_json: export the reflection result of the registered
            classes as a nodes.json scaffold before starting. None means no
            export; an empty string means export to ``<workspace>/nodes.json``;
            a non-empty string is used as the target path. An existing target is
            not overwritten.
    """
    global workspace_dir
    workspace_dir = workspace

    # Optional: dynamically generate a nodes.json scaffold at startup (only when the target does not exist)
    if generate_nodes_json is not None:
        target = generate_nodes_json or (
            os.path.join(workspace, 'nodes.json') if workspace else None)
        if not target:
            print("[WARN] --generate-nodes-json requires an explicit path (no workspace specified), skipped")
        elif os.path.exists(target):
            print(f"[INFO] nodes.json already exists, keeping it without overwriting: {os.path.abspath(target)}")
        else:
            count = _export_overlay_scaffold(target, workspace)
            print(f"[INFO] Generated nodes.json scaffold from registered classes ({count} type(s)): "
                  f"{os.path.abspath(target)}")
    
    # Get the directory where web files are located
    package_dir = os.path.dirname(os.path.abspath(__file__))
    web_dir = os.path.join(os.path.dirname(package_dir), 'web')
    
    # If web directory doesn't exist in expected place, try alternate location
    if not os.path.exists(web_dir):
        web_dir = os.path.join(package_dir, 'web')
    
    # Initialize: specify HTML folder
    eel.init(web_dir)

    # Give HTML access to this Python function
    @eel.expose
    def python_add(a, b):
        print(f"Python received: {a} + {b}")
        return a + b

    @eel.expose
    def get_node_types():
        """Build the palette by reflecting registered Python node classes; nodes.json only serves as a UI overlay."""
        print("=== get_node_types called ===")
        try:
            data = _build_node_types(workspace_dir, use_overlay=use_overlay)
            count = len(data.get('nodes', []))
            print(f"Reflected {count} registered node type(s) from NODE_REGISTRY")
            return {'success': True, 'data': data}
        except Exception as e:
            import traceback
            print(f"Failed to build node types: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            return {'success': False, 'data': None}

    @eel.expose
    def get_saved_pipeline():
        """Get saved pipeline from workspace/workspace.json if it exists."""
        print("=== get_saved_pipeline called ===")
        
        if workspace_dir and os.path.exists(os.path.join(workspace_dir, 'workspace.json')):
            try:
                pipeline_path = os.path.join(workspace_dir, 'workspace.json')
                with open(pipeline_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"Loaded saved pipeline from workspace: {pipeline_path}")
                    return {'success': True, 'data': data}
            except Exception as e:
                print(f"Failed to load workspace.json from workspace: {e}")
        
        print("No saved workspace.json found")
        return {'success': False, 'data': None}

    @eel.expose
    def save_pipeline(pipeline_data):
        """Save pipeline directly to workspace/workspace.json."""
        print("=== save_pipeline called ===")
        
        if not workspace_dir:
            print("No workspace directory specified, cannot save directly")
            return {'success': False, 'error': 'No workspace directory specified'}
        
        try:
            # In some eel versions, the data might be wrapped in an extra list
            if isinstance(pipeline_data, list) and len(pipeline_data) == 1 and isinstance(pipeline_data[0], dict):
                pipeline_data = pipeline_data[0]
            
            nodes_count = len(pipeline_data.get('nodes', []))
            conn_count = len(pipeline_data.get('connections', []))
            pipeline_path = os.path.join(workspace_dir, 'workspace.json')
            with open(pipeline_path, 'w', encoding='utf-8') as f:
                json.dump(pipeline_data, f, ensure_ascii=False, indent=2)
            print(f"Saved pipeline to: {pipeline_path} ({nodes_count} nodes, {conn_count} connections)")
            return {'success': True, 'path': pipeline_path}
        except Exception as e:
            import traceback
            error_msg = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
            print(f"Failed to save pipeline: {error_msg}")
            return {'success': False, 'error': error_msg}

    @eel.expose
    def run_pipeline(pipeline_data):
        """Run Pipeline"""
        print("=== run_pipeline called ===")
        
        try:
            # Use provided workspace if available, otherwise temp
            if workspace_dir:
                use_workspace = workspace_dir
                print(f"Using provided workspace: {use_workspace}")
            else:
                import tempfile
                use_workspace = tempfile.mkdtemp(prefix='pipeline_')
                print(f"Created temp workspace: {use_workspace}")
            
            pipeline_path = os.path.join(use_workspace, 'workspace.json')
            with open(pipeline_path, 'w', encoding='utf-8') as f:
                json.dump(pipeline_data, f, ensure_ascii=False, indent=2)
            
            print("Loading pipeline...")
            pipeline = Pipeline.load_from_json(pipeline_path, use_workspace)
            pipeline.force = True
            print("Pipeline loaded, stages:", len(pipeline.stages))
            
            pipeline.run()
            
            import time
            time.sleep(0.1)
            
            if os.path.exists(pipeline.log_file):
                with open(pipeline.log_file, 'r', encoding='utf-8') as f:
                    output = f.read()
            else:
                output = "Log file not found"
            
            print("=== run_pipeline finished ===")
            return {'success': True, 'output': output}
        
        except Exception as e:
            import traceback
            error_msg = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
            print(f"Pipeline error: {error_msg}")
            return {'success': False, 'error': error_msg}

    @eel.expose
    def run_single_node(pipeline_data, node_id):
        """Run a single node by its frontend ID"""
        print(f"=== run_single_node called for node: {node_id} ===")
        
        try:
            if workspace_dir:
                use_workspace = workspace_dir
                print(f"Using provided workspace: {use_workspace}")
            else:
                import tempfile
                use_workspace = tempfile.mkdtemp(prefix='pipeline_')
                print(f"Created temp workspace: {use_workspace}")
            
            pipeline_path = os.path.join(use_workspace, 'workspace.json')
            with open(pipeline_path, 'w', encoding='utf-8') as f:
                json.dump(pipeline_data, f, ensure_ascii=False, indent=2)
            
            print("Loading pipeline...")
            pipeline = Pipeline.load_from_json(pipeline_path, use_workspace)
            pipeline.force = True
            print(f"Pipeline loaded, stages: {len(pipeline.stages)}")
            
            pipeline.run_node_by_frontend_id(node_id)
            
            import time
            time.sleep(0.1)
            
            if os.path.exists(pipeline.log_file):
                with open(pipeline.log_file, 'r', encoding='utf-8') as f:
                    output = f.read()
            else:
                output = "Log file not found"
            
            print("=== run_single_node finished ===")
            return {'success': True, 'output': output}
        
        except Exception as e:
            import traceback
            error_msg = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
            print(f"Single node run error: {error_msg}")
            return {'success': False, 'error': error_msg}

    @eel.expose
    def open_node_cache_folder(node_id, folder_name):
        """Open the cache folder for a specific node in file explorer.

        ``folder_name`` is the disk naming identifier of the node type (the
        cache_name in the palette data, defaulting to the class name); the display
        name, which can be overridden by register_node/nodes.json, must not be
        used, otherwise the wrong cache directory would be located.
        """
        print(f"=== open_node_cache_folder called for node: {node_id}_{folder_name} ===")
        if not workspace_dir:
            return {'success': False, 'error': 'No workspace directory'}

        import subprocess
        cache_path = os.path.join(workspace_dir, 'cache', f"{node_id}_{folder_name}")
        if not os.path.exists(cache_path):
            os.makedirs(cache_path, exist_ok=True)
            print(f"Created cache folder: {cache_path}")

        subprocess.Popen(['explorer', os.path.normpath(cache_path)])
        print(f"Opened cache folder: {cache_path}")
        return {'success': True}

    # Start the application, use Bottle server mode, keep blocking
    mode = 'default' if open_browser else 'none'
    if workspace_dir:
        print(f"Workspace directory: {workspace_dir}")
        if use_overlay:
            found_nodes = _find_nodes_json(workspace_dir)
            if found_nodes:
                print(f"Found nodes.json overlay: {found_nodes}")
        else:
            print("nodes.json overlay disabled (--no-overlay); palette metadata comes only from registered classes")
    print(f"Starting eel server on {host}:{port}...")
    eel.start("index.html", size=(1200, 800), mode=mode, host=host, port=port, block=True)


def main():
    """Command-line entry point for the pipeline viewer."""
    import argparse
    parser = argparse.ArgumentParser(description='Start pipeline viewer web UI')
    parser.add_argument('--host', default='localhost', help='Host to bind to (default: localhost)')
    parser.add_argument('--port', '-p', type=int, default=8080, help='Port to listen on (default: 8080)')
    parser.add_argument('--open', '-o', action='store_true', help='Open browser automatically')
    parser.add_argument('--workspace', '-w', help='Workspace directory (optional)')
    parser.add_argument('--no-overlay', action='store_true',
                        help='Ignore nodes.json entirely; palette metadata comes only from registered classes')
    parser.add_argument('--generate-nodes-json', nargs='?', const='', default=None,
                        metavar='PATH',
                        help='Export a nodes.json UI-overlay scaffold from registered classes '
                             'before starting (default target: <workspace>/nodes.json); '
                             'an existing file is never overwritten')
    args = parser.parse_args()

    workspace = None
    if args.workspace:
        workspace = os.path.abspath(args.workspace)
        if not os.path.exists(workspace):
            print(f"[WARN] Workspace directory does not exist: {workspace}")

    run_viewer(host=args.host, port=args.port, open_browser=args.open, workspace=workspace,
               use_overlay=not args.no_overlay,
               generate_nodes_json=args.generate_nodes_json)


if __name__ == "__main__":
    main()
