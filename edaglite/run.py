#!/usr/bin/env python3
"""Command-line script to run pipeline from workspace.json."""

import os
from edaglite import Pipeline


def main():
    """Main entry point for running pipeline."""
    import argparse
    parser = argparse.ArgumentParser(description='Run pipeline from workspace.json')
    parser.add_argument('--pipeline', '-p', required=True, help='Path to workspace.json')
    parser.add_argument('--force', '-f', action='store_true', help='Force re-execution')
    args = parser.parse_args()

    # Use the directory containing workspace.json as the working folder
    working_folder = os.path.dirname(os.path.abspath(args.pipeline))
    pipeline = Pipeline.load_from_json(args.pipeline, working_folder)
    pipeline.force = args.force
    pipeline.run()


if __name__ == "__main__":
    main()
