#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""清理指定工作区的 pipeline 缓存。

用法:
    python demo/clean_pipeline.py <workspace>

示例:
    python demo/clean_pipeline.py test_workspace
    python demo/clean_pipeline.py demo/test_workspace

参数:
    workspace    工作区名称（位于 demo/ 目录下）或工作区目录路径
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edaglite import Pipeline

# 注册所有 demo 节点到 Pipeline.NODE_REGISTRY
import demo.demo_nodes  # noqa: F401


def main():
    parser = argparse.ArgumentParser(description='清理指定工作区的 pipeline 缓存')
    parser.add_argument('workspace', help='工作区名称（位于 demo/ 目录下）或工作区目录路径')
    args = parser.parse_args()

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

    print(f"[INFO] 清理工作区: {workspace_dir}")

    pipeline = Pipeline.load_from_json(pipeline_json, workspace_dir)
    pipeline.clean()

    print(f"[INFO] 清理完成")


if __name__ == '__main__':
    main()
