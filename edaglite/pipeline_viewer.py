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

# 向上查找 nodes.json 时最多跨越的父目录层数（防止误中用户根目录等高层位置）
_MAX_NODES_JSON_LEVELS = 8


def _find_nodes_json(start_dir):
    """按 ``workspace → 父目录链`` 的顺序查找 nodes.json，返回首个命中的绝对路径。

    查找的第一站就是 workspace 目录本身，因此"每个 workspace 放一份
    nodes.json"的旧布局继续生效（就近优先，向后兼容）；workspace 内没有时，
    再逐级向上到项目级目录，使多个 workspace 可以共享同一份节点类型面板
    定义。到达盘符根目录或超过层数上限仍未找到时返回 None。
    """
    if not start_dir:
        return None
    cur = os.path.abspath(start_dir)
    for _ in range(_MAX_NODES_JSON_LEVELS + 1):
        candidate = os.path.join(cur, 'nodes.json')
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:  # 已到达盘符根目录
            break
        cur = parent
    return None


# 覆盖层允许提供的纯 UI 字段（按节点类型名匹配；端口与参数一律以 Python 注册类为准）
_OVERLAY_UI_KEYS = ("name", "icon", "group", "description")
_DEFAULT_ICON = "🧩"


def _load_overlay(workspace):
    """读取可选的 nodes.json UI 覆盖层，返回 {节点类型名: UI 配置}。

    nodes.json 不再是端口/参数的真相源，仅可提供展示名、图标、分组、描述
    等 UI 元数据；其中多写的 inputs/outputs/params 会被忽略。文件不存在或
    解析失败时返回空 dict（此时面板全部字段来自 Python 注册类）。
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
    """从 ``Pipeline.NODE_REGISTRY`` 反射生成编辑器节点面板数据。

    Python 注册类是唯一直相：面板上的端口、参数、描述全部来自实例化后的
    节点对象（类级声明与 ``__init__`` 动态添加两种写法都能正确反映）；
    展示字段的优先级为 nodes.json 覆盖层 > ``register_node(...)`` 元数据 >
    默认值（类名 / 🧩 / docstring 首行）。``use_overlay=False`` 时完全忽略
    nodes.json，面板信息全部来自注册类——此时根本不需要 nodes.json 存在。

    实例化使用临时工作目录的一次性 Context，避免仅仅打开编辑器就在真实
    workspace 下创建 cache 目录；实例化失败的单个节点被跳过并告警，不影响
    其余类型展示。

    Returns:
        ``{"nodes": [ {id,name,icon,group,description,cache_name,
        inputs,outputs,params}, ... ]}``，顺序与节点注册顺序一致；没有任何
        已注册类型时 nodes 为空列表。
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
            # register_node(name/icon/group/description=...) 提供的类级元数据
            meta = getattr(node_cls, '_node_meta', {})
            default_desc = inst.description or meta.get("description") or doc_desc
            ui = overlay.get(type_name, {})

            result["nodes"].append({
                "id": type_name,
                "name": ui.get("name") or meta.get("name") or inst.name,
                "icon": ui.get("icon") or meta.get("icon") or _DEFAULT_ICON,
                "group": ui.get("group") or meta.get("group") or "",
                "description": ui.get("description") or default_desc,
                # 磁盘缓存目录命名标识 cache/{前端id}_{cache_name}，默认等于
                # 类名；与展示名解耦，前端"打开缓存目录"必须回传此值
                "cache_name": inst.name,
                "inputs": [{"name": p.name, "description": p.description}
                           for p in inst.inputs],
                "outputs": [{"name": p.name, "description": p.description}
                            for p in inst.outputs],
                # type 沿用 nodes.json 契约（int/float/string）；
                # 前端建节点时会据此同时生成 UI 的 type 与后端的 param_type
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
        print(f"[WARN] nodes.json 覆盖层中存在未注册节点类型，已忽略: {extra}")
    return result


def _export_overlay_scaffold(target_path, workspace):
    """从当前注册表导出一份纯 UI 覆盖层 nodes.json（忽略任何已有覆盖层）。

    导出内容只有 id/name/icon/group/description——端口与参数永远以 Python
    注册类为准，因此脚手架里不包含它们。返回导出的节点类型数。
    已存在的目标文件由调用方决定是否跳过，本函数不做覆盖保护。
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
        use_overlay: 是否加载 nodes.json UI 覆盖层；False 时面板元数据完全
            来自 Python 注册类（适用于彻底不使用 nodes.json 的项目）。
        generate_nodes_json: 启动前把注册类反射结果导出为 nodes.json 脚手架。
            None 表示不导出；空字符串表示导出到 ``<workspace>/nodes.json``；
            非空字符串作为目标路径。目标已存在时不会被覆盖。
    """
    global workspace_dir
    workspace_dir = workspace

    # 可选：启动时动态生成 nodes.json 脚手架（仅当目标不存在时）
    if generate_nodes_json is not None:
        target = generate_nodes_json or (
            os.path.join(workspace, 'nodes.json') if workspace else None)
        if not target:
            print("[WARN] --generate-nodes-json 需要显式路径（当前未指定 workspace），已跳过")
        elif os.path.exists(target):
            print(f"[INFO] nodes.json 已存在，保留不覆盖: {os.path.abspath(target)}")
        else:
            count = _export_overlay_scaffold(target, workspace)
            print(f"[INFO] 已从注册类生成 nodes.json 脚手架（{count} 个类型）: "
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
        """反射已注册的 Python 节点类生成面板，nodes.json 仅作 UI 覆盖层。"""
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

        ``folder_name`` 是节点类型的磁盘命名标识（面板数据的 cache_name，
        默认类名），不能用可被 register_node/nodes.json 改写的展示名，否则
        会定位到错误的缓存目录。
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
