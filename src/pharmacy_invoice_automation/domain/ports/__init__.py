"""
Abstract port interfaces the future Application layer will program
against; implemented by future Infrastructure adapters.

Repository Ports (ports.repositories): PurchaseInvoiceRepository,
MedicineRepository, SupplierRepository, BatchRepository,
ManufacturerRepository, ProjectRepository.

External Service Ports (ports.services): OCRProvider,
BrowserAutomationProvider, AIProvider, FileStorageProvider,
PriceLookupProvider, NotificationProvider.

Renamed per Stage 04: no "I" prefix (e.g. "IInvoiceRepository" is now
"PurchaseInvoiceRepository"). Import from the specific subpackage,
e.g.:

    from pharmacy_invoice_automation.domain.ports.repositories import (
        PurchaseInvoiceRepository,
    )
    from pharmacy_invoice_automation.domain.ports.services import OCRProvider
"""
