# Pipeline Manager

一个带缓存支持的管道执行框架，附带可视化编辑器。

## 特性

- 🚀 **缓存支持** - 已执行过的阶段会被缓存，跳过重复执行
- 🎨 **可视化编辑器** - 基于 Web 的可视化管道编辑器
- 📦 **模块化设计** - 继承 `CachedSubprocess` 轻松自定义节点
- 🔧 **灵活配置** - `nodes.json` 在每个 workspace 自定义节点类型
- 📝 **日志记录** - 自动记录执行日志到文件

## 安装

从 wheel 安装：

```bash
pip install dist/pipeline_manager-0.1.0-py3-none-any.whl
```

## 快速开始

### 1. 定义自定义节点

```python
from pipeline_manager import CachedSubprocess, Input, Output, Param, Pipeline

register_node = Pipeline.register_node

@register_node
class MyNode(CachedSubprocess):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.name = "MyNode"
        self.inputs = [Input(name="input", description="Input data")]
        self.outputs = [Output(name="output", description="Output data")]
        self.params = [Param(name="value", description="Some parameter", value="default")]
    
    def _execute(self):
        input_path = self.require_input("input")
        # 处理...
        with open(self.cache_path("output.csv"), "w") as f:
            # 写输出
            pass
```

### 2. 准备 workspace 目录结构

每个 workspace 目录需要两个固定文件名：

```
my_workspace/
├── nodes.json      # 必需 - 定义可用节点类型（给编辑器用）
└── workspace.json  # 可选 - 保存管道连接配置
```

### 3. 创建 nodes.json

在 `nodes.json` 中定义可用节点类型：

```json
{
    "nodes": [
        {
            "id": "MyNode",
            "name": "My Node",
            "icon": "📦",
            "description": "My custom node",
            "inputs": [{"name": "input", "description": "Input description"}],
            "outputs": [{"name": "output", "description": "Output description"}],
            "params": [{"name": "value", "description": "Parameter description", "type": "string", "value": "default"}]
        }
    ]
}
```

### 4. 启动可视化编辑器

```bash
# 指定 workspace 目录（包含 nodes.json）
pipeline-viewer --workspace ./my_workspace --port 8080
```

然后打开浏览器访问 http://localhost:8080 即可开始编辑。

### 5. 命令行运行管道

```bash
pipeline-run --pipeline ./my_workspace/workspace.json
```

working folder 自动使用 `workspace.json` 所在目录，不需要额外指定。

### 6. 清理缓存和日志

```bash
pipeline-clean --pipeline ./my_workspace/workspace.json
```

## 命令行工具

| 命令 | 说明 | 示例 |
|------|------|------|
| `pipeline-run` | 运行管道 | `pipeline-run --pipeline pipeline.json --working-folder ./workspace [-f]` |
| `pipeline-viewer` | 启动可视化编辑器 | `pipeline-viewer --workspace ./workspace [--port 8080] [--open]` |
| `pipeline-clean` | 清理缓存 | `pipeline-clean --pipeline pipeline.json` |

### 参数说明

**pipeline-run**:
- `--pipeline, -p` - workspace.json 文件路径 (必需)
- `--force, -f` - 强制重新执行，忽略缓存 (可选)

working folder 自动使用 `workspace.json` 所在目录，不需要额外指定。

**pipeline-viewer**:
- `--workspace, -w` - 工作目录，包含 nodes.json (可选)
- `--port, -p` - 监听端口，默认 8080 (可选)
- `--host` - 绑定地址，默认 localhost (可选)
- `--open, -o` - 自动打开浏览器 (可选)

**pipeline-clean**:
- `--pipeline, -p` - workspace.json 文件路径 (必需)

## Python API 使用

```python
from pipeline_manager import Pipeline, CachedSubprocess

# 从 JSON 加载管道
pipeline = Pipeline.load_from_json("workspace.json", "./workspace")
pipeline.run()
```

## 项目结构

```
pipeline_manager/
├── pipeline_manager/             # Python 包（会被打包进 wheel）
│   ├── __init__.py          # 包初始化，导出公共 API
│   ├── pipeline.py          # 核心：Pipeline, CachedSubprocess, Context 等
│   ├── pipeline_viewer.py   # Web 可视化编辑器
│   ├── run.py              # pipeline-run 命令入口
│   ├── clean.py            # pipeline-clean 命令入口
│   └── web/                 # Web 静态资源
│       ├── index.html
│       ├── test.html
│       └── js/
│           ├── app.js
│           ├── connections.js
│           └── properties.js
├── demo/                    # 示例工作区（不会打包进 wheel）
│   ├── pipeline_workspace/
│   │   ├── nodes.json
│   │   └── workspace.json
│   └── test_workspace/
│       ├── nodes.json
│       └── workspace.json
├── dist/
│   └── pipeline_manager-0.1.0-py3-none-any.whl
├── README.md
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

MIT
