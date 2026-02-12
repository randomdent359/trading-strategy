"""Allow running paper engine as: python -m trading_core.paper [--config path]."""

import argparse

from trading_core.paper.runner import main

parser = argparse.ArgumentParser(description="Paper trading engine")
parser.add_argument("--config", default=None, help="Path to config.yaml")
args = parser.parse_args()
main(config_path=args.config)
