# edaglite

**English** | [简体中文](README.zh-CN.md)

A **lightweight, embeddable** DAG workflow manager: define nodes as Python classes, let the framework validate the graph (dangling links / port conflicts / cycle detection), execute it in topological order with per-node file caching, and edit it in a bundled web visual editor.

## Features

- 🪶 **Lightweight and embeddable** - no service, no database. A single Python package you can embed into your own project to define and run DAGs as a library.
- 🕸️ **A real DAG** - validates dangling links, duplicate/conflicting edges and cyclic dependencies before execution, then schedules nodes in topological order (out-of-order declarations are reordered automatically).
- 🚀 **Caching** - nodes that have already run are skipped via the cache directory.
- 🎨 **Visual editor** - a web-based DAG editor where parameters come from node definitions and users only fill in values.
- 📦 **Modular design** - subclass `CachedSubprocess` to define custom nodes easily.
- 🔧 **Single source of truth** - node id/name/icon/group/description plus ports and parameters are all reflected automatically from the Python class registry (`@Pipeline.register_node(icon=..., name=..., node_id=...)`); **no nodes.json is needed**, since that file is only an optional UI overlay. You can also generate it from the registered classes with `--generate-nodes-json`.
- 📝 **Logging** - execution logs are written to files automatically.
- ▶️ **Run a single node** - select a node in the editor and run it alone for debugging.
- 📂 **Cache browsing** - open a node's cache directory with one click.

## Installation

From a wheel:

```bash
pip install dist/edaglite-0.5.0-py3-none-any.whl
```

From PyPI:

```bash
pip install edaglite
```

## Quick start

### 1. Define a custom node

```python
from edaglite import CachedSubprocess, Input, Output, Param, Pipeline

# icon/name/group/description are panel display metadata and are all optional;
# node_id is the type identifier (defaults to the class name) used by the panel
# and workspace.json to look up the type.
@Pipeline.register_node(icon="📦", name="My Node")
class MyNode(CachedSubprocess):
    # Ports and parameters declared here are the single source of truth; the
    # editor panel reflects them automatically with no JSON configuration needed.
    inputs = [Input("input", description="Input data")]
    outputs = [Output("output", description="Output data")]
    params = [Param("value", description="Some parameter", value="default")]

    def _execute(self):
        input_path = self.require_input("input")
        # process...
        # The output file name matches the output port name (without extension);
        # the extension is chosen by the node according to its data type.
        with open(self.cache_path("output"), "w") as f:
            # write output
            pass
```

**Declare parameters with type annotations (recommended)**: annotate scalar class
attributes with `int` / `float` / `str` and the decorator generates the matching
`Param` (including `Optional[X]` / `X | None`), so you no longer need to write
`params` by hand:

```python
@Pipeline.register_node(icon="🎓")
class StudentGenerator(CachedSubprocess):
    outputs = [Output("students.csv")]

    count: int = 10        # equivalent to Param("count", value=10, param_type="int")
    ratio: float = 0.5     # param_type="float"
    prefix: str = "S"      # param_type="string"
    tag: Optional[str] = None
    # Annotations with no matching frontend control (bool/list/dict, ...) are ignored;
    # when names collide, an explicit params=[Param(...)] takes precedence over annotations
```

### 2. Prepare the workspace directory structure

Only `workspace.json` (the DAG connection configuration) is required. All panel
information (ports, parameters, icon, display name) is reflected by the framework
from the registered Python classes, so **nodes.json may be absent entirely**.
`nodes.json` is useful in exactly one scenario: you do not want to touch the Python
code but do want to adjust icons/display names externally. It is a **UI overlay
that does not participate in execution**, and it can live at project level and be
shared by multiple workspaces:

```
my_project/
├── nodes.json       # fully optional - project-level UI overlay shared by all workspaces
└── workspaces/
    ├── ws_a/
    │   └── workspace.json   # DAG connection config (the only required file)
    └── ws_b/
        ├── nodes.json       # optional - a copy inside the workspace, takes precedence
        └── workspace.json
```

Overlay lookup order: **the workspace directory, then each parent directory in turn**
(the first hit wins).

### 3. (Optional) nodes.json overlay and dynamic generation

The overlay accepts display fields only, matched by `id` (the registered type id,
i.e. the class name or `node_id`) against already-registered nodes; ports and
parameters are ignored even if present in the file - they are governed solely by the
`inputs` / `outputs` / `params` declarations in the registered Python classes.
Display field priority:

```
nodes.json overlay  >  register_node(...) metadata  >  defaults (class name / 🧩 / first docstring line)
```

Rather than writing it by hand, you can let the viewer **generate** a scaffold from
the current registered classes (an existing file is never overwritten), then tweak
it:

```bash
# Export to <workspace>/nodes.json by default
edaglite-viewer --workspace ./my_project/workspaces/ws_a --generate-nodes-json

# Or point at an explicit path (e.g. a project-level shared file)
edaglite-viewer -w ./ws --generate-nodes-json ../nodes.json
```

The generated file looks like:

```json
{
    "nodes": [
        {
            "id": "MyNode",
            "name": "My Node",
            "icon": "📦",
            "group": "Data",
            "description": "My custom node"
        }
    ]
}
```

