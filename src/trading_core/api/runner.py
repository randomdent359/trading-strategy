#!/usr/bin/env python3
"""FastAPI server runner."""

import uvicorn
import structlog

from trading_core.logging.setup import setup_logging
from trading_core.api.app import app

logger = structlog.get_logger()


def main():
    """Run the FastAPI server."""
    setup_logging()

    logger.info("Starting FastAPI server", port=8000)

    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8000,
            log_config=None  # Use our structlog setup
        )
    except Exception as e:
        logger.error("Failed to start server", error=str(e))
        raise


if __name__ == "__main__":
    main()