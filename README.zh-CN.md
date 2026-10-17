# edaglite

[English](README.md) | **简体中文**

一个**轻量化、可嵌入项目**的 DAG 工作流管理器：用 Python 类定义节点，框架负责图校验（悬空连接 / 端口冲突 / 环检测）、拓扑排序执行、节点级文件缓存，并附带一个 Web 可视化编辑器。

## 特性

- 🪶 **轻量可嵌入** - 无服务/无数据库，一个 Python 包即可嵌入你自己的项目，以库的方式定义并运行 DAG
- 🕸️ **真正的 DAG** - 执行前校验悬空连接、重复/冲突边与环形依赖，按拓扑序自动调度（乱序声明自动重排）
- 🚀 **缓存支持** - 已执行过的节点按缓存目录跳过重复执行
- 🎨 **可视化编辑器** - 基于 Web 的 DAG 编辑器，参数由节点定义、用户只填值
- 📦 **模块化设计** - 继承 `CachedSubprocess` 轻松自定义节点
- 🔧 **单一真相源** - 节点 id/名称/图标/分组/描述与端口/参数全部以 Python 注册类（`@Pipeline.register_node(icon=..., name=..., node_id=...)`）为准自动反射；**不需要 nodes.json 即可使用**，该文件只是可选的 UI 覆盖层，也可用 `--generate-nodes-json` 从注册类一键生成
- 📝 **日志记录** - 自动记录执行日志到文件
- ▶️ **单节点运行** - 在编辑器中选中节点单独运行调试
- 📂 **缓存浏览** - 一键打开节点缓存目录

## 安装

从 wheel 安装：

```bash
pip install dist/edaglite-0.5.0-py3-none-any.whl
```

## 快速开始

### 1. 定义自定义节点

```python
from edaglite import CachedSubprocess, Input, Output, Param, Pipeline

# icon/name/group/description 是面板展示信息，均可省略；
# node_id 是类型标识（默认取类名），面板与 workspace.json 用它定位类型。
@Pipeline.register_node(icon="📦", name="My Node")
class MyNode(CachedSubprocess):
    # 端口与参数声明即为唯一真相，编辑器面板自动反射，无需任何 JSON 配置
    inputs = [Input("input", description="Input data")]
    outputs = [Output("output", description="Output data")]
    params = [Param("value", description="Some parameter", value="default")]

    def _execute(self):
        input_path = self.require_input("input")
        # 处理...
        # 输出文件名与输出端口名保持一致（无扩展名）；扩展名由节点按数据类型自定
        with open(self.cache_path("output"), "w") as f:
            # 写输出
            pass
```

**用类型注解声明参数（推荐）**：标量类属性加 `int` / `float` / `str` 注解后，
装饰器自动生成对应 `Param`（含 `Optional[X]` / `X | None`），无需手写 `params`：

```python
@Pipeline.register_node(icon="🎓")
class StudentGenerator(CachedSubprocess):
    outputs = [Output("students.csv")]

    count: int = 10        # 等价于 Param("count", value=10, param_type="int")
    ratio: float = 0.5     # param_type="float"
    prefix: str = "S"      # param_type="string"
    tag: Optional[str] = None
    # bool/list/dict 等无对应前端控件的注解会被忽略；
    # 同名时显式 params=[Param(...)] 优先于注解
```

### 2. 准备 workspace 目录结构

只需要 `workspace.json`（DAG 连接配置）即可。节点面板的全部信息（端口、参数、
图标、展示名）由框架从 Python 注册类反射，**nodes.json 可以完全不存在**。
`nodes.json` 只在一种场景下有用：不想改 Python 代码、又想在外部调整图标/展示名，
它是一个**不参与执行**的 UI 覆盖层，可放在项目级供多个 workspace 共享：

```
my_project/
├── nodes.json       # 完全可选 - 项目级 UI 覆盖层，所有 workspace 共享
└── workspaces/
    ├── ws_a/
    │   └── workspace.json   # DAG 连接配置（唯一必需文件）
    └── ws_b/
        ├── nodes.json       # 可选 - workspace 内副本，就近优先，覆盖项目级
        └── workspace.json
```

覆盖层查找顺序：**workspace 目录 → 逐级父目录**（首个命中生效）。

### 3. （可选）nodes.json 覆盖层与动态生成

覆盖层只接受纯展示字段，按 `id`（注册类型 id，即默认类名或 `node_id`）匹配
已注册节点；端口、参数即使写在文件里也会被忽略——它们唯一以 Python 注册类中的
`inputs` / `outputs` / `params` 声明为准。展示字段的优先级为：

```
nodes.json 覆盖层  >  register_node(...) 元数据  >  默认值（类名 / 🧩 / docstring 首行）
```

不想手写时，可让 viewer 从当前注册类**动态生成**一份脚手架（已存在则不会覆盖），
随后在文件里微调即可：

```bash
# 默认导出到 <workspace>/nodes.json
edaglite-viewer --workspace ./my_project/workspaces/ws_a --generate-nodes-json

# 或指定导出路径（如项目级共享文件）
edaglite-viewer -w ./ws --generate-nodes-json ../nodes.json
```

生成的文件形如：

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

若希望编辑器**完全无视**磁盘上的 nodes.json（比如排查"文件内容与面板不一致"
问题），加 `--no-overlay` 即可。