If you want the editor to **completely ignore** the nodes.json on disk (for example
to diagnose a mismatch between file contents and the panel), pass `--no-overlay`.

> When the overlay references an unregistered node type, that entry is ignored and a
> warning is logged at startup. When no node is registered at all, the editor panel
> shows an empty state instead of built-in fake nodes. After changing `node_id`, a
> workspace.json saved with the old id is treated as referencing an unregistered node.

### 4. Start the visual editor

```bash
# Point at a workspace directory; no nodes.json needed - the panel reflects imported
# registered classes directly
edaglite-viewer --workspace ./my_project/workspaces/ws_a --port 8080
```

> **Note**: `edaglite-viewer` is the generic framework entry point and ships no
> business nodes. You need to import your custom node classes (registered via
> `@Pipeline.register_node`) before starting it, or use a launcher script
> (see `demo/run_demo.py`).

Then open http://localhost:8080 in your browser and start editing.

### 5. Run the DAG from the command line

```bash
edaglite-run --pipeline ./my_workspace/workspace.json
```

The working folder is taken automatically from the directory containing
`workspace.json`; no extra flag is needed.

### 6. Clear cache and logs

```bash
edaglite-clean --pipeline ./my_workspace/workspace.json
```

## Running the example

Install the package first:

```bash
pip install dist/edaglite-0.5.0-py3-none-any.whl
```

Then use the launcher script to try the example:

```bash
# Launcher script (registers the demo nodes and starts the editor)
python demo/run_demo.py
```

Or run straight from source (no installation needed):

```bash
cd edaglite
python demo/run_demo.py
```

The example already includes:
- `demo/demo_nodes.py` - Python implementations of the sample nodes (icons declared via `register_node(icon=...)`, no nodes.json)
- `demo/test_workspace/workspace.json` - a fully wired DAG configuration

**If the command is not found**, your Python Scripts directory is not on PATH; run it
through `python -m` instead:

```bash
python -m edaglite.pipeline_viewer --workspace ./my_workspace --port 8080
```

## Command-line tools

| Command | Description | Example |
|------|------|------|
| `edaglite-run` | Run a DAG | `edaglite-run --pipeline ./workspace/workspace.json [-f]` |
| `edaglite-viewer` | Start the visual editor | `edaglite-viewer --workspace ./workspace [--port 8080] [--open] [--no-overlay] [--generate-nodes-json [PATH]]` |
| `edaglite-clean` | Clear the cache | `edaglite-clean --pipeline ./workspace/workspace.json` |

### Flags

**edaglite-run**:
- `--pipeline, -p` - path to workspace.json (required)
- `--force, -f` - force re-execution, ignoring the cache (optional)

The working folder is taken automatically from the directory containing
`workspace.json`; no extra flag is needed.

**edaglite-viewer**:
- `--workspace, -w` - workspace directory (the nodes.json overlay is looked up along this directory and its parents) (optional)
- `--port, -p` - port to listen on, default 8080 (optional)
- `--host` - address to bind to, default localhost (optional)
- `--open, -o` - open the browser automatically (optional)
- `--no-overlay` - ignore nodes.json entirely; panel metadata comes from the registered classes only (optional)
- `--generate-nodes-json [PATH]` - export a nodes.json scaffold from the registered classes before starting (default `<workspace>/nodes.json`, never overwrites an existing file) (optional)

**edaglite-clean**:
- `--pipeline, -p` - path to workspace.json (required)

## Python API

```python
from edaglite import Pipeline, CachedSubprocess

# Load a DAG from JSON
pipeline = Pipeline.load_from_json("workspace.json", "./workspace")
pipeline.run()

# Run a single node (by frontend node id)
pipeline.run_node_by_frontend_id(1)
```

## Project layout

```
edaglite/
├── edaglite/                # the Python package (packaged into the wheel)
│   ├── __init__.py          # package init, exports the public API
│   ├── pipeline.py          # core: Pipeline, CachedSubprocess, Context, ...
│   ├── pipeline_viewer.py   # web visual editor
│   ├── run.py               # edaglite-run entry point
│   ├── clean.py             # edaglite-clean entry point
│   └── web/                 # web static assets
│       ├── index.html
│       └── js/
│           ├── app.js
│           ├── connections.js
│           └── properties.js
├── demo/                    # example workspace (not packaged into the wheel)
│   ├── demo_nodes.py        # sample node implementations (with register_node icon metadata)
│   ├── run_demo.py          # sample launcher script
│   ├── run_pipeline.py      # command-line run script
│   ├── view_pipeline.py     # visual editor launcher script
│   └── test_workspace/
│       └── workspace.json
├── dist/
│   └── edaglite-0.5.0-py3-none-any.whl
├── README.md
└── pyproject.toml
```

The `demo/` directory is an example that lives in the source repository and is **not
packaged into the wheel**. Installed packages do not include it.

## Requirements

- Python >= 3.8
- eel >= 0.16.0
- bottle >= 0.12.25
- gevent >= 23.9.1
- greenlet >= 2.0.2
- colorama >= 0.4.6
- typing-extensions >= 4.8.0

## License

Apache License 2.0 - see [LICENSE](LICENSE).
