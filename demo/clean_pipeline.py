#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Clean the pipeline cache for a given workspace.

Usage:
    python demo/clean_pipeline.py <workspace>

Examples:
    python demo/clean_pipeline.py test_workspace
    python demo/clean_pipeline.py demo/test_workspace

Arguments:
    workspace    Workspace name (under demo/) or a workspace directory path
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edaglite import Pipeline

# Register all demo nodes in Pipeline.NODE_REGISTRY
import demo.demo_nodes  # noqa: F401


def main():
    parser = argparse.ArgumentParser(description='Clean the pipeline cache for a given workspace')
    parser.add_argument('workspace', help='Workspace name (under demo/) or a workspace directory path')
    args = parser.parse_args()

    # Support a direct path or a workspace name
    ws_path = Path(args.workspace)
    if ws_path.is_dir():
        workspace_dir = str(ws_path.resolve())
    elif (ROOT / "demo" / args.workspace).is_dir():
        workspace_dir = str((ROOT / "demo" / args.workspace).resolve())
    else:
        print(f"Error: workspace not found: {args.workspace}")
        sys.exit(1)

    pipeline_json = os.path.join(workspace_dir, 'workspace.json')
    if not os.path.exists(pipeline_json):
        print(f"Error: pipeline config file not found: {pipeline_json}")
        sys.exit(1)

    print(f"[INFO] Cleaning workspace: {workspace_dir}")

    pipeline = Pipeline.load_from_json(pipeline_json, workspace_dir)
    pipeline.clean()

    print(f"[INFO] Cleanup complete")


if __name__ == '__main__':
    main()
