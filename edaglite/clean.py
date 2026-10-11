#!/usr/bin/env python3
"""Command-line script to clean pipeline cache and logs."""

import sys
import os
from edaglite import Pipeline


def main():
    """Main entry point for cleaning pipeline."""
    import argparse
    parser = argparse.ArgumentParser(description='Clean pipeline cache and logs')
    parser.add_argument('--pipeline', '-p', required=True, help='Path to workspace.json')
    args = parser.parse_args()

    working_folder = os.path.dirname(os.path.abspath(args.pipeline))
    pipeline = Pipeline.load_from_json(args.pipeline, working_folder)
    pipeline.clean()


if __name__ == "__main__":
    main()
