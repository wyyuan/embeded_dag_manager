#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启动 Pipeline Viewer 可视化编辑器。

用法:
    python demo/view_pipeline.py [<workspace>]

示例:
    python demo/view_pipeline.py test_workspace
    python demo/view_pipeline.py              # 弹出选择界面

参数:
    workspace    工作区名称（位于 demo/ 目录下，可选）或工作区目录路径
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def find_workspaces(base_dir):
    """搜索 demo/ 目录下所有包含 workspace.json 的子目录。"""
    demo_dir = os.path.join(base_dir, 'demo')
    if not os.path.exists(demo_dir):
        return []
    workspaces = []
    for item in os.listdir(demo_dir):
        item_path = os.path.join(demo_dir, item)
        if os.path.isdir(item_path):
            workspace_json = os.path.join(item_path, 'workspace.json')
            if os.path.exists(workspace_json):
                workspaces.append(item)
    return workspaces


def select_workspace(base_dir):
    workspaces = find_workspaces(base_dir)
    if not workspaces:
        print("错误: demo/ 目录下没有找到工作区（包含 workspace.json 的目录）")
        sys.exit(1)

    print("\n请选择工作区:")
    for i, ws in enumerate(workspaces, 1):
        ws_dir = os.path.join(base_dir, 'demo', ws)
        cache_dir = os.path.join(ws_dir, 'cache')
        cache_count = len(os.listdir(cache_dir)) if os.path.exists(cache_dir) else 0
        print(f"  {i}. {ws}")
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


def main():
    parser = argparse.ArgumentParser(description='启动 Pipeline Viewer 可视化编辑器')
    parser.add_argument('workspace', nargs='?', help='工作区名称（位于 demo/ 目录下）或工作区目录路径')
    args = parser.parse_args()

    base_dir = str(ROOT)

    if not args.workspace:
        args.workspace = select_workspace(base_dir)

    # 支持直接路径或工作区名称
    ws_path = Path(args.workspace)
    if ws_path.is_dir():
        workspace_dir = str(ws_path.resolve())
    elif (ROOT / "demo" / args.workspace).is_dir():
        workspace_dir = str((ROOT / "demo" / args.workspace).resolve())
    else:
        print(f"错误: 未找到工作区: {args.workspace}")
        sys.exit(1)

    pipeline_json = os.path.join(workspace_dir, 'workspace.json')
    if not os.path.exists(pipeline_json):
        print(f"错误: 未找到 pipeline 配置文件: {pipeline_json}")
        sys.exit(1)

    print(f"[INFO] 启动 Pipeline Viewer")
    print(f"[INFO] 工作区目录: {workspace_dir}")
    print(f"[INFO] 等待浏览器打开...")

    # 直接调用 run_viewer()，而非通过 subprocess
    from edaglite.pipeline_viewer import run_viewer

    # 启动前必须先 import 节点定义，触发 @Pipeline.register_node 注册，
    # 否则画布中的节点类型会全部被判为"未注册"而无法运行
    # （与 run_pipeline.py / run_demo.py 保持一致）
    import demo.demo_nodes  # noqa: F401

    run_viewer(host='localhost', port=8080, open_browser=True, workspace=workspace_dir)


if __name__ == '__main__':
    main()
