import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_nodes
from pipeline import load_pipeline_from_json, Pipeline

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Run pipeline from JSON')
    parser.add_argument('--pipeline', '-p', required=True, help='Path to pipeline.json')
    parser.add_argument('--working-folder', '-w', required=True, help='Working folder')
    parser.add_argument('--force', '-f', action='store_true', help='Force re-execution')
    args = parser.parse_args()

    pipeline = load_pipeline_from_json(args.pipeline, args.working_folder)
    pipeline.force = args.force
    pipeline.run()
