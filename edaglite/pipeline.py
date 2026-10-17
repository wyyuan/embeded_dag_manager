import os
import json
import csv
import shutil
import datetime
import sys
import inspect
import copy
import types
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import (
    Dict, Callable, Any, List, Optional, Literal,
    Union, get_type_hints, get_origin, get_args,
)
from collections import defaultdict, deque


@dataclass
class Input:
    name: str
    description: str = ""
    path: Optional[str] = None


@dataclass
class Output:
    name: str
    description: str = ""
    path: Optional[str] = None


@dataclass
class Param:
    name: str
    description: str = ""
    value: Any = None
    param_type: Literal["float", "int", "string"] = "string"


class Context(dict):
    """Execution context: key-value storage shared across nodes + working-folder location.

    Context is itself a dict: the ``globals`` and ``working_folder`` of
    workspace.json are both stored as ordinary keys, and nodes read them
    directly via ``self.ctx[key]`` / ``self.ctx.get(key)``; the framework no
    longer maintains any separate global shared cache.
    """

    _id_counter = 0

    def __init__(self, working_folder: str, **kwargs):
        super().__init__(**kwargs)
        self.working_folder = working_folder
        self['working_folder'] = working_folder
        os.makedirs(working_folder, exist_ok=True)

    @classmethod
    def generate_id(cls) -> int:
        cls._id_counter += 1
        return cls._id_counter


class CachedSubprocess(ABC):
    """Single pipeline stage with file-based caching: input → execute → output

    This class corresponds to the NODE concept in the frontend editor,
    supporting configurable inputs, outputs, and custom parameters.
    """

    def __init__(self, ctx: Context, id: int = None):
        self.id = id if id is not None else Context.generate_id()
        self.ctx = ctx
        self.name = self.__class__.__name__
        self.description = ""

        self.inputs: List[Input] = []
        self.outputs: List[Output] = []
        self.params: List[Param] = []

    @abstractmethod
    def _execute(self):
        """Concrete stage logic: read inputs, produce outputs to cache folder."""
        pass

    def get_input(self, port_name: str) -> Optional[Input]:
        """Get input port by name."""
        return next((p for p in self.inputs if p.name == port_name), None)

    def get_output(self, port_name: str) -> Optional[Output]:
        """Get output port by name."""
        return next((p for p in self.outputs if p.name == port_name), None)

    def cache_path(self, name: str) -> str:
        """Absolute path for a file in this subprocess instance's cache folder."""
        return os.path.join(self.ctx.working_folder, 'cache', f"{self.id}_{self.name}", name)

    def cache_folder(self) -> str:
        """Absolute path for this subprocess instance's cache folder."""
        return os.path.join(self.ctx.working_folder, 'cache', f"{self.id}_{self.name}")

    def require_input(self, port_name: str) -> str:
        """Get input path, raise ValueError if not connected.
        
        Helper to avoid repeated "if not x: raise ValueError" boilerplate.
        """
        port = self.get_input(port_name)
        if not port or not port.path:
            raise ValueError(f"Input '{port_name}' not connected (port path not set)")
        return port.path

    def run(self, force: bool = False):
        """Execute the stage with caching support."""
        cache_dir = self.cache_folder()
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

        # —— Record the actual file names (with extensions) referenced by inputs/outputs, to catch wrong file references ——
        # Input file name = upstream output port name (the framework resolves it this way when connecting); port names may carry an extension (e.g. xxx.csv);
        # Output files are resolved via cache_path(port_name); the real extension is whatever ends up on disk after writing.
        for p in self.inputs:
            if p.path and not os.path.exists(p.path):
                folder = os.path.dirname(p.path)
                present = [f for f in os.listdir(folder)] if os.path.isdir(folder) else []
                print(f"    [WARN] Input {p.name} references a missing file: {p.path}"
                      + (f", actual files in cache dir: {present}" if present else ""))
        inputs_desc = "; ".join(
            f"{p.name}={os.path.basename(p.path)}" if p.path else f"{p.name}=(not connected)"
            for p in self.inputs)
        outputs_desc = "; ".join(
            f"{p.name}={os.path.basename(self.cache_path(p.name))}" for p in self.outputs)
        print(f"    [PORTS] inputs : {inputs_desc or '(none)'}")
        print(f"    [PORTS] outputs: {outputs_desc or '(none)'}")

        cached_outputs = [f for f in os.listdir(cache_dir) if os.path.isfile(os.path.join(cache_dir, f))]
        all_cached = not force and len(cached_outputs) > 0
        
        if all_cached:
            print(f'[SKIP] {self.name} cached - skipped')
        else:
            print(f'[EXEC] {self.name} executing...')
            self._execute()
            print(f'[DONE] {self.name} finished')
            # After execution, record the files actually produced in the cache dir (with extensions) for verification
            actual = [f for f in os.listdir(cache_dir) if os.path.isfile(os.path.join(cache_dir, f))]
            if actual:
                print(f"    [FILES] actual outputs: {', '.join(actual)}")


