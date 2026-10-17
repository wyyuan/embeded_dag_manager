#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run the pipeline for a given workspace (project-side launcher).

Usage:
    python demo/run_pipeline.py <workspace> [--force]
    python demo/run_pipeline.py --pipeline demo/test_workspace [--force]
    python demo/run_pipeline.py                # list all workspaces under demo/

Examples:
    python demo/run_pipeline.py test_workspace
    python demo/run_pipeline.py test_workspace --force
    python demo/run_pipeline.py --pipeline demo/test_workspace/workspace.json

Arguments:
    workspace         Workspace name (under demo/) or path to workspace.json
    --force, -f       Force re-execution of all stages (skip cache)
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edaglite import Pipeline

# Register all demo nodes in Pipeline.NODE_REGISTRY
import demo.demo_nodes  # noqa: F401


def find_workspaces() -> list[Path]:
    """Find all subdirectories under demo/ that contain a workspace.json."""
    demo_dir = ROOT / "demo"
    if not demo_dir.exists():
        return []
    return sorted(demo_dir.glob("*/workspace.json"))


def select_workspace() -> Path:
    """Interactively select a workspace."""
    workspaces = find_workspaces()
    if not workspaces:
        print("Error: no workspace found under demo/ (a directory containing workspace.json)")
        sys.exit(1)

    print("\nSelect a workspace:")
    for i, ws in enumerate(workspaces, 1):
        ws_dir = ws.parent
        cache_dir = ws_dir / "cache"
        cache_count = len(list(cache_dir.iterdir())) if cache_dir.exists() else 0
        print(f"  {i}. {ws_dir.name}")
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


def resolve_workspace(arg: str) -> Path:
    """Resolve user input into a workspace.json path.

    Supports three forms:
      - Direct path: demo/test_workspace/workspace.json
      - Directory path: demo/test_workspace
      - Workspace name: test_workspace (looked up under demo/)
    """
    p = Path(arg)
    if p.is_file():
        return p.resolve()
    if p.is_dir():
        ws = p / "workspace.json"
        if ws.exists():
            return ws.resolve()
    # Treat as a workspace name and look it up under demo/
    name_p = ROOT / "demo" / arg / "workspace.json"
    if name_p.exists():
        return name_p.resolve()
    print(f"Error: pipeline config file not found: {arg}")
    sys.exit(1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the pipeline for a given workspace")
    ap.add_argument("--pipeline", "-p", default=None,
                    help="Path to workspace.json or its parent directory")
    ap.add_argument("--force", "-f", action="store_true",
                    help="Force re-execution of all stages (skip cache)")
    ap.add_argument("workspace", nargs="?",
                    help="Workspace name (under demo/) or path to workspace.json")
    args = ap.parse_args(argv)

    # Determine the workspace.json path
    if args.pipeline:
        ws = resolve_workspace(args.pipeline)
    elif args.workspace:
        ws = resolve_workspace(args.workspace)
    else:
        ws = select_workspace()

    working_folder = str(ws.parent)
    print(f"[INFO] Loading pipeline config: {ws}")
    print(f"[INFO] Workspace directory: {working_folder}")
    print(f"[INFO] Force mode: {args.force}")
    print(f"[INFO] Registered nodes: {len(Pipeline.NODE_REGISTRY)}")

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
