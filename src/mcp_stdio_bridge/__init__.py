# SPDX-License-Identifier: Unlicense
"""
MCP Stdio Bridge Package
=======================

Modular implementation of the MCP SSE <-> Stdio bridge.
"""

__version__ = "1.5.0"

# --- WORKAROUND: rich.box encoding crash (Windows only) ---
# Some Windows terminal environments crash when rich.box.Box
# attempts to unpack box-drawing characters during import.
import sys

if sys.platform == "win32" and "rich.box" not in sys.modules:
    from unittest.mock import MagicMock

    class _SafeBox:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    _rich_mock = MagicMock()
    _rich_mock.Box = _SafeBox
    sys.modules["rich.box"] = _rich_mock
# ----------------------------------------------------------
