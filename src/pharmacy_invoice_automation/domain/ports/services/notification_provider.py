"""
Service Port: NotificationProvider.

Abstract user-notification contract -- new per Stage 04. Covers
surfacing significant events (e.g. "batch complete," "N invoices
failed") to the user through whatever mechanism the eventual desktop
UI chooses (a system tray notification, an in-app banner, or similar),
without the Domain layer knowing which.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class NotificationProvider(ABC):
    """Abstract contract for notifying the user of a significant event."""

    @abstractmethod
    def notify(self, title: str, message: str, level: str = "info") -> None:
        """
        Notify the user. ``level`` is one of "info", "warning", or
        "error", letting the implementation choose appropriate styling
        without the Domain layer needing to know what that styling is.
        """