> 覆盖层引用了未注册的节点类型时，该条目会被忽略并在启动日志中告警；
> 没有任何注册节点时，编辑器面板显示空状态提示而不是内置假节点。
> 自定义 `node_id` 后，用旧 id 保存的 workspace.json 会被视为未注册节点。

### 4. 启动可视化编辑器

```bash
# 指定 workspace 目录；无需 nodes.json，面板直接反射已导入的注册类
edaglite-viewer --workspace ./my_project/workspaces/ws_a --port 8080
```

> **注意**：`edaglite-viewer` 是通用框架入口，不包含任何业务节点。
> 你需要在启动前导入自定义节点类（通过 `@Pipeline.register_node` 注册），
> 或者使用启动脚本的方式（参考 `demo/run_demo.py`）。

然后打开浏览器访问 http://localhost:8080 即可开始编辑。

### 5. 命令行运行 DAG

```bash
edaglite-run --pipeline ./my_workspace/workspace.json
```

working folder 自动使用 `workspace.json` 所在目录，不需要额外指定。

### 6. 清理缓存和日志

```bash
edaglite-clean --pipeline ./my_workspace/workspace.json
```

## 运行示例

首先需要安装包：

```bash
pip install dist/edaglite-0.5.0-py3-none-any.whl
```

安装完成后使用启动脚本体验示例：

```bash
# 使用启动脚本（自动注册 demo 节点并启动编辑器）
python demo/run_demo.py
```

或者源码运行（无需安装）：

```bash
cd edaglite
python demo/run_demo.py
```

示例中已经包含：
- `demo/demo_nodes.py` - 示例节点的 Python 实现（图标通过 `register_node(icon=...)` 声明，无 nodes.json）
- `demo/test_workspace/workspace.json` - 已经连接好的完整 DAG 配置

**如果提示命令找不到**，说明 Python 的 Scripts 目录没有在 PATH 中，可以使用 python -m 方式运行：

```bash
python -m edaglite.pipeline_viewer --workspace ./my_workspace --port 8080
```

## 命令行工具

| 命令 | 说明 | 示例 |
|------|------|------|
| `edaglite-run` | 运行 DAG | `edaglite-run --pipeline ./workspace/workspace.json [-f]` |
| `edaglite-viewer` | 启动可视化编辑器 | `edaglite-viewer --workspace ./workspace [--port 8080] [--open] [--no-overlay] [--generate-nodes-json [PATH]]` |
| `edaglite-clean` | 清理缓存 | `edaglite-clean --pipeline ./workspace/workspace.json` |

### 参数说明

**edaglite-run**:
- `--pipeline, -p` - workspace.json 文件路径 (必需)
- `--force, -f` - 强制重新执行，忽略缓存 (可选)

working folder 自动使用 `workspace.json` 所在目录，不需要额外指定。

**edaglite-viewer**:
- `--workspace, -w` - 工作目录（nodes.json 覆盖层沿该目录及父目录链查找）(可选)
- `--port, -p` - 监听端口，默认 8080 (可选)
- `--host` - 绑定地址，默认 localhost (可选)
- `--open, -o` - 自动打开浏览器 (可选)
- `--no-overlay` - 完全忽略 nodes.json，面板元数据只取注册类 (可选)
- `--generate-nodes-json [PATH]` - 启动前从注册类导出 nodes.json 脚手架（默认 `<workspace>/nodes.json`，已存在不覆盖）(可选)

**edaglite-clean**:
- `--pipeline, -p` - workspace.json 文件路径 (必需)

## Python API 使用

```python
from edaglite import Pipeline, CachedSubprocess

# 从 JSON 加载 DAG
pipeline = Pipeline.load_from_json("workspace.json", "./workspace")
pipeline.run()

# 运行单个节点（按前端节点 ID）
pipeline.run_node_by_frontend_id(1)
```

## 项目结构

```
edaglite/
├── edaglite/                   # Python 包（会被打包进 wheel）
│   ├── __init__.py          # 包初始化，导出公共 API
│   ├── pipeline.py          # 核心：Pipeline, CachedSubprocess, Context 等
│   ├── pipeline_viewer.py   # Web 可视化编辑器
│   ├── run.py               # edaglite-run 命令入口
│   ├── clean.py             # edaglite-clean 命令入口
│   └── web/                 # Web 静态资源
│       ├── index.html
│       └── js/
│           ├── app.js
│           ├── connections.js
│           └── properties.js
├── demo/                    # 示例工作区（不会打包进 wheel）
│   ├── demo_nodes.py        # 示例节点 Python 实现（含 register_node 图标元数据）
│   ├── run_demo.py          # 示例启动脚本
│   ├── run_pipeline.py      # 命令行运行脚本
│   ├── view_pipeline.py     # 启动可视化编辑器脚本
│   └── test_workspace/
│       └── workspace.json
├── dist/
│   └── edaglite-0.5.0-py3-none-any.whl
├── README.md
├── README.zh-CN.md
└── pyproject.toml
```

`demo/` 目录是项目源码中的示例，**不会被打包进 wheel**。安装包后不包含这个目录。

## 依赖

- Python >= 3.8
- eel >= 0.16.0
- bottle >= 0.12.25
- gevent >= 23.9.1
- greenlet >= 2.0.2
- colorama >= 0.4.6
- typing-extensions >= 4.8.0

## 许可证

Apache License 2.0，详见 [LICENSE](LICENSE)。
