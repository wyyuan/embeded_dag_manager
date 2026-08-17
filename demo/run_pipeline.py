#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""运行指定工作区的 pipeline（项目侧启动器）。

用法:
    python demo/run_pipeline.py <workspace> [--force]
    python demo/run_pipeline.py --pipeline demo/test_workspace [--force]
    python demo/run_pipeline.py                # 列出 demo/ 下所有工作区

示例:
    python demo/run_pipeline.py test_workspace
    python demo/run_pipeline.py test_workspace --force
    python demo/run_pipeline.py --pipeline demo/test_workspace/workspace.json

参数:
    workspace         工作区名称（位于 demo/ 目录下）或 workspace.json 路径
    --force, -f       强制重新执行所有阶段（跳过缓存）
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_manager import Pipeline

# 注册所有 demo 节点到 Pipeline.NODE_REGISTRY
import demo.demo_nodes  # noqa: F401


def find_workspaces() -> list[Path]:
    """搜索 demo/ 目录下所有包含 workspace.json 的子目录。"""
    demo_dir = ROOT / "demo"
    if not demo_dir.exists():
        return []
    return sorted(demo_dir.glob("*/workspace.json"))


def select_workspace() -> Path:
    """交互式选择工作区。"""
    workspaces = find_workspaces()
    if not workspaces:
        print("错误: demo/ 目录下没有找到工作区（包含 workspace.json 的目录）")
        sys.exit(1)

    print("\n请选择工作区:")
    for i, ws in enumerate(workspaces, 1):
        ws_dir = ws.parent
        cache_dir = ws_dir / "cache"
        cache_count = len(list(cache_dir.iterdir())) if cache_dir.exists() else 0
        print(f"  {i}. {ws_dir.name}")
        print(f"     目录: {ws_dir}")
        print(f"     缓存节点数: {cache_count}")

    while True:
        try:
            choice = input(f"\n请输入序号 (1-{len(workspaces)}): ")
            idx = int(choice) - 1
            if 0 <= idx < len(workspaces):
                return workspaces[idx]
            else:
                print(f"请输入 1-{len(workspaces)} 之间的数字")
        except ValueError:
            print("请输入有效数字")


def resolve_workspace(arg: str) -> Path:
    """将用户输入解析为 workspace.json 路径。

    支持三种形式:
      - 直接路径: demo/test_workspace/workspace.json
      - 目录路径: demo/test_workspace
      - 工作区名称: test_workspace （在 demo/ 下查找）
    """
    p = Path(arg)
    if p.is_file():
        return p.resolve()
    if p.is_dir():
        ws = p / "workspace.json"
        if ws.exists():
            return ws.resolve()
    # 当作工作区名称，在 demo/ 下查找
    name_p = ROOT / "demo" / arg / "workspace.json"
    if name_p.exists():
        return name_p.resolve()
    print(f"错误: 未找到 pipeline 配置文件: {arg}")
    sys.exit(1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="运行指定工作区的 pipeline")
    ap.add_argument("--pipeline", "-p", default=None,
                    help="workspace.json 路径或其父目录")
    ap.add_argument("--force", "-f", action="store_true",
                    help="强制重新执行所有阶段（跳过缓存）")
    ap.add_argument("workspace", nargs="?",
                    help="工作区名称（位于 demo/ 目录下）或 workspace.json 路径")
    args = ap.parse_args(argv)

    # 确定 workspace.json 路径
    if args.pipeline:
        ws = resolve_workspace(args.pipeline)
    elif args.workspace:
        ws = resolve_workspace(args.workspace)
    else:
        ws = select_workspace()

    working_folder = str(ws.parent)
    print(f"[INFO] 加载 pipeline 配置: {ws}")
    print(f"[INFO] 工作区目录: {working_folder}")
    print(f"[INFO] 强制模式: {args.force}")
    print(f"[INFO] 已注册节点: {len(Pipeline.NODE_REGISTRY)}")

    try:
        pipeline = Pipeline.load_from_json(str(ws), working_folder)
        pipeline.force = args.force
        pipeline.run()
    except SystemExit as exc:
        if exc.code:
            return int(exc.code)
    except Exception as exc:
        print(f"[ERR] pipeline failed: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
