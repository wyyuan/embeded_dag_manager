"""
edaglite - A lightweight, embeddable DAG workflow manager with a visual editor.

edaglite provides a small framework for defining DAG workflows as Python
classes (nodes with named input/output ports), validating the graph
(dangling edges, port conflicts, cycles), running it in topological order
with per-node file caching, and optionally editing it in a web UI.
"""

__version__ = "0.4.0"
__author__ = "Your Name"

from .pipeline import (
    Input,
    Output,
    Param,
    Context,
    CachedSubprocess,
    Pipeline,
)

__all__ = [
    "Input",
    "Output",
    "Param",
    "Context",
    "CachedSubprocess",
    "Pipeline",
]
