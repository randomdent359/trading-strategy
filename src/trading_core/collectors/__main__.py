"""Allow running collectors as: python -m trading_core.collectors <name>."""

import sys


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m trading_core.collectors <hyperliquid|polymarket>")
        sys.exit(1)

    name = sys.argv[1]
    # Remove the subcommand so the collector's argparse doesn't see it.
    sys.argv = [sys.argv[0]] + sys.argv[2:]

    if name == "hyperliquid":
        from trading_core.collectors.hyperliquid import main as hl_main
        hl_main()
    elif name == "polymarket":
        from trading_core.collectors.polymarket import main as pm_main
        pm_main()
    else:
        print(f"Unknown collector: {name}")
        sys.exit(1)


main()