class Pipeline:
    """
    Pipeline executor class, responsible for managing and executing a series of CachedSubprocess stages.

    Pipeline is the core controller of the whole workflow; it is responsible for:
    1. Loading the working-folder configuration (from workspace.json or defaults)
    2. Managing the execution context (Context)
    3. Executing all stages in order
    4. Logging execution to file and console

    Attributes:
        working_folder: Working-folder path containing the config file and output directory
        force: Whether to force re-execution of all stages (skipping the cache check)
        ctx: Context object storing shared configuration and state
        stages: List of CachedSubprocess instances, representing execution stages
        log_dir: Log directory path
        log_file: Log file path for the current execution
        original_stdout: Original stdout, restored after execution finishes
    """

    def __init__(self, stages, working_folder: str, force: bool = False):
        """
        Initialize a Pipeline instance

        Args:
            stages: Iterable of CachedSubprocess instances, ordered by execution order
            working_folder: Working-folder path, may contain a workspace.json file (optional)
            force: Whether to force re-execution (default False, i.e. use the cache)
        """
        self.working_folder = working_folder
        self.force = force
        
        # Try to load workspace.json config (optional)
        cfg = {}
        pipeline_path = os.path.join(working_folder, "workspace.json")
        if os.path.isfile(pipeline_path):
            try:
                with open(pipeline_path, "r", encoding="utf-8") as f:
                    pipeline_data = json.load(f)
                    # globals are merged into cfg as plain keys and then land in the Context dict via Context(**cfg)
                    cfg.update(pipeline_data.get('globals', {}))
            except Exception as e:
                print(f"[WARN] Failed to load workspace.json: {e}")
        
        # Set the absolute path of the working folder
        cfg["working_folder"] = os.path.abspath(working_folder)
        
        # Create the context object (Context is a dict; nodes can read globals via ctx.get(key))
        self.ctx = Context(**cfg)
        
        # Convert stages to a list to ensure it can be iterated multiple times
        self.stages = list(stages)

        # Mapping from frontend node ID to stage instance (used to run a single node)
        self._node_frontend_id_map: Dict[str, 'CachedSubprocess'] = {}

        # Raw connection table (populated by load_from_json), used for pre-execution graph validation and topological sort
        self.edges: List[dict] = []

        # Unregistered node types: frontend node ID -> node type name (populated by load_from_json).
        # These nodes cannot be instantiated because their type is not in NODE_REGISTRY; graph
        # validation and single-node execution use this to give an accurate "type not registered"
        # error rather than a vague "node not found".
        self.unregistered_nodes: Dict[Any, str] = {}

        # Create the log directory
        self.log_dir = os.path.join(working_folder, "logs")
        os.makedirs(self.log_dir, exist_ok=True)

        # Create a timestamped log file
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(self.log_dir, f"pipeline_{timestamp}.log")
        
        # Save the original stdout for later restoration
        self.original_stdout = sys.stdout

    def run(self):
        """
        Execute all stages of the whole Pipeline

        Execution flow:
        1. Create a Tee object that writes output to both the console and the log file
        2. Redirect stdout to the Tee object
        3. Print execution info (start time, working folder, force mode, stage list)
        4. Before execution, validate the connection graph (dangling connections / duplicate or conflicting edges / cyclic
           dependencies) and order nodes topologically; when the declaration order is valid the execution order matches
           the declaration order, and when out of order it is rearranged automatically
        5. Execute each stage in topological order
        6. Print completion info
        7. Restore the original stdout

        The log file is saved at working_folder/logs/pipeline_YYYYMMDD_HHMMSS.log
        """
        # Open the log file and set up output redirection
        with open(self.log_file, 'w', encoding='utf-8') as f:
            # Define the Tee class: write output to multiple streams at once (console + file)
            class Tee:
                def __init__(self, *files):
                    """Initialize the Tee object, accepting multiple file objects"""
                    self.files = files
                
                def write(self, data):
                    """Write data to all files and flush immediately"""
                    for file in self.files:
                        file.write(data)
                        file.flush()
                
                def flush(self):
                    """Flush all file buffers"""
                    for file in self.files:
                        file.flush()

            # Redirect stdout to Tee (output to both console and log file)
            sys.stdout = Tee(self.original_stdout, f)

            try:
                # Print execution start info
                print(f"[INFO] Pipeline started at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"[INFO] Working folder: {self.working_folder}")
                print(f"[INFO] Force mode: {self.force}")
                print(f"[INFO] Log file: {self.log_file}")
                print("=" * 80)

                # Pre-execution graph validation (dangling connections / duplicate edges / cyclic dependencies) to get topological order
                ordered_stages = self._validate_graph_and_order()
                if ordered_stages != self.stages:
                    print("[INFO] Node declaration order is not topological; execution reordered automatically by dependency")

                # Print the stage list
                print("[INFO] Stages to execute:")
                for i, stage in enumerate(ordered_stages, 1):
                    print(f"  {i}. {stage.name}")
                print("=" * 80)

                # Execute all stages in topological order
                print("[INFO] Executing stages:")
                for i, stage in enumerate(ordered_stages, 1):
                    print(f"\n--- Stage {i}: {stage.name} ---")
                    stage.run(force=self.force)

                # Print completion info
                print("\n" + "=" * 80)
                print("[INFO] Pipeline finished - all stages done")
                print(f"[INFO] Pipeline completed at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            finally:
                # Ensure the original stdout is restored
                sys.stdout = self.original_stdout
                print(f"[INFO] Log saved to: {self.log_file}")

    def run_stage(self, name: str):
        """
        Start a single subprocess (stage) by name, writing output to both console and log file

        Args:
            name: Stage name (corresponds to CachedSubprocess.name)

        Raises:
            ValueError: Thrown when no stage with the given name is found
        """
        stage = next((s for s in self.stages if s.name == name), None)
        if stage is None:
            available = ", ".join(s.name for s in self.stages)
            raise ValueError(f"Stage '{name}' not found. Available stages: {available}")

        # Open the log file and set up output redirection
        with open(self.log_file, 'w', encoding='utf-8') as f:
            # Define the Tee class: write output to multiple streams at once (console + file)
            class Tee:
                def __init__(self, *files):
                    """Initialize the Tee object, accepting multiple file objects"""
                    self.files = files

                def write(self, data):
                    """Write data to all files and flush immediately"""
                    for file in self.files:
                        file.write(data)
                        file.flush()

                def flush(self):
                    """Flush all file buffers"""
                    for file in self.files:
                        file.flush()

            # Redirect stdout to Tee (output to both console and log file)
            sys.stdout = Tee(self.original_stdout, f)

            try:
                # Print execution start info
                print(f"[INFO] Pipeline started at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"[INFO] Working folder: {self.working_folder}")
                print(f"[INFO] Force mode: {self.force}")
                print(f"[INFO] Log file: {self.log_file}")
                print("=" * 80)

                # Execute the specified stage
                print(f"[INFO] Running stage: {name}")
                print(f"\n--- Stage: {stage.name} ---")
                stage.run(force=self.force)

                # Print completion info
                print("\n" + "=" * 80)
                print(f"[INFO] Stage '{name}' finished")
                print(f"[INFO] Pipeline completed at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            finally:
                # Ensure the original stdout is restored
                sys.stdout = self.original_stdout
                print(f"[INFO] Log saved to: {self.log_file}")

    def run_node_by_frontend_id(self, node_id: str):
        """
        Start a single node by frontend ID, writing output to both console and log file

        Args:
            node_id: Frontend node ID (corresponds to the id field in the frontend nodes array)

        Raises:
            ValueError: Thrown when no node with the given ID is found
        """
        stage = self._node_frontend_id_map.get(node_id)
        if stage is None:
            if node_id in self.unregistered_nodes:
                raise ValueError(
                    f"Node '{node_id}' has type '{self.unregistered_nodes[node_id]}' "
                    f"which is not registered and cannot be run alone; make sure the node's "
                    f"Python definition is imported before startup")
            available_ids = ", ".join(map(str, self._node_frontend_id_map.keys()))
            raise ValueError(f"Node '{node_id}' not found. Available IDs: {available_ids}")

        # Open the log file and set up output redirection
        with open(self.log_file, 'w', encoding='utf-8') as f:
            # Define the Tee class: write output to multiple streams at once (console + file)
            class Tee:
                def __init__(self, *files):
                    self.files = files

                def write(self, data):
                    for file in self.files:
                        file.write(data)
                        file.flush()

                def flush(self):
                    for file in self.files:
                        file.flush()

            # Redirect stdout to Tee (output to both console and log file)
            sys.stdout = Tee(self.original_stdout, f)

            try:
                # Print execution start info
                print(f"[INFO] Pipeline started at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"[INFO] Working folder: {self.working_folder}")
                print(f"[INFO] Force mode: {self.force}")
                print(f"[INFO] Log file: {self.log_file}")
                print("=" * 80)

                # Execute the specified node
                print(f"[INFO] Running single node: {stage.name} (frontend ID: {node_id})")
                print(f"\n--- Stage: {stage.name} ---")
                stage.run(force=self.force)

                # Print completion info
                print("\n" + "=" * 80)
                print(f"[INFO] Node '{stage.name}' finished")
                print(f"[INFO] Pipeline completed at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            finally:
                # Ensure stdout is restored
                sys.stdout = self.original_stdout
                print(f"[INFO] Log saved to: {self.log_file}")

    def _validate_graph_and_order(self) -> List["CachedSubprocess"]:
        """Validate the connection graph before execution and return nodes in topological order.

        Three kinds of invalid graphs are validated (any failure raises ValueError and aborts execution, no silent ignoring):

        1. **Dangling connections**: an edge references a node that does not exist, or the referenced output/input port
           does not exist on the node (e.g. the node type changed but the canvas still holds old wiring);
        2. **Duplicate/conflicting edges**: the exact same connection appears multiple times; or the same input port
           is connected by two different upstream outputs (before, the latter was silently overwritten by the last edge);
        3. **Cyclic dependencies**: the graph contains a cycle, so the execution order cannot be determined; raise an
           error listing the nodes on the cycle.

        Returns:
            A stage list in topological order (upstream first). A stable strategy is used -- each round picks the
            "ready" node earliest in declaration order, so when the nodes declaration order is itself a valid
            topological order (as in demo), the execution order is exactly as before; rearrangement happens only
            when the declaration is out of order. A Pipeline built directly in code, without load_from_json assembly,
            has no edge table and returns ``self.stages`` unchanged.

        Raises:
            ValueError: Thrown when graph validation fails, with a message identifying the specific invalid connection or cycle nodes.
        """
        # A Pipeline built directly in code has no frontend ID map or edge table, so keep linear execution
        if not self._node_frontend_id_map:
            return list(self.stages)

        fid_map = self._node_frontend_id_map

        # If the graph has nodes with unregistered types (even without edges), it cannot fully execute; raise explicitly
        if self.unregistered_nodes:
            detail = ", ".join(
                f"ID={fid}({ntype})" for fid, ntype in self.unregistered_nodes.items())
            raise ValueError(
                f"Unregistered node type(s) present, cannot execute: {detail}; "
                f"make sure these nodes' Python definitions are imported before startup (@Pipeline.register_node)")

        decl_order = list(fid_map.keys())  # fid_map is inserted in nodes-array order

        adjacency: Dict[Any, List[Any]] = {fid: [] for fid in decl_order}
        indegree: Dict[Any, int] = {fid: 0 for fid in decl_order}
        seen_edges = set()
        input_sources: Dict[tuple, tuple] = {}

        for conn in self.edges:
            from_fid = conn.get('from', {}).get('node')
            from_port = conn.get('from', {}).get('port')
            to_fid = conn.get('to', {}).get('node')
            to_port = conn.get('to', {}).get('port')

            # —— 1a. Dangling: the referenced node does not exist (distinguish "type not registered" from "ID not found") ——
            if from_fid not in fid_map:
                if from_fid in self.unregistered_nodes:
                    raise ValueError(
                        f"Node (ID={from_fid}) has type "
                        f"'{self.unregistered_nodes[from_fid]}' which is not registered, cannot execute; "
                        f"make sure the node's Python definition is imported before startup"
                        f" (wiring: {from_fid}.{from_port} -> {to_fid}.{to_port})")
                raise ValueError(
                    f"Invalid connection: source node '{from_fid}' does not exist"
                    f" ({from_fid}.{from_port} -> {to_fid}.{to_port}); remove the dangling wiring on the canvas")
            if to_fid not in fid_map:
                if to_fid in self.unregistered_nodes:
                    raise ValueError(
                        f"Node (ID={to_fid}) has type "
                        f"'{self.unregistered_nodes[to_fid]}' which is not registered, cannot execute; "
                        f"make sure the node's Python definition is imported before startup"
                        f" (wiring: {from_fid}.{from_port} -> {to_fid}.{to_port})")
                raise ValueError(
                    f"Invalid connection: target node '{to_fid}' does not exist"
                    f" ({from_fid}.{from_port} -> {to_fid}.{to_port}); remove the dangling wiring on the canvas")

            from_inst = fid_map[from_fid]
            to_inst = fid_map[to_fid]

            # —— 1b. Dangling: the referenced port does not exist ——
            if from_inst.get_output(from_port) is None:
                raise ValueError(
                    f"Invalid connection: node '{from_inst.name}' has no output port '{from_port}'"
                    f" (-> {to_inst.name}.{to_port})")
            if to_inst.get_input(to_port) is None:
                raise ValueError(
                    f"Invalid connection: node '{to_inst.name}' has no input port '{to_port}'"
                    f" ({from_inst.name}.{from_port} ->)")

            # —— 2a. Fully duplicate edges ——
            edge_key = (from_fid, from_port, to_fid, to_port)
            if edge_key in seen_edges:
                raise ValueError(
                    f"Duplicate connection: {from_inst.name}.{from_port} -> "
                    f"{to_inst.name}.{to_port} appears multiple times; keep only one")
            seen_edges.add(edge_key)

            # —— 2b. The same input port connected by multiple upstreams (multi-producer conflict) ——
            port_key = (to_fid, to_port)
            prev = input_sources.get(port_key)
            if prev is not None:
                prev_fid, prev_port = prev
                raise ValueError(
                    f"Input port conflict: '{to_inst.name}.{to_port}' is connected by both "
                    f"'{fid_map[prev_fid].name}.{prev_port}' and "
                    f"'{from_inst.name}.{from_port}'; an input port can have only one upstream")
            input_sources[port_key] = (from_fid, from_port)

            adjacency[from_fid].append(to_fid)
            indegree[to_fid] += 1

        # —— 3. Kahn topological sort; stable strategy: each round picks the earliest declared zero-indegree node ——
        # Node counts are usually only a few dozen, so an O(N²) full scan buys the stable semantics of
        # "valid declaration order == execution order", avoiding needless rearrangement.
        remaining = set(decl_order)
        work_indegree = dict(indegree)
        ordered: List[Any] = []
        while remaining:
            picked = next(
                (fid for fid in decl_order if fid in remaining and work_indegree[fid] == 0),
                None
            )
            if picked is None:
                cycle_names = ", ".join(
                    fid_map[fid].name for fid in decl_order if fid in remaining)
                raise ValueError(
                    f"Cyclic dependency detected, cannot determine execution order. Nodes on the cycle (or their downstream): {cycle_names}")
            remaining.discard(picked)
            ordered.append(picked)
            for nxt in adjacency[picked]:
                work_indegree[nxt] -= 1

        return [fid_map[fid] for fid in ordered]

    def clean(self):
        """
        Clean up the cache and logs under the working folder (whitelist approach: delete only ``cache/`` and ``logs/``).

        Only the two directories produced by the framework itself are deleted; node scripts, workspace.json,
        nodes.json and any other user files in the workspace are never touched -- avoiding a blacklist-style
        deletion that would erase user data when working_folder is passed incorrectly.
        """
        if not os.path.isdir(self.working_folder):
            print(f"[INFO] {self.working_folder} not found, skipped")
            return
        # Whitelist: only directories produced by the framework itself may be deleted
        targets = ["cache", "logs"]
        for name in targets:
            target = os.path.join(self.working_folder, name)
            if not os.path.exists(target):
                continue
            if os.path.isdir(target):
                shutil.rmtree(target)
            else:
                os.remove(target)
            print(f"[INFO] Removed {target}")

    # Node type registry: node type id -> class object
    # id defaults to the class name and can be customized via @Pipeline.register_node(node_id=...)
    NODE_REGISTRY: Dict[str, type] = {}

    @staticmethod
    def register_node(cls=None, *, node_id=None, name=None, icon=None,
                      group=None, description=None):
        """Register a CachedSubprocess subclass, with optional UI metadata.

        Can be used bare (``@Pipeline.register_node``) or parameterised
        (``@Pipeline.register_node(icon="🎓", name="Display Name")``). The optional
        metadata is consumed by the visual editor's node palette only — it
        never affects execution or cache paths:

        - ``node_id``: registry key / node type id, used by the palette and
          workspace.json to locate the type; defaults to the class name. After
          customization, the old type name in an old workspace.json is treated
          as unregistered.
        - ``name``: palette display name, defaults to node_id.
        - ``icon`` / ``group`` / ``description``: palette icon, group and description;
          when description is absent the palette falls back to the first line of
          the class docstring.

        Besides metadata, three convenience features are supported:

        1. Class-level declarative traits:
           Declare ``inputs`` / ``outputs`` / ``params`` as class attributes and
           they will be deep-copied into each instance automatically, so you do
           not need to assign them inside ``__init__``.

        2. Type-hint parameters:
           Annotated scalar class attributes become params automatically —
           ``count: int = 10`` is equivalent to
           ``params = [Param("count", value=10, param_type="int")]``.
           Supported annotations are ``int`` / ``float`` / ``str`` and a single
           scalar wrapped in ``Optional[...]``; other annotations are ignored.
           Explicit ``params`` take precedence over same-named hints.

        3. Simplified ``__init__`` signature:
           You may write ``def __init__(self, ctx):`` without the ``id``
           parameter.  The decorator normalises the signature so the class is
           still constructible as ``Cls(ctx, id=...)`` / ``Cls(ctx)``.

        Example::

            @Pipeline.register_node
            class CloneSolution(CachedSubprocess):
                inputs = [Input("solution_json")]
                outputs = [Output("clones")]
                multiplier: int = 1

                def __init__(self, ctx):
                    super().__init__(ctx)
        """
        def decorator(cls):
            if not isinstance(cls, type) or not issubclass(cls, CachedSubprocess):
                raise TypeError(
                    f"@Pipeline.register_node can only decorate CachedSubprocess "
                    f"subclasses, got {cls!r}"
                )

            type_id = str(node_id) if node_id is not None else cls.__name__
            existing = Pipeline.NODE_REGISTRY.get(type_id)
            if existing is not None and existing is not cls:
                raise ValueError(
                    f"Duplicate node type id '{type_id}': already registered to "
                    f"{existing.__name__}, cannot re-register {cls.__name__}"
                )
            # Pure palette metadata (not involved in execution); read by viewer reflection
            cls._node_meta = {
                "id": type_id,
                "name": str(name) if name else type_id,
                "icon": icon or "",
                "group": group or "",
                "description": description or "",
            }
            return Pipeline._register_node_traits(cls, type_id)

        # Bare decorator usage @Pipeline.register_node: the first positional argument is the class
        if cls is not None:
            return decorator(cls)
        # Factory usage @Pipeline.register_node(icon=...): returns the actual decorator
        return decorator

    @staticmethod
    def _register_node_traits(cls, type_id):
        """Apply trait-injection/__init__ normalisation and put cls into registry."""
        # ---- Collect class-level declarative traits -------------------------
        # Use vars(cls) instead of getattr so we only pick *direct* class
        # attributes and don't accidentally pull them from CachedSubprocess.
        declared_inputs = vars(cls).get("inputs", None)
        declared_outputs = vars(cls).get("outputs", None)
        declared_params = vars(cls).get("params", None)
        # Derive params from class-level scalar type hints (int/float/str, including Optional wrapping)
        hint_params = Pipeline._params_from_type_hints(
            cls, declared_inputs, declared_outputs, declared_params)

        # ---- Inspect original __init__ signature ----------------------------
        original_init = cls.__init__
        init_sig = inspect.signature(original_init)
        init_param_names = list(init_sig.parameters.keys())

        # Does the user-defined __init__ accept an `id` argument?
        # Skip "self"; accept both positional and keyword forms.
        rest_names = [n for n in init_param_names if n != "self"]
        accepts_id = "id" in rest_names

        # ---- Build injected __init__ wrapper --------------------------------
        def _wrapped_init(self, ctx: Context, id: Optional[int] = None, **kwargs):
            # Decide which id to use ONCE up front.  If the user later calls
            # ``super().__init__(ctx)`` without an ``id`` argument it will
            # overwrite self.id with a freshly generated one — we restore our
            # chosen id at the very end, below.
            if id is None:
                target_id = Context.generate_id()
            else:
                target_id = id

            # 1. Run the base-class constructor first so that `inputs`/`outputs`/
            #    `params` are initialised as empty lists (guaranteed by
            #    CachedSubprocess.__init__).  We always pass the explicit
            #    target_id whether the user subclass accepts it or not.
            #
            #    NOTE: we intentionally do the base init here and NOT rely on
            #    the user to call ``super().__init__(ctx, id)``, because if the
            #    user does call it later (which is still perfectly valid) it
            #    will only overwrite id/ctx/inputs/outputs/params with the same
            #    values or reset the lists to ``[]`` — we therefore perform
            #    declarative-trait injection and id-restoration *after* user
            #    __init__ has had a chance to run.
            CachedSubprocess.__init__(self, ctx=ctx, id=target_id)

            # 2. Call the user's __init__ with a compatible argument list.
            #    Users may still call ``super().__init__(ctx[, id])`` themselves
            #    for style or legacy reasons; that only resets the field lists
            #    to empty and potentially overwrites self.id, both of which we
            #    repair below.
            if accepts_id:
                # Original is `def __init__(self, ctx, id=None): ...` — pass both
                original_init(self, ctx, id=target_id, **kwargs)
            else:
                # Original is the simplified `def __init__(self, ctx): ...`
                original_init(self, ctx, **kwargs)

            # 3. Restore the authoritative id and inject declarative traits
            #    AFTER the user's __init__ returns.  This guards against a
            #    ``super().__init__(ctx)`` call (without `id`) inside the user
            #    constructor, which would otherwise clobber the id that was
            #    passed to the wrapper.
            self.id = target_id

            # Deep copy so each instance owns its own Input/Output/Param
            # objects and modifying one instance does not affect others or
            # the class defaults.
            if declared_inputs is not None:
                self.inputs = [copy.deepcopy(p) for p in declared_inputs]
            if declared_outputs is not None:
                self.outputs = [copy.deepcopy(p) for p in declared_outputs]
            if declared_params is not None:
                self.params = [copy.deepcopy(p) for p in declared_params]
            # Hint params are placed after explicit declarations; same-name ones (including those added dynamically in __init__) are not overwritten
            if hint_params:
                existing_param_names = {p.name for p in self.params}
                for p in hint_params:
                    if p.name not in existing_param_names:
                        self.params.append(copy.deepcopy(p))

        # Preserve metadata so introspection / debugging stays friendly.
        _wrapped_init.__name__ = original_init.__name__
        _wrapped_init.__qualname__ = original_init.__qualname__
        _wrapped_init.__doc__ = original_init.__doc__
        _wrapped_init.__module__ = original_init.__module__
        try:
            _wrapped_init.__signature__ = init_sig.replace(
                parameters=[
                    inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD),
                    inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                      annotation=Context),
                    inspect.Parameter("id", inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                      default=None, annotation=Optional[int]),
                ]
            )
        except (ValueError, TypeError):
            pass

        cls.__init__ = _wrapped_init

        # ---- Register and return -------------------------------------------
        Pipeline.NODE_REGISTRY[type_id] = cls
        return cls

    # Scalar type hint -> Param.param_type whitelist (bool not supported: no corresponding frontend control)
    _HINT_PARAM_TYPES = {int: "int", float: "float", str: "string"}
    # Reserved attribute names that cannot be treated as params even with a scalar annotation
    _RESERVED_HINT_NAMES = frozenset({
        "id", "ctx", "name", "description", "inputs", "outputs", "params",
    })
    # UnionType produced by Python 3.10+'s X | None syntax
    _UNION_TYPES = (Union, getattr(types, "UnionType", Union))

    @staticmethod
    def _resolve_hint_param_type(ann):
        """Map a single type hint to ``Param.param_type``; return None if unsupported.

        Supports ``int`` / ``float`` / ``str`` and ``Optional[X]`` / ``X | None`` wrapping a single
        scalar; returns None for ``bool`` / containers / multi-type unions.
        """
        if isinstance(ann, str):
            # Fallback when from __future__ import annotations is used and get_type_hints fails to resolve
            ann = {"int": int, "float": float, "str": str, "string": str}.get(
                ann.strip())
            if ann is None:
                return None
        if get_origin(ann) in Pipeline._UNION_TYPES:
            args = [a for a in get_args(ann) if a is not type(None)]
            if len(args) == 1:
                return Pipeline._resolve_hint_param_type(args[0])
            return None
        return Pipeline._HINT_PARAM_TYPES.get(ann)

    @staticmethod
    def _params_from_type_hints(cls, declared_inputs, declared_outputs,
                                declared_params):
        """Derive a Param list from class-level scalar type hints, in annotation declaration order.

        ``count: int = 10`` is equivalent to
        ``params = [Param("count", value=10, param_type="int")]``; when there is only an annotation
        and no default, value is None. Explicit ``params``, same-named input/output ports and
        reserved attribute names take priority and are skipped on match; unsupported annotations are
        silently ignored, and non-scalar defaults are warned and skipped.
        """
        try:
            hints = get_type_hints(cls)
        except Exception as e:
            try:
                # 3.13 and earlier: __annotations__ is a plain dict; under 3.14 PEP 649,
                # if lazy evaluation still resolves, we can get the dict here too
                hints = dict(cls.__annotations__)
            except Exception:
                # A name in an annotation cannot be resolved (e.g. an un-imported Optional) — a single bad
                # annotation should not block node registration, so warn and skip all annotated params
                print(f"[WARN] Node {cls.__name__} type annotations cannot be resolved"
                      f" ({type(e).__name__}: {e}); annotated params skipped")
                return []

        taken = {p.name for p in (declared_params or [])}
        taken.update(p.name for p in (declared_inputs or []))
        taken.update(p.name for p in (declared_outputs or []))

        class_vars = vars(cls)
        result = []
        for attr, ann in hints.items():
            if (attr.startswith("_") or attr in Pipeline._RESERVED_HINT_NAMES
                    or attr in taken):
                continue
            ptype = Pipeline._resolve_hint_param_type(ann)
            if ptype is None:
                continue
            default = class_vars[attr] if attr in class_vars else None
            if default is not None and not isinstance(default, (int, float, str, bool)):
                print(f"[WARN] Node {cls.__name__} annotated param '{attr}' has a non-scalar default"
                      f" ({type(default).__name__}); skipped")
                continue
            result.append(Param(name=attr, value=default, param_type=ptype))
        return result

    @classmethod
    def load_from_json(cls, pipeline_path: str, working_folder: str) -> "Pipeline":
        """Load and build a Pipeline instance from workspace.json.

        Workflow:
        1. Read the ``nodes`` / ``connections`` / ``globals`` sections of the JSON;
        2. Write ``globals`` into the Context as plain keys (Context is itself a dict; nodes read
           them via ``self.ctx[key]`` / ``self.ctx.get(key)``; the framework keeps no shared global cache);
        3. Instantiate each stage from ``NODE_REGISTRY`` by the ``type`` in ``nodes``:
           - node declarations (class-level ``inputs`` / ``outputs`` / ``params``) are the primary source of ports and params,
             where a param's name/type/description come entirely from the node definition and JSON can only supply value for same-named params;
           - extra input/output ports in the JSON are appended to the node (preserving frontend-custom ports),
             while extra params print [WARN] and are ignored;
           - unknown node types print [WARN] and are skipped;
        4. Build input port paths from ``connections``:
           downstream input path = the file in the upstream cache directory with the **same name as the output port**
           (``cache/{id}_{name}/{port}``; the file name is the port name and the extension is chosen by the node per data type;
           the framework never forces any extension). The load phase is lenient about connections whose node/port
           do not match (the editor may save a half-finished graph), but the raw connection table is kept intact;
        5. Record the mapping from frontend node ID to stage instance (``_node_frontend_id_map``) and the raw
           connection table (``edges``) — before execution, ``_validate_graph_and_order`` reports errors uniformly for dangling
           connections, duplicate/conflicting edges and cyclic dependencies, and performs the topological sort.

        Args:
            pipeline_path: Absolute/relative path of workspace.json.
            working_folder: Workspace root; the cache directory ``cache/`` and log directory
                ``logs/`` are created on top of it.

        Returns:
            Pipeline: A Pipeline instance assembled with nodes and connections per the JSON config.
        """
        with open(pipeline_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        nodes = data.get('nodes', [])
        connections = data.get('connections', [])
        globals_dict = data.get('globals', {})

        ctx = Context(working_folder)
        
        # Write global config into the Context as plain keys (Context is a dict;
        # nodes read them via self.ctx[key] / self.ctx.get(key); no separate shared cache)
        for key, value in globals_dict.items():
            ctx[key] = value

        node_instances = {}
        unregistered: Dict[Any, str] = {}

        for i, node_def in enumerate(nodes, 1):
            node_type = node_def.get('type')
            if node_type not in cls.NODE_REGISTRY:
                print(f"[WARN] Unknown node type: {node_type}, skipping")
                unregistered[node_def.get('id')] = node_type
                continue

            node_cls = cls.NODE_REGISTRY[node_type]
            instance = node_cls(ctx)
            instance.id = i

            instance.description = node_def.get('description', '')

            # --- Update existing declarative inputs (append new if missing) ---
            declared_input_names = {p.name for p in instance.inputs}
            for inp in node_def.get('inputs', []):
                name = inp.get('name', '')
                existing = next((p for p in instance.inputs if p.name == name), None)
                if existing:
                    existing.description = inp.get('description', existing.description)
                else:
                    instance.inputs.append(Input(
                        name=name,
                        description=inp.get('description', '')
                    ))

            # --- Update existing declarative outputs (append new if missing) ---
            declared_output_names = {p.name for p in instance.outputs}
            for outp in node_def.get('outputs', []):
                name = outp.get('name', '')
                existing = next((p for p in instance.outputs if p.name == name), None)
                if existing:
                    existing.description = outp.get('description', existing.description)
                else:
                    instance.outputs.append(Output(
                        name=name,
                        description=outp.get('description', '')
                    ))

            # --- Params: the node definition takes precedence; workspace.json only supplies user-entered values ---
            # Param name/type/description come from the registered class (explicit params or type hints);
            # extra params in the JSON (e.g. hand-added by old versions) are ignored with a warning and no longer dynamically appended.
            for param in node_def.get('customParams', []):
                name = param.get('name', '')
                existing = next((p for p in instance.params if p.name == name), None)
                if existing:
                    if 'value' in param and param['value'] is not None:
                        existing.value = param['value']
                elif name:
                    print(f"[WARN] Node {node_type} does not define param '{name}', ignored "
                          f"(params are governed by the node's Python definition; workspace.json can only assign values)")

            node_instances[node_def['id']] = instance

        for conn in connections:
            from_node_id = conn.get('from', {}).get('node')
            from_port = conn.get('from', {}).get('port')
            to_node_id = conn.get('to', {}).get('node')
            to_port = conn.get('to', {}).get('port')

            if from_node_id not in node_instances or to_node_id not in node_instances:
                continue

            from_instance = node_instances[from_node_id]
            to_instance = node_instances[to_node_id]

            # Downstream input path = the real location of the upstream output file; the file name matches the output port name
            # (nodes write via cache_path(port_name), and the file extension is chosen by the node per data type,
            #   possibly pickle/json/csv — the framework must not force .csv, or non-CSV ports would inevitably mismatch).
            output_path = os.path.join(
                ctx.working_folder, 'cache',
                f"{from_instance.id}_{from_instance.name}",
                f"{from_port}"
            )

            input_port = to_instance.get_input(to_port)
            if input_port:
                input_port.path = output_path

        stages = list(node_instances.values())
        pipeline = cls(stages, working_folder)
        # Save the mapping from frontend node ID to stage instance
        pipeline._node_frontend_id_map = {nid: inst for nid, inst in node_instances.items()}
        # Record nodes with unregistered types that could not be instantiated, so pre-execution validation can report accurately
        pipeline.unregistered_nodes = unregistered
        # Save the raw connection table for pre-execution dangling/duplicate-edge/cycle validation and topological sort
        pipeline.edges = connections
        return pipeline
