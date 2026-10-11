#!/usr/bin/env python3
"""Launcher for the demo pipeline viewer.

Registers demo node types and starts the web UI with the test workspace.
Usage: python demo/run_demo.py
"""

import os
import sys

# Ensure the project root is on the path so edaglite is importable
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 1. Register demo node types BEFORE the viewer starts
import demo_nodes  # noqa: F401

# 2. Start the viewer with the demo workspace
from edaglite.pipeline_viewer import run_viewer

workspace = os.path.join(project_root, 'demo', 'test_workspace')
run_viewer(host='localhost', port=8080, open_browser=True, workspace=workspace)