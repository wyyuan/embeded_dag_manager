"""
Pipeline Manager - A cached pipeline execution framework with visual editor.

This package provides a flexible framework for building and executing
data processing pipelines with caching support and a web-based visual editor.
"""

__version__ = "0.1.0"
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
