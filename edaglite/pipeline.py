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
    """执行上下文：跨节点共享的键值存储 + 工作目录定位。

    Context 本身就是一个 dict：workspace.json 的 ``globals`` 与
    ``working_folder`` 都以普通键值存入，节点通过 ``self.ctx[key]`` /
    ``self.ctx.get(key)`` 直接读取，框架不再维护任何独立的全局共享缓存。
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

        # —— 记录输入/输出引用的实际文件名（含扩展名），防止引用错文件 ——
        # 输入文件名 = 上游输出端口名（框架连接时按此解析），端口名可自带扩展名（如 xxx.csv）；
        # 输出文件按 cache_path(port_name) 解析，真实扩展名以写入后的磁盘文件为准。
        for p in self.inputs:
            if p.path and not os.path.exists(p.path):
                folder = os.path.dirname(p.path)
                present = [f for f in os.listdir(folder)] if os.path.isdir(folder) else []
                print(f"    [WARN] 输入 {p.name} 引用文件不存在: {p.path}"
                      + (f"，缓存目录实际文件: {present}" if present else ""))
        inputs_desc = "; ".join(
            f"{p.name}={os.path.basename(p.path)}" if p.path else f"{p.name}=(未连接)"
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
            # 执行完毕后记录缓存目录中实际生成的文件（含扩展名），供核对是否写错
            actual = [f for f in os.listdir(cache_dir) if os.path.isfile(os.path.join(cache_dir, f))]
            if actual:
                print(f"    [FILES] 实际输出: {', '.join(actual)}")


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
                    # globals 作为普通键值并入 cfg，随后随 Context(**cfg) 落入 Context dict
                    cfg.update(pipeline_data.get('globals', {}))
            except Exception as e:
                print(f"[WARN] Failed to load workspace.json: {e}")
        
        # 设置工作目录的绝对路径
        cfg["working_folder"] = os.path.abspath(working_folder)
        
        # 创建上下文对象（Context 是 dict，globals 可由节点通过 ctx.get(key) 读取）
        self.ctx = Context(**cfg)
        
        # 将 stages 转换为列表，确保可多次迭代
        self.stages = list(stages)

        # 前端节点ID到 stage 实例的映射（用于运行单个节点）
        self._node_frontend_id_map: Dict[str, 'CachedSubprocess'] = {}

        # 原始连接表（load_from_json 填充），供执行前图校验与拓扑排序使用
        self.edges: List[dict] = []

        # 未注册节点类型：前端节点ID -> 节点类型名（load_from_json 填充）。
        # 这些节点因类型不在 NODE_REGISTRY 中而无法实例化，图校验与单节点
        # 执行据此给出"类型未注册"的准确报错，而非笼统的"节点不存在"。
        self.unregistered_nodes: Dict[Any, str] = {}

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
        4. 执行前校验连接图（悬空连接 / 重复或冲突边 / 环形依赖），并按拓扑序排列节点；
           声明顺序合法时执行序与声明序一致，乱序时自动重排
        5. 按拓扑序执行每个阶段
        6. 输出完成信息
        7. 恢复原始 stdout
        
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

                # 执行前图校验（悬空连接 / 重复边 / 环形依赖）并得到拓扑序
                ordered_stages = self._validate_graph_and_order()
                if ordered_stages != self.stages:
                    print("[INFO] 节点声明顺序不是拓扑序，已按依赖关系自动重排执行")

                # 输出阶段列表
                print("[INFO] Stages to execute:")
                for i, stage in enumerate(ordered_stages, 1):
                    print(f"  {i}. {stage.name}")
                print("=" * 80)

                # 按拓扑序执行所有阶段
                print("[INFO] Executing stages:")
                for i, stage in enumerate(ordered_stages, 1):
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
            if node_id in self.unregistered_nodes:
                raise ValueError(
                    f"Node '{node_id}' 的类型 '{self.unregistered_nodes[node_id]}' "
                    f"未注册，无法单独执行；请确认启动前已 import 该节点的 Python 定义")
            available_ids = ", ".join(map(str, self._node_frontend_id_map.keys()))
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
                # 确保恢复 stdout
                sys.stdout = self.original_stdout
                print(f"[INFO] Log saved to: {self.log_file}")

    def _validate_graph_and_order(self) -> List["CachedSubprocess"]:
        """执行前校验连接图并返回按拓扑序排列的节点。

        校验三类非法图（任一失败即抛 ValueError 中止执行，不再静默忽略）：

        1. **悬空连接**：边引用的节点不存在，或引用的输出/输入端口在节点上
           不存在（例如节点类型已改但画布还留着旧连线）；
        2. **重复/冲突边**：完全相同的连接出现多次；或同一个输入端口被两个
           不同的上游输出连接（此前后者会被最后一条边静默覆盖）；
        3. **环形依赖**：图中存在环，无法确定执行顺序，报错并列出环上节点。

        Returns:
            按拓扑序（上游在前）排列的 stage 列表。采用稳定策略——每轮选取
            声明顺序最靠前的"就绪"节点，因此当 nodes 声明顺序本身就是合法
            拓扑序时（如 demo），执行顺序与以前完全一致；仅在声明乱序时才
            自动重排。直接用代码构造、未经 load_from_json 装配的 Pipeline
            没有边表，原样返回 ``self.stages``。

        Raises:
            ValueError: 图校验失败时抛出，消息指明具体的非法连接或环上节点。
        """
        # 直接代码构造的 Pipeline 没有前端 ID 映射与边表，保持线性执行
        if not self._node_frontend_id_map:
            return list(self.stages)

        fid_map = self._node_frontend_id_map

        # 图中存在类型未注册的节点（即使没有连线）时无法完整执行，显式报错
        if self.unregistered_nodes:
            detail = ", ".join(
                f"ID={fid}({ntype})" for fid, ntype in self.unregistered_nodes.items())
            raise ValueError(
                f"存在未注册的节点类型，无法执行：{detail}；"
                f"请确认启动前已 import 这些节点的 Python 定义（@Pipeline.register_node）")

        decl_order = list(fid_map.keys())  # fid_map 按 nodes 数组顺序插入

        adjacency: Dict[Any, List[Any]] = {fid: [] for fid in decl_order}
        indegree: Dict[Any, int] = {fid: 0 for fid in decl_order}
        seen_edges = set()
        input_sources: Dict[tuple, tuple] = {}

        for conn in self.edges:
            from_fid = conn.get('from', {}).get('node')
            from_port = conn.get('from', {}).get('port')
            to_fid = conn.get('to', {}).get('node')
            to_port = conn.get('to', {}).get('port')

            # —— 1a. 悬空：引用的节点不存在（区分"类型未注册"与"ID 不存在"） ——
            if from_fid not in fid_map:
                if from_fid in self.unregistered_nodes:
                    raise ValueError(
                        f"节点（ID={from_fid}）的类型 "
                        f"'{self.unregistered_nodes[from_fid]}' 未注册，无法执行；"
                        f"请确认启动前已 import 该节点的 Python 定义"
                        f"（连线：{from_fid}.{from_port} -> {to_fid}.{to_port}）")
                raise ValueError(
                    f"非法连接：起点节点 '{from_fid}' 不存在"
                    f"（{from_fid}.{from_port} -> {to_fid}.{to_port}），请删除画布上的悬空连线")
            if to_fid not in fid_map:
                if to_fid in self.unregistered_nodes:
                    raise ValueError(
                        f"节点（ID={to_fid}）的类型 "
                        f"'{self.unregistered_nodes[to_fid]}' 未注册，无法执行；"
                        f"请确认启动前已 import 该节点的 Python 定义"
                        f"（连线：{from_fid}.{from_port} -> {to_fid}.{to_port}）")
                raise ValueError(
                    f"非法连接：终点节点 '{to_fid}' 不存在"
                    f"（{from_fid}.{from_port} -> {to_fid}.{to_port}），请删除画布上的悬空连线")

            from_inst = fid_map[from_fid]
            to_inst = fid_map[to_fid]

            # —— 1b. 悬空：引用的端口不存在 ——
            if from_inst.get_output(from_port) is None:
                raise ValueError(
                    f"非法连接：节点 '{from_inst.name}' 上不存在输出端口 '{from_port}'"
                    f"（-> {to_inst.name}.{to_port}）")
            if to_inst.get_input(to_port) is None:
                raise ValueError(
                    f"非法连接：节点 '{to_inst.name}' 上不存在输入端口 '{to_port}'"
                    f"（{from_inst.name}.{from_port} ->）")

            # —— 2a. 完全重复的边 ——
            edge_key = (from_fid, from_port, to_fid, to_port)
            if edge_key in seen_edges:
                raise ValueError(
                    f"重复连接：{from_inst.name}.{from_port} -> "
                    f"{to_inst.name}.{to_port} 出现了多次，请只保留一条")
            seen_edges.add(edge_key)

            # —— 2b. 同一输入端口被多个上游连接（多生产者冲突） ——
            port_key = (to_fid, to_port)
            prev = input_sources.get(port_key)
            if prev is not None:
                prev_fid, prev_port = prev
                raise ValueError(
                    f"输入端口冲突：'{to_inst.name}.{to_port}' 同时连接了 "
                    f"'{fid_map[prev_fid].name}.{prev_port}' 与 "
                    f"'{from_inst.name}.{from_port}'，一个输入端口只能有一个上游")
            input_sources[port_key] = (from_fid, from_port)

            adjacency[from_fid].append(to_fid)
            indegree[to_fid] += 1

        # —— 3. Kahn 拓扑排序；稳定策略：每轮取声明顺序最靠前的零入度节点 ——
        # 节点规模通常只有几十个，O(N²) 的全表扫描换取"合法声明序 == 执行序"
        # 的稳定语义，避免无谓重排。
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
                    f"检测到环形依赖，无法确定执行顺序。成环节点（或其下游）：{cycle_names}")
            remaining.discard(picked)
            ordered.append(picked)
            for nxt in adjacency[picked]:
                work_indegree[nxt] -= 1

        return [fid_map[fid] for fid in ordered]

    def clean(self):
        """
        清理工作目录下的缓存与日志（白名单方式：只删 ``cache/`` 和 ``logs/``）。

        仅删除框架自身产生的两个目录，工作区中的节点脚本、workspace.json、
        nodes.json 及其他任何用户文件都不会被触碰——避免黑名单式删除在
        working_folder 传错时误删用户数据。
        """
        if not os.path.isdir(self.working_folder):
            print(f"[INFO] {self.working_folder} not found, skipped")
            return
        # 白名单：只有框架自己产出的目录才允许删除
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

    # 节点类型注册表：节点类型 id -> 类对象
    # id 默认为类名，可通过 @Pipeline.register_node(node_id=...) 自定义
    NODE_REGISTRY: Dict[str, type] = {}

    @staticmethod
    def register_node(cls=None, *, node_id=None, name=None, icon=None,
                      group=None, description=None):
        """Register a CachedSubprocess subclass, with optional UI metadata.

        Can be used bare (``@Pipeline.register_node``) or parameterised
        (``@Pipeline.register_node(icon="🎓", name="展示名")``). The optional
        metadata is consumed by the visual editor's node palette only — it
        never affects execution or cache paths:

        - ``node_id``: registry key / 节点类型 id，面板与 workspace.json 用它
          定位类型；默认取类名。自定义后旧 workspace.json 中的旧类型名会被
          视为未注册。
        - ``name``: 面板展示名，默认同 node_id。
        - ``icon`` / ``group`` / ``description``: 面板图标、分组与描述；
          description 缺省时面板回退到类 docstring 首行。

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
            # 纯面板元数据（不参与执行）；viewer 反射时读取
            cls._node_meta = {
                "id": type_id,
                "name": str(name) if name else type_id,
                "icon": icon or "",
                "group": group or "",
                "description": description or "",
            }
            return Pipeline._register_node_traits(cls, type_id)

        # 裸装饰器用法 @Pipeline.register_node：第一个位置参数就是类
        if cls is not None:
            return decorator(cls)
        # 工厂用法 @Pipeline.register_node(icon=...)：返回真正的装饰器
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
        # 类级标量类型注解推导参数（int/float/str，含 Optional 包装）
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
            # 注解参数排在显式声明之后；同名（含 __init__ 动态添加）不覆盖
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

    # 标量类型注解 -> Param.param_type 白名单（bool 不支持：前端无对应控件）
    _HINT_PARAM_TYPES = {int: "int", float: "float", str: "string"}
    # 即使写了标量注解也不能当作参数的保留属性名
    _RESERVED_HINT_NAMES = frozenset({
        "id", "ctx", "name", "description", "inputs", "outputs", "params",
    })
    # Python 3.10+ 的 X | None 语法产生的 UnionType
    _UNION_TYPES = (Union, getattr(types, "UnionType", Union))

    @staticmethod
    def _resolve_hint_param_type(ann):
        """把单个类型注解映射为 ``Param.param_type``；不支持时返回 None。

        支持 ``int`` / ``float`` / ``str`` 以及仅包一个标量的
        ``Optional[X]`` / ``X | None``；``bool`` / 容器 / 多类型联合返回 None。
        """
        if isinstance(ann, str):
            # from __future__ import annotations 且 get_type_hints 解析失败时的兜底
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
        """从类级标量类型注解推导 Param 列表，顺序与注解声明顺序一致。

        ``count: int = 10`` 等价于
        ``params = [Param("count", value=10, param_type="int")]``；只有注解
        没有默认值时 value 为 None。显式 ``params``、同名输入/输出端口以及
        保留属性名优先，命中即跳过；不支持的注解静默忽略，非标量默认值告警跳过。
        """
        try:
            hints = get_type_hints(cls)
        except Exception as e:
            try:
                # 3.13 及更早：__annotations__ 是普通 dict；3.14 PEP 649 下
                # 若延迟求值仍可解析，这里同样能拿到 dict
                hints = dict(cls.__annotations__)
            except Exception:
                # 存在无法解析的注解名（如未导入的 Optional）——单个坏注解
                # 不应阻断节点注册，告警后跳过全部注解参数
                print(f"[WARN] 节点 {cls.__name__} 的类型注解无法解析"
                      f"（{type(e).__name__}: {e}），已跳过注解参数")
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
                print(f"[WARN] 节点 {cls.__name__} 的注解参数 '{attr}' 默认值不是标量"
                      f"（{type(default).__name__}），已跳过")
                continue
            result.append(Param(name=attr, value=default, param_type=ptype))
        return result

    @classmethod
    def load_from_json(cls, pipeline_path: str, working_folder: str) -> "Pipeline":
        """从 workspace.json 加载并构建 Pipeline 实例。

        工作流程：
        1. 读取 JSON 中的 ``nodes`` / ``connections`` / ``globals`` 三个部分；
        2. 将 ``globals`` 以普通键值写入 Context（Context 本身是 dict，节点通过
           ``self.ctx[key]`` / ``self.ctx.get(key)`` 读取，框架不维护全局共享缓存）；
        3. 按 ``nodes`` 中的 ``type`` 从 ``NODE_REGISTRY`` 实例化每个 stage：
           - 节点声明（类级 ``inputs`` / ``outputs`` / ``params``）为端口与参数的主体，
             其中参数的名称/类型/描述完全由节点定义，JSON 只能为同名参数提供 value；
           - JSON 中多出的输入/输出端口会被追加到节点上（此前端自定义端口保留），
             多出的参数则打印 [WARN] 并忽略；
           - 未知节点类型打印 [WARN] 并跳过；
        4. 根据 ``connections`` 建立输入端口路径：
           下游输入路径 = 上游缓存目录中与**输出端口名同名**的文件
           （``cache/{id}_{name}/{port}``，文件名即端口名，扩展名由节点按数据类型自定，
           框架不强制拼任何扩展名）。加载阶段对节点/端口不匹配的连线保持宽容
           （编辑器可能保存半成品图），但原始连接表会被完整保留；
        5. 记录前端节点 ID 与 stage 实例的映射（``_node_frontend_id_map``）与原始
           连接表（``edges``）——执行前由 ``_validate_graph_and_order`` 对悬空连接、
           重复/冲突边、环形依赖统一报错并做拓扑排序。

        Args:
            pipeline_path: workspace.json 的绝对/相对路径。
            working_folder: 工作区根目录，缓存目录 ``cache/`` 与日志目录
                ``logs/`` 均在此基础上创建。

        Returns:
            Pipeline: 按 JSON 配置组装好节点与连接的 Pipeline 实例。
        """
        with open(pipeline_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        nodes = data.get('nodes', [])
        connections = data.get('connections', [])
        globals_dict = data.get('globals', {})

        ctx = Context(working_folder)
        
        # 将全局配置以普通键值写入 Context（Context 是 dict，
        # 节点通过 self.ctx[key] / self.ctx.get(key) 读取，无独立共享缓存）
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

            # --- Params: 以节点定义为准，workspace.json 只提供用户填写的值 ---
            # 参数名/类型/描述来自注册类（显式 params 或类型注解）；JSON 中
            # 多出的参数（如旧版手工添加的）忽略并告警，不再动态追加。
            for param in node_def.get('customParams', []):
                name = param.get('name', '')
                existing = next((p for p in instance.params if p.name == name), None)
                if existing:
                    if 'value' in param and param['value'] is not None:
                        existing.value = param['value']
                elif name:
                    print(f"[WARN] 节点 {node_type} 未定义参数 '{name}'，已忽略 "
                          f"（参数以节点 Python 定义为准，workspace.json 只能赋值）")

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

            # 下游输入路径 = 上游输出文件的真实位置，文件名与输出端口名保持一致
            # （节点通过 cache_path(port_name) 写出，文件扩展名由节点按数据类型自定，
            #   可能是 pickle/json/csv —— 框架不得强制拼 .csv，否则非 CSV 端口必然错位）。
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
        # 保存前端节点ID到 stage 实例的映射
        pipeline._node_frontend_id_map = {nid: inst for nid, inst in node_instances.items()}
        # 记录类型未注册、未能实例化的节点，供执行前校验给出准确报错
        pipeline.unregistered_nodes = unregistered
        # 保存原始连接表，供执行前的悬空/重复边/环校验与拓扑排序使用
        pipeline.edges = connections
        return pipeline
