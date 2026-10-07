import os
import json
import csv
import shutil
import datetime
import sys
import inspect
import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Callable, Any, List, Optional, Literal
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
    """Cross-stage file resolver + source files container"""

    _id_counter = 0

    def __init__(self, working_folder: str, **kwargs):
        super().__init__(**kwargs)
        self.working_folder = working_folder
        self['working_folder'] = working_folder
        os.makedirs(working_folder, exist_ok=True)
        self._shared_cache = {}

    @classmethod
    def generate_id(cls) -> int:
        cls._id_counter += 1
        return cls._id_counter

    def shared_cache_path(self, name: str) -> str:
        return os.path.join(self.working_folder, 'cache', name)

    def shared_cache_folder(self) -> str:
        return os.path.join(self.working_folder, 'cache')

    def set_shared(self, key: str, value):
        self._shared_cache[key] = value

    def get_shared(self, key: str, default=None):
        return self._shared_cache.get(key, default)


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

    def get_shared(self, key: str, default=None):
        """Get shared global value from context."""
        return self.ctx.get_shared(key, default)
    
    def set_shared(self, key: str, value):
        """Set shared global value to context."""
        self.ctx.set_shared(key, value)

    def run(self, force: bool = False):
        """Execute the stage with caching support."""
        cache_dir = self.cache_folder()
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

        cached_outputs = [f for f in os.listdir(cache_dir) if os.path.isfile(os.path.join(cache_dir, f))]
        all_cached = not force and len(cached_outputs) > 0
        
        if all_cached:
            print(f'[SKIP] {self.name} cached - skipped')
        else:
            print(f'[EXEC] {self.name} executing...')
            self._execute()
            print(f'[DONE] {self.name} finished')


