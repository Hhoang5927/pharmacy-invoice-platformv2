"""
External Service Ports: abstract contracts for capabilities outside
the Domain layer's control (OCR, browser automation, AI, file storage,
price lookup, notifications).

Per Stage 04's exact examples: OCRProvider, BrowserAutomationProvider,
AIProvider, FileStorageProvider, PriceLookupProvider,
NotificationProvider. (SettingsProvider and Logger, present in the
prior Domain Layer build, are intentionally dropped here -- Stage 04's
own External Service Ports list does not include them, and Stage 04's
architecture rules explicitly forbid the Domain layer from performing
logging or knowing about configuration/DI, so this omission is honored
rather than re-added.)
"""

from pharmacy_invoice_automation.domain.ports.services.ai_provider import AIProvider
from pharmacy_invoice_automation.domain.ports.services.browser_automation_provider import (
    AutomationOutcome,
    BrowserAutomationProvider,
)
from pharmacy_invoice_automation.domain.ports.services.file_storage_provider import (
    FileStorageProvider,
)
from pharmacy_invoice_automation.domain.ports.services.notification_provider import (
    NotificationProvider,
)
from pharmacy_invoice_automation.domain.ports.services.ocr_provider import OCRProvider
from pharmacy_invoice_automation.domain.ports.services.price_lookup_provider import (
    PriceLookupProvider,
)

__all__ = [
    "OCRProvider",
    "BrowserAutomationProvider",
    "AutomationOutcome",
    "AIProvider",
    "FileStorageProvider",
    "PriceLookupProvider",
    "NotificationProvider",
]
