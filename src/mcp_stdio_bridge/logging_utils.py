# SPDX-License-Identifier: Unlicense
"""
Logging Utilities
=================

Provides functions for configuring the Python logging subsystem, supporting
YAML, JSON, and INI external configuration files. Ensures that logging
output is directed to sys.stderr by default to maintain compatibility
with the MCP stdio transport.
"""
import os
import sys
import logging
import logging.config
import yaml
import json
from typing import Optional

# Pre-defined logger name used throughout the application.
logger = logging.getLogger("mcp-bridge")

def configure_logging(level_name: str, config_file: Optional[str] = None) -> bool:
    """
    Set up the logging subsystem using either a custom file or standard basicConfig.

    Args:
        level_name (str): The desired logging level (e.g., "INFO", "DEBUG").
        config_file (Optional[str]): Path to a custom logging configuration file.

    Returns:
        bool: True if a custom configuration file was successfully loaded,
              False if the application reverted to default basicConfig.
    """
    if config_file and os.path.exists(config_file):
        try:
            ext = os.path.splitext(config_file)[1].lower()
            if ext in ('.yaml', '.yml'):
                with open(config_file, 'rt') as f:
                    config = yaml.safe_load(f.read())
                logging.config.dictConfig(config)
            elif ext == '.json':
                with open(config_file, 'rt') as f:
                    config = json.loads(f.read())
                logging.config.dictConfig(config)
            else:
                # Fallback to INI/Conf format for standard Python log config files.
                logging.config.fileConfig(config_file, disable_existing_loggers=False)
            return True
        except Exception as e:
            print(f"Error loading logging configuration from {config_file}: {e}", file=sys.stderr)

    # Default logging setup explicitly uses sys.stderr to avoid stdout protocol corruption.
    numeric_level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stderr,
        force=True
    )
    return False
