#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Launch the Pipeline Viewer visual editor.

Usage:
    python demo/view_pipeline.py [<workspace>]

Examples:
    python demo/view_pipeline.py test_workspace
    python demo/view_pipeline.py              # show the selection prompt

Arguments:
    workspace    Workspace name (under demo/, optional) or a workspace directory path
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def find_workspaces(base_dir):
    """Find all subdirectories under demo/ that contain a workspace.json."""
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
        print("Error: no workspace found under demo/ (a directory containing workspace.json)")
        sys.exit(1)

    print("\nSelect a workspace:")
    for i, ws in enumerate(workspaces, 1):
        ws_dir = os.path.join(base_dir, 'demo', ws)
        cache_dir = os.path.join(ws_dir, 'cache')
        cache_count = len(os.listdir(cache_dir)) if os.path.exists(cache_dir) else 0
        print(f"  {i}. {ws}")
        print(f"     Directory: {ws_dir}")
        print(f"     Cached nodes: {cache_count}")

    while True:
        try:
            choice = input(f"\nEnter a number (1-{len(workspaces)}): ")
            idx = int(choice) - 1
            if 0 <= idx < len(workspaces):
                return workspaces[idx]
            else:
                print(f"Please enter a number between 1 and {len(workspaces)}")
        except ValueError:
            print("Please enter a valid number")


def main():
    parser = argparse.ArgumentParser(description='Launch the Pipeline Viewer visual editor')
    parser.add_argument('workspace', nargs='?', help='Workspace name (under demo/) or a workspace directory path')
    args = parser.parse_args()

    base_dir = str(ROOT)

    if not args.workspace:
        args.workspace = select_workspace(base_dir)

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

    print(f"[INFO] Starting Pipeline Viewer")
    print(f"[INFO] Workspace directory: {workspace_dir}")
    print(f"[INFO] Waiting for the browser to open...")

    # Call run_viewer() directly instead of via subprocess
    from edaglite.pipeline_viewer import run_viewer

    # The node definitions must be imported before startup to trigger
    # @Pipeline.register_node registration; otherwise every node type on the
    # canvas is treated as "unregistered" and cannot run
    # (kept consistent with run_pipeline.py / run_demo.py)
    import demo.demo_nodes  # noqa: F401

    run_viewer(host='localhost', port=8080, open_browser=True, workspace=workspace_dir)


if __name__ == '__main__':
    main()
