import os
import json
import csv
import shutil
import datetime
import sys
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
    1. 加载工作目录配置（从 pipeline.json 或使用默认配置）
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
            working_folder: 工作目录路径，可包含 pipeline.json 文件（可选）
            force: 是否强制重新执行（默认 False，即使用缓存）
        """
        self.working_folder = working_folder
        self.force = force
        
        # 尝试加载 pipeline.json 配置（可选）
        cfg = {}
        pipeline_path = os.path.join(working_folder, "pipeline.json")
        if os.path.isfile(pipeline_path):
            try:
                with open(pipeline_path, "r", encoding="utf-8") as f:
                    pipeline_data = json.load(f)
                    # 提取 globals 配置，后续会单独处理
                    cfg.update(pipeline_data.get('globals', {}))
            except Exception as e:
                print(f"[WARN] Failed to load pipeline.json: {e}")
        
        # 设置工作目录的绝对路径
        cfg["working_folder"] = os.path.abspath(working_folder)
        
        # 创建上下文对象
        self.ctx = Context(**cfg)
        
        # 如果 pipeline.json 包含 globals，已经通过构造参数注入到 Context dict 中
        
        # 将 stages 转换为列表，确保可多次迭代
        self.stages = list(stages)

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

    def clean(self):
        """
        清理项目：删除工作目录下除 config.json 之外的所有内容
        """
        if not os.path.isdir(self.working_folder):
            print(f"[INFO] {self.working_folder} not found, skipped")
            return
        for entry in os.listdir(self.working_folder):
            if entry == "config.json":
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
        """Decorator to register a CachedSubprocess subclass."""
        Pipeline.NODE_REGISTRY[cls.__name__] = cls
        return cls

    @classmethod
    def load_from_json(cls, pipeline_path: str, working_folder: str) -> "Pipeline":
        """Load pipeline stages from a pipeline.json file."""
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
        node_id_map = {}

        for i, node_def in enumerate(nodes, 1):
            node_type = node_def.get('type')
            if node_type not in cls.NODE_REGISTRY:
                print(f"[WARN] Unknown node type: {node_type}, skipping")
                continue

            node_cls = cls.NODE_REGISTRY[node_type]
            instance = node_cls(ctx)
            instance.id = i

            instance.description = node_def.get('description', '')

            for param in node_def.get('customParams', []):
                p = next((x for x in instance.params if x.name == param.get('name')), None)
                if p:
                    p.value = param.get('value')

            instance.inputs = []
            for inp in node_def.get('inputs', []):
                instance.inputs.append(Input(
                    name=inp.get('name', ''),
                    description=inp.get('description', '')
                ))

            instance.outputs = []
            for outp in node_def.get('outputs', []):
                instance.outputs.append(Output(
                    name=outp.get('name', ''),
                    description=outp.get('description', '')
                ))

            instance.params = []
            for param in node_def.get('customParams', []):
                instance.params.append(Param(
                    name=param.get('name', ''),
                    value=param.get('value')
                ))

            node_instances[node_def['id']] = instance
            node_id_map[node_def['id']] = i

        for conn in connections:
            from_node_id = conn.get('from', {}).get('node')
            from_port = conn.get('from', {}).get('port')
            to_node_id = conn.get('to', {}).get('node')
            to_port = conn.get('to', {}).get('port')

            if from_node_id not in node_instances or to_node_id not in node_instances:
                continue

            from_instance = node_instances[from_node_id]
            to_instance = node_instances[to_node_id]
            from_id = node_id_map[from_node_id]

            output_path = os.path.join(
                ctx.working_folder, 'cache',
                f"{from_id}_{from_instance.name}",
                f"{from_port}.csv"
            )

            input_port = to_instance.get_input(to_port)
            if input_port:
                input_port.path = output_path

        stages = list(node_instances.values())
        return cls(stages, working_folder)