class Pipeline:
    """
    管道执行器类，负责管理和执行一系列 CachedSubprocess 阶段。
    
    Pipeline 是整个工作流的核心控制器，负责：
    1. 加载工作目录配置（从 workspace.json 或使用默认配置）
    2. 管理执行上下文 (Context)
    3. 按顺序执行所有阶段
    4. 记录执行日志到文件和控制台
    
    Attributes:
        working_folder: 工作目录路径，包含配置文件和输出目录
        force: 是否强制重新执行所有阶段（跳过缓存检查）
        ctx: 上下文对象，存储共享配置和状态
        stages: CachedSubprocess 实例列表，表示执行阶段
        log_dir: 日志目录路径
        log_file: 当前执行的日志文件路径
        original_stdout: 原始 stdout，用于执行完毕后恢复
    """

    def __init__(self, stages, working_folder: str, force: bool = False):
        """
        初始化 Pipeline 实例
        
        Args:
            stages: CachedSubprocess 实例的可迭代对象，按执行顺序排列
            working_folder: 工作目录路径，可包含 workspace.json 文件（可选）
            force: 是否强制重新执行（默认 False，即使用缓存）
        """
        self.working_folder = working_folder
        self.force = force
        
        # 尝试加载 workspace.json 配置（可选）
        cfg = {}
        pipeline_path = os.path.join(working_folder, "workspace.json")
        if os.path.isfile(pipeline_path):
            try:
                with open(pipeline_path, "r", encoding="utf-8") as f:
                    pipeline_data = json.load(f)
                    # 提取 globals 配置，后续会单独处理
                    cfg.update(pipeline_data.get('globals', {}))
            except Exception as e:
                print(f"[WARN] Failed to load workspace.json: {e}")
        
        # 设置工作目录的绝对路径
        cfg["working_folder"] = os.path.abspath(working_folder)
        
        # 创建上下文对象
        self.ctx = Context(**cfg)
        
        # 如果 workspace.json 包含 globals，已经通过构造参数注入到 Context dict 中
        
        # 将 stages 转换为列表，确保可多次迭代
        self.stages = list(stages)

        # 前端节点ID到 stage 实例的映射（用于运行单个节点）
        self._node_frontend_id_map: Dict[str, 'CachedSubprocess'] = {}

        # 创建日志目录
        self.log_dir = os.path.join(working_folder, "logs")
        os.makedirs(self.log_dir, exist_ok=True)

        # 创建带时间戳的日志文件
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(self.log_dir, f"pipeline_{timestamp}.log")
        
        # 保存原始 stdout，用于后续恢复
        self.original_stdout = sys.stdout

    def run(self):
        """
        执行整个 Pipeline 的所有阶段
        
        执行流程：
        1. 创建 Tee 对象，将输出同时写入控制台和日志文件
        2. 重定向 stdout 到 Tee 对象
        3. 输出执行信息（开始时间、工作目录、强制模式、阶段列表）
        4. 按顺序执行每个阶段
        5. 输出完成信息
        6. 恢复原始 stdout
        
        日志文件会保存在 working_folder/logs/pipeline_YYYYMMDD_HHMMSS.log
        """
        # 打开日志文件并设置输出重定向
        with open(self.log_file, 'w', encoding='utf-8') as f:
            # 定义 Tee 类：将输出同时写入多个流（控制台 + 文件）
            class Tee:
                def __init__(self, *files):
                    """初始化 Tee 对象，接受多个文件对象"""
                    self.files = files
                
                def write(self, data):
                    """写入数据到所有文件，并立即刷新"""
                    for file in self.files:
                        file.write(data)
                        file.flush()
                
                def flush(self):
                    """刷新所有文件缓冲区"""
                    for file in self.files:
                        file.flush()

            # 将 stdout 重定向到 Tee（同时输出到控制台和日志文件）
            sys.stdout = Tee(self.original_stdout, f)

            try:
                # 输出执行开始信息
                print(f"[INFO] Pipeline started at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"[INFO] Working folder: {self.working_folder}")
                print(f"[INFO] Force mode: {self.force}")
                print(f"[INFO] Log file: {self.log_file}")
                print("=" * 80)

                # 输出阶段列表
                print("[INFO] Stages to execute:")
                for i, stage in enumerate(self.stages, 1):
                    print(f"  {i}. {stage.name}")
                print("=" * 80)

                # 按顺序执行所有阶段
                print("[INFO] Executing stages:")
                for i, stage in enumerate(self.stages, 1):
                    print(f"\n--- Stage {i}: {stage.name} ---")
                    stage.run(force=self.force)

                # 输出完成信息
                print("\n" + "=" * 80)
                print("[INFO] Pipeline finished - all stages done")
                print(f"[INFO] Pipeline completed at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            finally:
                # 确保恢复原始 stdout
                sys.stdout = self.original_stdout
                print(f"[INFO] Log saved to: {self.log_file}")

    def run_stage(self, name: str):
        """
        启动指定名称的一个 subprocess（阶段），并将输出同时写入控制台和日志文件

        Args:
            name: 阶段名称（对应 CachedSubprocess.name）

        Raises:
            ValueError: 当找不到指定名称的阶段时抛出
        """
        stage = next((s for s in self.stages if s.name == name), None)
        if stage is None:
            available = ", ".join(s.name for s in self.stages)
            raise ValueError(f"Stage '{name}' not found. Available stages: {available}")

        # 打开日志文件并设置输出重定向
        with open(self.log_file, 'w', encoding='utf-8') as f:
            # 定义 Tee 类：将输出同时写入多个流（控制台 + 文件）
            class Tee:
                def __init__(self, *files):
                    """初始化 Tee 对象，接受多个文件对象"""
                    self.files = files

                def write(self, data):
                    """写入数据到所有文件，并立即刷新"""
                    for file in self.files:
                        file.write(data)
                        file.flush()

                def flush(self):
                    """刷新所有文件缓冲区"""
                    for file in self.files:
                        file.flush()

            # 将 stdout 重定向到 Tee（同时输出到控制台和日志文件）
            sys.stdout = Tee(self.original_stdout, f)

            try:
                # 输出执行开始信息
                print(f"[INFO] Pipeline started at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"[INFO] Working folder: {self.working_folder}")
                print(f"[INFO] Force mode: {self.force}")
                print(f"[INFO] Log file: {self.log_file}")
                print("=" * 80)

                # 执行指定阶段
                print(f"[INFO] Running stage: {name}")
                print(f"\n--- Stage: {stage.name} ---")
                stage.run(force=self.force)

                # 输出完成信息
                print("\n" + "=" * 80)
                print(f"[INFO] Stage '{name}' finished")
                print(f"[INFO] Pipeline completed at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            finally:
                # 确保恢复原始 stdout
                sys.stdout = self.original_stdout
                print(f"[INFO] Log saved to: {self.log_file}")

    def run_node_by_frontend_id(self, node_id: str):
        """
        启动指定前端ID的单个节点，并将输出同时写入控制台和日志文件

        Args:
            node_id: 前端节点ID（对应前端 nodes 数组中的 id 字段）

        Raises:
            ValueError: 当找不到指定ID的节点时抛出
        """
        stage = self._node_frontend_id_map.get(node_id)
        if stage is None:
            available_ids = ", ".join(self._node_frontend_id_map.keys())
            raise ValueError(f"Node '{node_id}' not found. Available IDs: {available_ids}")

        # 打开日志文件并设置输出重定向
        with open(self.log_file, 'w', encoding='utf-8') as f:
            # 定义 Tee 类：将输出同时写入多个流（控制台 + 文件）
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

            # 将 stdout 重定向到 Tee（同时输出到控制台和日志文件）
            sys.stdout = Tee(self.original_stdout, f)

            try:
                # 输出执行开始信息
                print(f"[INFO] Pipeline started at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"[INFO] Working folder: {self.working_folder}")
                print(f"[INFO] Force mode: {self.force}")
                print(f"[INFO] Log file: {self.log_file}")
                print("=" * 80)

                # 执行指定节点
                print(f"[INFO] Running single node: {stage.name} (frontend ID: {node_id})")
                print(f"\n--- Stage: {stage.name} ---")
                stage.run(force=self.force)

                # 输出完成信息
                print("\n" + "=" * 80)
                print(f"[INFO] Node '{stage.name}' finished")
                print(f"[INFO] Pipeline completed at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            finally:
                # 确保恢复原始 stdout
                sys.stdout = self.original_stdout
                print(f"[INFO] Log saved to: {self.log_file}")

    def clean(self):
        """
        清理项目：删除工作目录下除 nodes.json 和 workspace.json 之外的所有内容
        """
        if not os.path.isdir(self.working_folder):
            print(f"[INFO] {self.working_folder} not found, skipped")
            return
        keep = {"nodes.json", "workspace.json"}
        for entry in os.listdir(self.working_folder):
            if entry in keep:
                continue
            target = os.path.join(self.working_folder, entry)
            if os.path.isdir(target):
                shutil.rmtree(target)
            else:
                os.remove(target)
            print(f"[INFO] Removed {target}")

    # 节点类型注册表：节点类名 -> 类对象
    NODE_REGISTRY: Dict[str, type] = {}

    @staticmethod
    def register_node(cls):
        """Decorator to register a CachedSubprocess subclass with trait injection.

        Supports two convenience features:

        1. Class-level declarative traits:
           Declare ``inputs`` / ``outputs`` / ``params`` as class attributes and
           they will be deep-copied into each instance automatically, so you do
           not need to assign them inside ``__init__``.

        2. Simplified ``__init__`` signature:
           You may write ``def __init__(self, ctx):`` without the ``id``
           parameter.  The decorator normalises the signature so the class is
           still constructible as ``Cls(ctx, id=...)`` / ``Cls(ctx)``.

        Example::

            @Pipeline.register_node
            class CloneSolution(CachedSubprocess):
                inputs = [Input("solution_json")]
                outputs = [Output("clones")]
                params = [Param("multiplier", value=1, param_type="int")]

                def __init__(self, ctx):
                    super().__init__(ctx)
        """
        if not issubclass(cls, CachedSubprocess):
            raise TypeError(
                f"@Pipeline.register_node can only decorate CachedSubprocess "
                f"subclasses, got {cls.__name__}"
            )

        # ---- Collect class-level declarative traits -------------------------
        # Use vars(cls) instead of getattr so we only pick *direct* class
        # attributes and don't accidentally pull them from CachedSubprocess.
        declared_inputs = vars(cls).get("inputs", None)
        declared_outputs = vars(cls).get("outputs", None)
        declared_params = vars(cls).get("params", None)

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
        Pipeline.NODE_REGISTRY[cls.__name__] = cls
        return cls

    @classmethod
    def load_from_json(cls, pipeline_path: str, working_folder: str) -> "Pipeline":
        """Load pipeline stages from a workspace.json file."""
        with open(pipeline_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        nodes = data.get('nodes', [])
        connections = data.get('connections', [])
        globals_dict = data.get('globals', {})

        ctx = Context(working_folder)
        
        # 将全局配置写入 Context 的共享缓存
        for key, value in globals_dict.items():
            ctx.set_shared(key, value)

        node_instances = {}

        for i, node_def in enumerate(nodes, 1):
            node_type = node_def.get('type')
            if node_type not in cls.NODE_REGISTRY:
                print(f"[WARN] Unknown node type: {node_type}, skipping")
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

            # --- Update existing declarative params (append new if missing) ---
            for param in node_def.get('customParams', []):
                name = param.get('name', '')
                existing = next((p for p in instance.params if p.name == name), None)
                if existing:
                    if 'value' in param and param['value'] is not None:
                        existing.value = param['value']
                    if 'description' in param:
                        existing.description = param['description']
                    if 'param_type' in param:
                        existing.param_type = param['param_type']
                else:
                    instance.params.append(Param(
                        name=name,
                        description=param.get('description', ''),
                        value=param.get('value'),
                        param_type=param.get('param_type', 'string')
                    ))

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

            output_path = os.path.join(
                ctx.working_folder, 'cache',
                f"{from_instance.id}_{from_instance.name}",
                f"{from_port}.csv"
            )

            input_port = to_instance.get_input(to_port)
            if input_port:
                input_port.path = output_path

        stages = list(node_instances.values())
        pipeline = cls(stages, working_folder)
        # 保存前端节点ID到 stage 实例的映射
        pipeline._node_frontend_id_map = {nid: inst for nid, inst in node_instances.items()}
        return pipeline
