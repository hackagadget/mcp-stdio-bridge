# SPDX-License-Identifier: Unlicense
"""
Mode Sub-package
================

Implements the different operation modes of the bridge:
- proxy: Transparently forwards MCP traffic to an external process.
- wrapper: Exposes local CLI utilities as secure MCP tools.
"""
from .proxy import bridge_streams
from .wrapper import create_wrapper_server

__all__ = ["bridge_streams", "create_wrapper_server"]
