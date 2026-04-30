# SPDX-License-Identifier: Unlicense
"""
Shared Utilities
================
Common helper functions and classes used across the bridge.
"""

import anyio
from typing import Dict, Any


class ExponentialBackoff:
    """
    Stateful exponential backoff helper.
    
    Tracks retry attempts and calculates delay periods based on the
    configured base delay, maximum delay, and multiplier.
    """

    def __init__(self, settings: Dict[str, Any]):
        self.max_retries: int = settings.get("max_retries", 0)
        self.base_delay: float = settings.get("retry_delay", 1.0)
        self.max_delay: float = settings.get("retry_max_delay", 60.0)
        self.multiplier: float = settings.get("retry_multiplier", 2.0)
        self.attempts: int = 0

    def get_delay(self) -> float:
        """Calculate the current delay based on the number of attempts."""
        if self.attempts == 0:
            return 0.0
        return min(
            self.base_delay * (self.multiplier ** (self.attempts - 1)),
            self.max_delay
        )

    async def wait(self) -> bool:
        """
        Wait for the next backoff period.
        
        Returns:
            bool: True if we can retry (haven't exceeded max_retries), False otherwise.
        """
        if self.attempts >= self.max_retries and self.max_retries > 0:
            return False

        self.attempts += 1
        delay = self.get_delay()
        if delay > 0:
            await anyio.sleep(delay)
        return True

    def reset(self) -> None:
        """Reset the attempt counter."""
        self.attempts = 0

    def can_retry(self) -> bool:
        """Check if another retry attempt is permitted."""
        if self.max_retries <= 0:
            return False
        return self.attempts < self.max_retries
