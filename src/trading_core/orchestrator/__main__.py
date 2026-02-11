"""Allow running orchestrator as: python -m trading_core.orchestrator [--config path]."""

import argparse

from trading_core.orchestrator.runner import main

parser = argparse.ArgumentParser(description="Strategy orchestrator")
parser.add_argument("--config", default=None, help="Path to config.yaml")
args = parser.parse_args()
main(config_path=args.config)
