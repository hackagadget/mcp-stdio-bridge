# SPDX-License-Identifier: Unlicense
"""
Mode Package
============
Handles the logic for different bridge operations (Proxy vs Wrapper).
"""

# We remove top-level imports here to prevent framework bleed
# (e.g. wrapper -> mcp sdk -> starlette) from leaking into proxy mode.
from typing import Any


def create_wrapper_server() -> Any:
    from .wrapper import create_wrapper_server as _create

    return _create()


def bridge_streams(*args: Any, **kwargs: Any) -> Any:
    from .proxy import bridge_streams as _bridge

    return _bridge(*args, **kwargs)
