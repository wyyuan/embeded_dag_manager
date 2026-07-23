import eel
import os
import sys
import json
import io

from .pipeline import Pipeline

# Global workspace directory set from command line
workspace_dir = None


def run_viewer(host='localhost', port=8080, open_browser=False, workspace=None):
    """Initialize and start the pipeline viewer web UI."""
    global workspace_dir
    workspace_dir = workspace
    
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
        """Get node types from workspace/nodes.json or fallback to default."""
        print("=== get_node_types called ===")
        
        if workspace_dir and os.path.exists(os.path.join(workspace_dir, 'nodes.json')):
            try:
                nodes_path = os.path.join(workspace_dir, 'nodes.json')
                with open(nodes_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"Loaded node types from workspace: {nodes_path}")
                    return {'success': True, 'data': data}
            except Exception as e:
                print(f"Failed to load nodes.json from workspace: {e}")
        
        # Fallback: try to load from default location (but we didn't package it)
        default_nodes_path = os.path.join(os.path.dirname(web_dir), 'config', 'nodes.json')
        if os.path.exists(default_nodes_path):
            try:
                with open(default_nodes_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"Loaded node types from default: {default_nodes_path}")
                    return {'success': True, 'data': data}
            except Exception as e:
                print(f"Failed to load default nodes.json: {e}")
        
        # If all fails, return empty list (frontend has fallback defaults)
        print("No nodes.json found, using frontend defaults")
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
    def open_node_cache_folder(node_id, node_name):
        """Open the cache folder for a specific node in file explorer."""
        print(f"=== open_node_cache_folder called for node: {node_id}_{node_name} ===")
        if not workspace_dir:
            return {'success': False, 'error': 'No workspace directory'}

        import subprocess
        cache_path = os.path.join(workspace_dir, 'cache', f"{node_id}_{node_name}")
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
        if os.path.exists(os.path.join(workspace_dir, 'nodes.json')):
            print(f"Found nodes.json in workspace")
    print(f"Starting eel server on {host}:{port}...")
    eel.start("index.html", size=(1200, 800), mode=mode, host=host, port=port, block=True)


def main():
    """Command-line entry point for the pipeline viewer."""
    import argparse
    parser = argparse.ArgumentParser(description='Start pipeline viewer web UI')
    parser.add_argument('--host', default='localhost', help='Host to bind to (default: localhost)')
    parser.add_argument('--port', '-p', type=int, default=8080, help='Port to listen on (default: 8080)')
    parser.add_argument('--open', '-o', action='store_true', help='Open browser automatically')
    parser.add_argument('--workspace', '-w', help='Workspace directory containing nodes.json (optional)')
    args = parser.parse_args()
    
    workspace = None
    if args.workspace:
        workspace = os.path.abspath(args.workspace)
        if not os.path.exists(workspace):
            print(f"[WARN] Workspace directory does not exist: {workspace}")
    
    run_viewer(host=args.host, port=args.port, open_browser=args.open, workspace=workspace)


if __name__ == "__main__":
    main()
